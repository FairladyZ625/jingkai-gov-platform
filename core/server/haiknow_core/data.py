"""v1 数据底座：HTTP 与 SDK 共用，同一 SQLite 锁内执行授权和写入。"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from haiknow_sdk import DataError
from .stability import AppUnavailable

class ReviewBody(BaseModel):
    appId: str
    recordId: str
    version: int = Field(strict=True, gt=0)
    assignee: str | None = None


class Requirement(BaseModel):
    appId: str | None = Field(default=None, min_length=1)
    recordId: str = Field(min_length=1)
    version: int = Field(strict=True, gt=0)
    status: Literal['draft', 'pending', 'confirmed', 'needs_info', 'recheck'] | None = None


class DecisionBody(BaseModel):
    decision: Literal['confirm', 'return', 'reassign']
    version: int = Field(strict=True, gt=0)
    comment: str = ''
    assignee: str | None = None
    require: list[Requirement] | None = None


class Reference(BaseModel):
    appId: str
    recordId: str
    version: int = Field(strict=True, gt=0)
    fileId: str | None = None


class RecordBody(BaseModel):
    project: str
    product: str | None = None
    type: str = Field(min_length=1)
    data: JsonValue
    files: list[str] = Field(default_factory=list)
    refs: list[Reference] = Field(default_factory=list)


class Revision(BaseModel):
    baseVersion: int = Field(strict=True, gt=0)


class MessageBody(BaseModel):
    model_config = ConfigDict(extra='forbid')

    idempotencyKey: str = Field(min_length=1, max_length=200)
    recipientIds: list[str] = Field(min_length=1)
    recordId: str = Field(min_length=1)
    version: int = Field(strict=True, gt=0)
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=4000)
    priority: Literal['low', 'normal', 'high', 'urgent'] = 'normal'
    expiresAt: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    requiresAcknowledgement: bool = False


def parse(model, body):
    try:
        return model.model_validate(body).model_dump()
    except ValidationError as e:
        raise DataError('invalid_request', '请求字段缺失或类型不正确', fields=[list(x['loc']) for x in e.errors()]) from e


def one(db, sql, args=()):
    return db.execute(sql, args).fetchone()


class DataService:
    def __init__(self, store, rbac, projects, apps):
        self.store, self.rbac, self.projects, self.apps = store, rbac, projects, apps
        self.blobs = store.data_dir / 'v1-blobs'
        self.blobs.mkdir(exist_ok=True)
        # 可选授权挂点：知识库安装后注入，对已登记为受限的原件按条目权限拒绝；为空时行为不变。
        self.file_guard = None
        self._reindex_cross_project_subjects()

    def _subject_field(self, app_id):
        entry = self.apps.get(app_id)
        cross = entry.manifest.get('crossProject') if entry else None
        field = cross.get('subjectField') if isinstance(cross, dict) else None
        return field if isinstance(field, str) and field else None

    @staticmethod
    def _subject_value(document, subject_field):
        value = document.get('data', {}).get(subject_field) if isinstance(document.get('data'), dict) else None
        if value is None or isinstance(value, (dict, list, bool)):
            return None
        return str(value)

    def _reindex_cross_project_subjects(self):
        with self.store._lock, self.store._db:
            db = self.store._db
            for app_id in self.apps:
                subject_field = self._subject_field(app_id)
                if not subject_field:
                    continue
                rows = db.execute('select record_id,version,document from v1_versions where record_id in (select id from v1_records where app=?)', (app_id,)).fetchall()
                for record_id, version, raw in rows:
                    value = self._subject_value(json.loads(raw), subject_field)
                    if value is not None:
                        db.execute('insert or ignore into cross_project_subjects values (?,?,?,?,?)',
                                   (app_id, record_id, version, subject_field, value))

    def _has_cross_project_grant(self, db, user, app_id, document):
        subject_field = self._subject_field(app_id)
        subject_value = self._subject_value(document, subject_field) if subject_field else None
        if subject_field is None or subject_value is None:
            return False
        roles = tuple(user.roles)
        placeholders = ','.join('?' for _ in roles) or "''"
        params = [app_id, subject_field, subject_value, user.id, *roles]
        row = db.execute(
            f"select id from cross_project_grants where app_id=? and subject_field=? "
            f"and revoked_at is null and (subject_value is null or subject_value=?) "
            f"and ((principal_type='user' and principal_id=?) or "
            f"(principal_type='role' and principal_id in ({placeholders}))) limit 1",
            params,
        ).fetchone()
        return bool(row)

    def _read_scope(self, db, user, app_id, document, *, allow_cross=False, resource_type=None, resource_id=None):
        try:
            self.projects.require(user, document['project'])
        except DataError as error:
            if error.code != 'not_found' or not allow_cross:
                raise
            self.app(user, app_id)
            if not self._has_cross_project_grant(db, user, app_id, document):
                raise error
            if resource_type and resource_id:
                self.store.audit(app_id, user.id, 'v1.cross_project.read', {
                    'resourceType': resource_type, 'resourceId': resource_id,
                    'appId': app_id,
                    'subjectField': self._subject_field(app_id),
                    'subjectValue': self._subject_value(document, self._subject_field(app_id)),
                    'project': document['project'],
                }, connection=db)
            return True
        self.app(user, app_id)
        return False

    def app(self, user, app_id, action='view'):
        if app_id not in self.apps or 'view' not in self.rbac.actions(user, app_id):
            raise DataError('not_found', '应用或资源不存在')
        entry = self.apps[app_id]
        if entry.unavailable_reason():
            raise AppUnavailable(app_id, entry.unavailable_reason(), entry.circuit.retry_after())
        if action not in self.rbac.actions(user, app_id):
            raise DataError('forbidden', '没有执行此操作的权限', action=action)

    def _record(self, db, user, app_id, rid, version=None, *, allow_cross=False, audit_cross=True):
        r = one(db, 'select app,latest from v1_records where id=?', (rid,))
        if not r or r[0] != app_id:
            raise DataError('not_found', '记录不存在')
        v = version if version is not None else r[1]
        row = one(db, 'select document from v1_versions where record_id=? and version=?', (rid, v))
        if not row:
            raise DataError('not_found', '记录版本不存在')
        document = json.loads(row[0])
        self._read_scope(db, user, app_id, document, allow_cross=allow_cross,
                         resource_type='record' if audit_cross else None,
                         resource_id=rid if audit_cross else None)
        document['status'] = one(db, 'select status from v1_states where record_id=? and version=?', (rid, v))[0]
        document.update(confirmedBy=None, confirmedAt=None)
        for (raw,) in db.execute('select d.document from v1_decisions d join v1_reviews r on r.id=d.review_id where r.record_id=? and r.version=? order by d.rowid desc', (rid, v)):
            decision = json.loads(raw)
            if decision['decision'] == 'confirm':
                document.update(confirmedBy=decision['actor'], confirmedAt=decision['createdAt'])
                break
        return document

    def get_record(self, user, app_id, rid, version=None):
        with self.store._lock, self.store._db:
            return self._record(self.store._db, user, app_id, rid, version, allow_cross=True)

    def list_records(self, user, app_id, *, project=None, status=None, type=None):
        if project is not None:
            self.projects.require(user, project)
        self.app(user, app_id)
        with self.store._lock:
            db = self.store._db
            items = []
            for (rid,) in db.execute('select id from v1_records where app=? order by rowid desc', (app_id,)).fetchall():
                try:
                    doc = self._record(db, user, app_id, rid)
                except DataError as e:
                    if e.code != 'not_found':
                        raise
                    continue
                if all(value is None or doc[key] == value for key, value in [('project', project), ('status', status), ('type', type)]):
                    items.append(doc)
            return {'items': items}

    def _file(self, db, user, fid):
        row = one(db, 'select document from v1_files where id=?', (fid,))
        if not row:
            raise DataError('not_found', '文件不存在')
        doc = json.loads(row[0])
        shared_knowledge = self.file_guard(user, fid) if self.file_guard is not None else False
        if shared_knowledge:
            self.app(user, doc['appId'])
            return doc
        try:
            self.projects.require(user, doc['project'])
        except DataError as error:
            if error.code != 'not_found':
                raise
            self.app(user, doc['appId'])
            uses = db.execute(
                'select u.record_id,u.version,v.document from v1_file_uses u '
                'join v1_versions v on v.record_id=u.record_id and v.version=u.version '
                'join v1_records r on r.id=u.record_id where u.file_id=? and r.app=?',
                (fid, doc['appId']),
            ).fetchall()
            allowed = False
            for _, _, raw in uses:
                record = json.loads(raw)
                if self._has_cross_project_grant(db, user, doc['appId'], record):
                    allowed = True
                    break
            if not allowed:
                raise error
            self.store.audit(doc['appId'], user.id, 'v1.cross_project.read', {
                'resourceType': 'file', 'resourceId': fid,
                'appId': doc['appId'],
                'subjectField': self._subject_field(doc['appId']),
                'subjectValue': self._subject_value(record, self._subject_field(doc['appId'])),
                'project': doc['project'],
            }, connection=db)
        else:
            self.app(user, doc['appId'])
        return doc

    def save_file(self, user, app_id, project, purpose, name, data):
        self.projects.require(user, project)
        self.app(user, app_id, 'operate')
        digest = hashlib.sha256(data).hexdigest()
        doc = {'fileId': uuid.uuid4().hex, 'appId': app_id, 'project': project,
               'purpose': purpose, 'name': Path(name).name, 'sha256': digest,
               'size': len(data), 'submitter': user.id, 'createdAt': time.time()}
        with self.store._lock, self.store._db:
            # 只在首次写入创建原件，同内容后续登记独立文件号。
            blob = self.blobs / digest
            if not blob.exists():
                with blob.open('xb') as f:
                    f.write(data)
            self.store._db.execute('insert into v1_files values (?,?,?,?)',
                                   (doc['fileId'], app_id, project, json.dumps(doc, ensure_ascii=False)))
            self.store.audit(app_id, user.id, 'v1.file.create', {'fileId': doc['fileId'], 'sha256': digest}, connection=self.store._db)
        return doc

    def get_file(self, user, fid):
        with self.store._lock, self.store._db:
            db = self.store._db
            doc = self._file(db, user, fid)
            uses = db.execute('select r.app,u.record_id,u.version from v1_file_uses u join v1_records r on r.id=u.record_id where u.file_id=? order by u.rowid', (fid,)).fetchall()
            doc['references'] = []
            for app, rid, v in uses:
                try:
                    self._record(db, user, app, rid, v, allow_cross=True, audit_cross=False)
                except AppUnavailable:
                    continue
                except DataError as e:
                    if e.code != 'not_found':
                        raise
                    continue
                doc['references'].append({'appId': app, 'recordId': rid, 'version': v})
            return doc

    def read_file(self, user, fid):
        with self.store._lock, self.store._db:
            doc = self._file(self.store._db, user, fid)
            return (self.blobs / doc['sha256']).read_bytes()

    def list_cross_records(self, user, app_id, subject, *, project=None, status=None, type=None):
        if not isinstance(subject, str) or not subject:
            raise DataError('invalid_request', '主体值不能为空')
        subject_field = self._subject_field(app_id)
        if subject_field is None:
            raise DataError('not_found', '应用未声明跨项目主体字段')
        self.app(user, app_id)
        if project is not None:
            self.projects.require(user, project)
        with self.store._lock, self.store._db:
            db = self.store._db
            rows = db.execute(
                'select r.id from v1_records r join cross_project_subjects s on s.record_id=r.id and s.version=r.latest '
                'where r.app=? and s.subject_field=? and s.subject_value=? order by r.rowid desc',
                (app_id, subject_field, subject),
            ).fetchall()
            items = []
            for (rid,) in rows:
                try:
                    doc = self._record(db, user, app_id, rid, allow_cross=True)
                except DataError as error:
                    if error.code == 'not_found':
                        continue
                    raise
                if all(value is None or doc[key] == value for key, value in [('project', project), ('status', status), ('type', type)]):
                    doc['sourceProject'] = doc['project']
                    items.append(doc)
            return {'items': items, 'subject': subject, 'subjectField': subject_field}

    def get_cross_record(self, user, app_id, rid, version=None):
        with self.store._lock, self.store._db:
            doc = self._record(self.store._db, user, app_id, rid, version, allow_cross=True)
            field = self._subject_field(app_id)
            if field is None or self._subject_value(doc, field) is None:
                raise DataError('not_found', '记录没有可跨项目读取的主体')
            doc['sourceProject'] = doc['project']
            return doc

    def read_cross_file(self, user, app_id, fid):
        with self.store._lock, self.store._db:
            raw = one(self.store._db, 'select document from v1_files where id=?', (fid,))
            if not raw or json.loads(raw[0])['appId'] != app_id:
                raise DataError('not_found', '文件不存在')
            doc = self._file(self.store._db, user, fid)
            return (self.blobs / doc['sha256']).read_bytes()

    def list_cross_grants(self):
        with self.store._lock:
            rows = self.store._db.execute(
                'select id,app_id,subject_field,subject_value,principal_type,principal_id,created_by,created_at,revoked_by,revoked_at '
                'from cross_project_grants order by created_at desc').fetchall()
            apps = [{'id': app_id, 'name': entry.manifest['name'], 'subjectField': self._subject_field(app_id)}
                    for app_id, entry in self.apps.items() if self._subject_field(app_id)]
        keys = ('id','appId','subjectField','subjectValue','principalType','principalId','createdBy','createdAt','revokedBy','revokedAt')
        return {'grants': [dict(zip(keys, row)) for row in rows], 'apps': apps}

    def create_cross_grant(self, user, body):
        app_id = body.get('appId'); field = body.get('subjectField'); value = body.get('subjectValue')
        principal_type = body.get('principalType'); principal_id = body.get('principalId')
        if app_id not in self.apps or self._subject_field(app_id) != field:
            raise DataError('invalid_request', '应用未声明该主体字段')
        if principal_type not in ('user', 'role') or not isinstance(principal_id, str) or not principal_id:
            raise DataError('invalid_request', '授权对象无效')
        with self.store._lock, self.store._db:
            db = self.store._db
            table = 'users' if principal_type == 'user' else 'roles'
            if not db.execute(f'select 1 from {table} where id=?', (principal_id,)).fetchone():
                raise DataError('invalid_request', '授权对象不存在')
            existing = db.execute('select id from cross_project_grants where app_id=? and subject_field=? and subject_value is ? and principal_type=? and principal_id=? and revoked_at is null',
                                  (app_id, field, value, principal_type, principal_id)).fetchone()
            if existing:
                return {'id': existing[0], 'replayed': True}
            grant_id = uuid.uuid4().hex
            now = time.time()
            db.execute('insert into cross_project_grants values (?,?,?,?,?,?,?,?,?,?)',
                       (grant_id, app_id, field, value, principal_type, principal_id, user.id, now, None, None))
            self.store.audit('platform', user.id, 'cross_project.grant.create', {
                'grantId': grant_id, 'appId': app_id, 'subjectField': field,
                'subjectValue': value, 'principalType': principal_type, 'principalId': principal_id,
            }, connection=db)
            return {'id': grant_id, 'appId': app_id, 'subjectField': field, 'subjectValue': value,
                    'principalType': principal_type, 'principalId': principal_id, 'createdBy': user.id, 'createdAt': now,
                    'revokedBy': None, 'revokedAt': None}

    def revoke_cross_grant(self, user, grant_id):
        with self.store._lock, self.store._db:
            db = self.store._db
            row = db.execute('select id,app_id,subject_field,subject_value,principal_type,principal_id,revoked_at from cross_project_grants where id=?', (grant_id,)).fetchone()
            if not row:
                raise DataError('not_found', '授权不存在')
            if row[-1] is not None:
                return {'ok': True, 'revoked': False}
            now = time.time()
            db.execute('update cross_project_grants set revoked_by=?,revoked_at=? where id=?', (user.id, now, grant_id))
            self.store.audit('platform', user.id, 'cross_project.grant.revoke', {
                'grantId': grant_id, 'appId': row[1], 'subjectField': row[2], 'subjectValue': row[3],
                'principalType': row[4], 'principalId': row[5],
            }, connection=db)
            return {'ok': True, 'revoked': True}

    def _validate_links(self, db, user, app_id, body):
        referenced_files = set()
        for ref in body['refs']:
            source = self._record(db, user, ref['appId'], ref['recordId'], ref['version'])
            if source['status'] != 'confirmed':
                raise DataError('invalid_reference', '只能引用已确认的版本')
            fid = ref['fileId']
            if fid is not None:
                if not one(db, 'select 1 from v1_file_uses where file_id=? and record_id=? and version=?',
                           (fid, source['id'], source['version'])):
                    raise DataError('invalid_reference', '文件未登记在被引用版本上')
                self._file(db, user, fid)
                referenced_files.add(fid)
        for fid in set(body['files']):
            f = self._file(db, user, fid)
            if fid not in referenced_files and (f['project'] != body['project'] or f['appId'] != app_id):
                raise DataError('invalid_reference', '文件须属于本项目和应用，跨应用请引用已确认版本')

    def save_record(self, user, app_id, body, rid=None):
        with self.store._lock, self.store._db:
            self.store.begin_write()
            db = self.store._db
            if rid is None:
                body = parse(RecordBody, body)
                version = 1
            else:
                old = self._record(db, user, app_id, rid)
                self.app(user, app_id, 'operate')
                base = parse(Revision, body)['baseVersion']
                if base != old['version']:
                    raise DataError('version_conflict', '记录已有新版本，请重新读取后保存', currentVersion=old['version'])
                body = parse(RecordBody, {**old, **body})
                version = old['version'] + 1
            project = self.projects.require(user, body['project'])
            self.app(user, app_id, 'operate')
            if body['product'] is not None and body['product'] not in {p['id'] for p in project['products']}:
                raise DataError('invalid_request', '产品不属于此项目')
            self._validate_links(db, user, app_id, body)
            rid = rid or uuid.uuid4().hex
            document = {**body, 'id': rid, 'appId': app_id, 'company': project['company'],
                        'version': version, 'submitter': user.id, 'createdAt': time.time()}
            if version == 1:
                db.execute('insert into v1_records values (?,?,?)', (rid, app_id, version))
            else:
                db.execute('update v1_records set latest=? where id=?', (version, rid))
            db.execute('insert into v1_versions values (?,?,?)', (rid, version, json.dumps(document, ensure_ascii=False)))
            db.execute('insert into v1_states values (?,?,?)', (rid, version, 'draft'))
            subject_field = self._subject_field(app_id)
            subject_value = self._subject_value(document, subject_field) if subject_field else None
            if subject_field and subject_value is not None:
                db.execute('insert into cross_project_subjects values (?,?,?,?,?)',
                           (app_id, rid, version, subject_field, subject_value))
            files = set(body['files'])
            for ref in body['refs']:
                db.execute('insert into v1_refs values (?,?,?,?,?,?)',
                           (rid, version, ref['appId'], ref['recordId'], ref['version'], ref['fileId']))
                if ref['fileId']:
                    files.add(ref['fileId'])
            for fid in files:
                db.execute('insert into v1_file_uses values (?,?,?)', (fid, rid, version))
            if version > 1:
                self._invalidate(db, document)
                self._supersede_reviews(db, rid)
            self.store.audit(app_id, user.id, 'v1.record.save', {'recordId': rid, 'version': version}, connection=db)
            return self._record(db, user, app_id, rid, version)

    def _write_review(self, db, review):
        db.execute('update v1_reviews set document=? where id=?', (json.dumps(review, ensure_ascii=False), review['id']))

    def _supersede_reviews(self, db, rid):
        for (raw,) in db.execute('select document from v1_reviews where record_id=?', (rid,)).fetchall():
            review = json.loads(raw)
            if review['status'] == 'pending':
                review['status'] = 'recheck'
                db.execute("update v1_states set status='recheck' where record_id=? and version=?",
                           (rid, review['version']))
                self._write_review(db, review)

    def _invalidate(self, db, source):
        targets = db.execute(
            'select distinct x.record_id,x.version,x.source_version from v1_refs x '
            'join v1_records r on r.id=x.record_id and r.latest=x.version '
            'where x.source_id=? and x.source_version<?', (source['id'], source['version'])
        ).fetchall()
        for rid, version, old in targets:
            target = json.loads(one(db, 'select document from v1_versions where record_id=? and version=?', (rid, version))[0])
            db.execute("update v1_states set status='recheck' where record_id=? and version=?", (rid, version))
            self._supersede_reviews(db, rid)
            note = {'id': uuid.uuid4().hex, 'appId': target['appId'], 'recordId': rid,
                    'version': version, 'recipient': target['submitter'], 'project': target['project'],
                    'source': {'appId': source['appId'], 'recordId': source['id'],
                               'version': old, 'currentVersion': source['version']},
                    'message': '引用的源记录已有新版本，请重新核对', 'createdAt': time.time()}
            db.execute('insert into v1_notifications values (?,?,?,?,?)',
                       (note['id'], target['appId'], target['submitter'], target['project'], json.dumps(note, ensure_ascii=False)))
            self.store.audit(target['appId'], source['submitter'], 'v1.reference.invalidate',
                             {'recordId': rid, 'version': version, 'sourceId': source['id'], 'notificationId': note['id']}, connection=db)

    def _assignee(self, record, assignee, submitter):
        other = self.rbac.users.get(assignee)
        if other is None or not self.projects.visible(other, record['project']) or 'view' not in self.rbac.actions(other, record['appId']):
            raise DataError('not_found', '确认人不存在或不在项目范围内')
        if assignee in (record['submitter'], submitter):
            raise DataError('self_review', '提交人不能确认自己的记录')
        self.app(other, record['appId'], 'approve')

    def _require_platform_review(self, app_id):
        if self.apps[app_id].manifest.get('review') == 'app':
            raise DataError('invalid_state', '此应用自管审核，请在应用内处理',
                            appId=app_id, appUrl=f'#/app/{app_id}')

    def _require_sources(self, db, user, app_id, requirements):
        """在决定事务内核对来源最新版本与状态；任一不满足即整体拒绝。"""
        for item in requirements or ():
            source_app = item['appId'] or app_id
            # _record 走与 ctx.records.get 相同的项目范围和应用可见性检查，越权按不存在处理。
            source = self._record(db, user, source_app, item['recordId'])
            if source['version'] != item['version']:
                raise DataError('stale_version', '来源记录已有新版本，请重新核对',
                                appId=source_app, recordId=item['recordId'],
                                currentVersion=source['version'])
            if item['status'] is not None and source['status'] != item['status']:
                raise DataError('invalid_state', '来源记录状态已变化，请重新核对',
                                appId=source_app, recordId=item['recordId'],
                                status=source['status'])

    def submit_review(self, user, body, *, generic_http=False):
        body = parse(ReviewBody, body)
        with self.store._lock, self.store._db:
            self.store.begin_write()
            db = self.store._db
            record = self._record(db, user, body['appId'], body['recordId'])
            self.app(user, body['appId'], 'operate')
            if generic_http:
                self._require_platform_review(body['appId'])
            if body['version'] != record['version']:
                raise DataError('stale_version', '只能提交当前最新版本', currentVersion=record['version'])
            if record['status'] not in ('draft', 'needs_info'):
                raise DataError('invalid_state', '只有草稿或待补充记录可以提交确认')
            if body['assignee'] is not None:
                self._assignee(record, body['assignee'], user.id)
            review = {**body, 'id': uuid.uuid4().hex, 'submitter': user.id,
                      'status': 'pending', 'createdAt': time.time()}
            db.execute('insert into v1_reviews values (?,?,?,?)',
                       (review['id'], record['id'], record['version'], json.dumps(review, ensure_ascii=False)))
            db.execute("update v1_states set status='pending' where record_id=? and version=?", (record['id'], record['version']))
            self.store.audit(body['appId'], user.id, 'v1.review.submit', review, connection=db)
            return review

    def decide_review(self, user, review_id, body, *, app_id=None, generic_http=False):
        body = parse(DecisionBody, body)
        requirements = body.pop('require')
        with self.store._lock, self.store._db:
            self.store.begin_write()
            db = self.store._db
            raw = one(db, 'select document from v1_reviews where id=?', (review_id,))
            if not raw:
                raise DataError('not_found', '确认待办不存在')
            review = json.loads(raw[0])
            if app_id is not None and review['appId'] != app_id:
                raise DataError('not_found', '确认待办不存在')
            record = self._record(db, user, review['appId'], review['recordId'])
            # 历史版本也检查范围，避免记录改到别的项目后泄露旧待办。
            target = self._record(db, user, review['appId'], review['recordId'], review['version'])
            self.app(user, review['appId'], 'approve')
            if generic_http:
                self._require_platform_review(review['appId'])
            if user.id in (target['submitter'], review['submitter']):
                raise DataError('self_review', '提交人不能确认自己的记录')
            if body['version'] != review['version'] or review['version'] != record['version']:
                raise DataError('stale_version', '记录已有新版本，不能确认旧版本', currentVersion=record['version'])
            if review['status'] != 'pending' or record['status'] != 'pending':
                raise DataError('invalid_state', '此待办已处理或需重新核对')
            if review['assignee'] is not None and review['assignee'] != user.id:
                raise DataError('forbidden', '此待办已指定其他确认人')
            # 来源核对与下面的决定、状态、审计在同一事务内提交。
            self._require_sources(db, user, review['appId'], requirements)
            if body['decision'] == 'reassign':
                if body['assignee'] is None:
                    raise DataError('invalid_request', '换人时必须指定确认人')
                self._assignee(target, body['assignee'], review['submitter'])
                review['assignee'] = body['assignee']
            else:
                review['status'] = 'confirmed' if body['decision'] == 'confirm' else 'needs_info'
                db.execute('update v1_states set status=? where record_id=? and version=?',
                           (review['status'], record['id'], record['version']))
            decision = {**body, 'id': uuid.uuid4().hex, 'reviewId': review_id,
                        'actor': user.id, 'createdAt': time.time()}
            db.execute('insert into v1_decisions values (?,?,?)', (decision['id'], review_id, json.dumps(decision, ensure_ascii=False)))
            self._write_review(db, review)
            self.store.audit(review['appId'], user.id, 'v1.review.' + body['decision'], decision, connection=db)
            return {**review, 'decision': decision}

    def list_reviews(self, user, *, assignee=None, mine=None, app_id=None):
        if assignee not in (None, 'me') or mine not in (None, 'submitted'):
            raise DataError('invalid_request', '待办筛选只支持 assignee=me 或 mine=submitted')
        if app_id is not None:
            self.app(user, app_id)
        with self.store._lock:
            db = self.store._db
            items = []
            for (raw,) in db.execute('select document from v1_reviews order by rowid desc').fetchall():
                review = json.loads(raw)
                if app_id is not None and review['appId'] != app_id:
                    continue
                try:
                    record = self._record(db, user, review['appId'], review['recordId'], review['version'])
                except AppUnavailable:
                    continue
                except DataError as e:
                    if e.code != 'not_found':
                        raise
                    continue
                if mine == 'submitted':
                    if review['submitter'] != user.id:
                        continue
                else:
                    if (review['status'] != 'pending' or 'approve' not in self.rbac.actions(user, review['appId'])
                            or user.id in (record['submitter'], review['submitter'])
                            or review['assignee'] not in (None, user.id)):
                        continue
                decisions = [json.loads(r[0]) for r in db.execute('select document from v1_decisions where review_id=? order by rowid', (review['id'],))]
                items.append({**review, 'decisions': decisions, 'project': record['project'],
                              'review': self.apps[review['appId']].manifest.get('review', 'platform')})
            return {'items': items}

    def list_members(self, user, app_id, project, action='approve'):
        """返回项目内对当前应用具备指定动作的在用成员。"""
        if action not in ('view', 'operate', 'approve', 'admin'):
            raise DataError('invalid_request', '成员动作无效')
        self.projects.require(user, project)
        self.app(user, app_id)
        members = []
        for member in self.rbac.users.values():
            if not self.projects.visible(member, project):
                continue
            actions = self.rbac.actions(member, app_id)
            if 'view' not in actions or action not in actions:
                continue
            members.append({'id': member.id, 'name': member.name})
        members.sort(key=lambda item: (item['name'], item['id']))
        return {'items': members}

    def find_artifacts(self, user, *, project=None, product=None, type=None, app=None, history=False, recordId=None, version=None):
        if project is not None:
            self.projects.require(user, project)
        if app is not None:
            self.app(user, app)
        with self.store._lock:
            db = self.store._db
            items, seen = [], set()
            rows = db.execute('select d.document,r.document from v1_decisions d join v1_reviews r on r.id=d.review_id order by d.rowid desc').fetchall()
            for decision_raw, review_raw in rows:
                decision, review = json.loads(decision_raw), json.loads(review_raw)
                if decision['decision'] != 'confirm':
                    continue
                try:
                    doc = self._record(db, user, review['appId'], review['recordId'], review['version'])
                except AppUnavailable:
                    continue
                except DataError as e:
                    if e.code != 'not_found':
                        raise
                    continue
                if doc['status'] != 'confirmed':
                    continue
                if not all(value is None or actual == value for actual, value in [
                    (doc['project'], project), (doc['product'], product), (doc['type'], type),
                    (doc['appId'], app), (doc['id'], recordId), (doc['version'], version)]):
                    continue
                files = []
                for (fid,) in db.execute(
                    'select file_id from v1_file_uses where record_id=? and version=? order by file_id',
                    (doc['id'], doc['version'])
                ).fetchall():
                    try:
                        files.append(self._file(db, user, fid))
                    except AppUnavailable:
                        continue
                    except DataError as e:
                        if e.code != 'not_found':
                            raise
                # 按版本选择最新已确认版，而非按确认动作的时间选择。
                items.append({**doc, 'recordId': doc['id'], 'confirmedBy': decision['actor'],
                              'confirmedAt': decision['createdAt'], 'files': files})
            result = []
            for doc in sorted(items, key=lambda r: r['version'], reverse=True):
                key = (doc['id'], doc['version']) if history or version is not None else doc['id']
                if key not in seen:
                    seen.add(key)
                    result.append(doc)
            return {'items': result}

    def list_notifications(self, user, *, app=None):
        if app is not None:
            self.app(user, app)
        with self.store._lock:
            db = self.store._db
            items = []
            for nid, target_app, recipient, project, raw in db.execute('select * from v1_notifications order by rowid desc').fetchall():
                if (app is None and recipient != user.id) or (app is not None and app != target_app):
                    continue
                if not self.projects.visible(user, project) or 'view' not in self.rbac.actions(user, target_app):
                    continue
                if target_app not in self.apps or self.apps[target_app].unavailable_reason():
                    continue
                note = json.loads(raw)
                note['read'] = bool(one(db, 'select 1 from v1_notification_reads where notification_id=? and user_id=?', (nid, user.id)))
                items.append(note)
            return {'items': items}

    def read_notification(self, user, nid, *, app=None):
        with self.store._lock, self.store._db:
            db = self.store._db
            raw = one(db, 'select document from v1_notifications where id=?', (nid,))
            if not raw:
                raise DataError('not_found', '通知不存在')
            note = json.loads(raw[0])
            if app is not None and app != note['appId']:
                raise DataError('not_found', '通知不存在')
            self.projects.require(user, note['project'])
            self.app(user, note['appId'])
            db.execute('insert or ignore into v1_notification_reads values (?,?)', (nid, user.id))
            self.store.audit(note['appId'], user.id, 'v1.notification.read', {'notificationId': nid}, connection=db)
            return {**note, 'read': True}

    @staticmethod
    def _message_delivery_item(row):
        mid, _, raw, read_at, acknowledged_at = row
        note = json.loads(raw)
        status = 'acknowledged' if acknowledged_at is not None else 'read' if read_at is not None else 'written'
        return {**note, 'id': mid, 'read': read_at is not None, 'readAt': read_at,
                'acknowledged': acknowledged_at is not None, 'acknowledgedAt': acknowledged_at,
                'status': status}

    def _message_item(self, db, user, row):
        mid, recipient, raw, read_at, acknowledged_at = row
        if recipient != user.id:
            raise DataError('not_found', '消息不存在')
        note = json.loads(raw)
        if note['expiresAt'] is not None and note['expiresAt'] <= time.time():
            raise DataError('not_found', '消息不存在或已失效')
        self._record(db, user, note['source']['appId'], note['source']['recordId'], note['source']['version'])
        return self._message_delivery_item(row)

    def send_message(self, user, app_id, request):
        try:
            message = parse(MessageBody, request)
            if len(set(message['recipientIds'])) != len(message['recipientIds']):
                raise DataError('invalid_request', '收件人不能重复')
            recipients = sorted(message['recipientIds'])
            normalized = {**message, 'recipientIds': recipients, 'source': {
                'appId': app_id, 'recordId': message['recordId'], 'version': message['version']}}
            request_json = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            with self.store._lock, self.store._db:
                db = self.store._db
                self.app(user, app_id, 'operate')
                existing = db.execute(
                    'select id,recipient,document,read_at,acknowledged_at,request from v1_messages '
                    'where app=? and sender=? and idempotency_key=? order by rowid',
                    (app_id, user.id, message['idempotencyKey'])
                ).fetchall()
                if existing:
                    if any(row[5] != request_json for row in existing):
                        raise DataError('invalid_state', '幂等键已用于不同的消息请求')
                    sent = json.loads(existing[0][2])
                    self._record(db, user, sent['source']['appId'], sent['source']['recordId'],
                                 sent['source']['version'])
                    self.store.audit(app_id, user.id, 'v1.message.deduplicate',
                                     {'idempotencyKey': message['idempotencyKey']}, connection=db)
                    return {'items': [self._message_delivery_item(row[:5]) for row in existing],
                            'replayed': True}
                if message['expiresAt'] is not None and message['expiresAt'] <= time.time():
                    raise DataError('invalid_request', '失效时间必须晚于当前时间')
                source = self._record(db, user, app_id, message['recordId'], message['version'])
                active_users = self.rbac.users
                failures = []
                authorized = []
                for recipient_id in recipients:
                    recipient = active_users.get(recipient_id)
                    if recipient is None:
                        failures.append({'recipientId': recipient_id, 'reason': '收件人不存在或已停用'})
                        continue
                    try:
                        self._record(db, recipient, app_id, message['recordId'], message['version'])
                    except (DataError, AppUnavailable):
                        failures.append({'recipientId': recipient_id, 'reason': '来源记录不可见'})
                    else:
                        authorized.append(recipient)
                if failures:
                    raise DataError('invalid_request', '消息未发送：请检查收件人与来源权限', recipients=failures)
                created_at = time.time()
                items = []
                for recipient in authorized:
                    mid = uuid.uuid4().hex
                    note = {'appId': app_id, 'senderId': user.id, 'recipientId': recipient.id,
                            'title': message['title'], 'body': message['body'],
                            'source': normalized['source'], 'project': source['project'],
                            'priority': message['priority'], 'createdAt': created_at,
                            'expiresAt': message['expiresAt'],
                            'requiresAcknowledgement': message['requiresAcknowledgement']}
                    db.execute(
                        'insert into v1_messages(id,app,sender,recipient,idempotency_key,request,document,read_at,acknowledged_at) '
                        'values (?,?,?,?,?,?,?,null,null)',
                        (mid, app_id, user.id, recipient.id, message['idempotencyKey'], request_json,
                         json.dumps(note, ensure_ascii=False, separators=(',', ':')))
                    )
                    self.store.audit(app_id, user.id, 'v1.message.write',
                                     {'messageId': mid, 'recipientId': recipient.id}, connection=db)
                    items.append({**note, 'id': mid, 'read': False, 'readAt': None,
                                  'acknowledged': False, 'acknowledgedAt': None, 'status': 'written'})
                return {'items': items, 'replayed': False}
        except DataError as error:
            self.store.audit(app_id, user.id, 'v1.message.send_failed', {'code': error.code})
            raise

    def list_messages(self, user):
        with self.store._lock:
            db = self.store._db
            items = []
            rows = db.execute(
                'select id,recipient,document,read_at,acknowledged_at from v1_messages '
                'where recipient=? order by rowid desc', (user.id,)
            ).fetchall()
            for row in rows:
                try:
                    items.append(self._message_item(db, user, row))
                except (DataError, AppUnavailable):
                    continue
            return {'items': items}

    def get_message(self, user, message_id):
        with self.store._lock:
            row = one(self.store._db,
                      'select id,recipient,document,read_at,acknowledged_at from v1_messages where id=?',
                      (message_id,))
            if not row:
                raise DataError('not_found', '消息不存在')
            return self._message_item(self.store._db, user, row)

    def read_message(self, user, message_id):
        with self.store._lock, self.store._db:
            db = self.store._db
            row = one(db, 'select id,recipient,document,read_at,acknowledged_at from v1_messages where id=?',
                      (message_id,))
            if not row:
                raise DataError('not_found', '消息不存在')
            item = self._message_item(db, user, row)
            if row[3] is None:
                read_at = time.time()
                db.execute('update v1_messages set read_at=? where id=?', (read_at, message_id))
                self.store.audit(item['appId'], user.id, 'v1.message.read', {'messageId': message_id}, connection=db)
                item.update(read=True, readAt=read_at, status='read')
            return item

    def acknowledge_message(self, user, message_id):
        with self.store._lock, self.store._db:
            db = self.store._db
            row = one(db, 'select id,recipient,document,read_at,acknowledged_at from v1_messages where id=?',
                      (message_id,))
            if not row:
                raise DataError('not_found', '消息不存在')
            item = self._message_item(db, user, row)
            if not item['requiresAcknowledgement']:
                raise DataError('invalid_state', '此消息不需要知悉确认')
            if row[4] is None:
                now = time.time()
                db.execute('update v1_messages set read_at=coalesce(read_at,?),acknowledged_at=? where id=?',
                           (now, now, message_id))
                self.store.audit(item['appId'], user.id, 'v1.message.acknowledge',
                                 {'messageId': message_id}, connection=db)
                item.update(read=True, readAt=row[3] or now, acknowledged=True,
                            acknowledgedAt=now, status='acknowledged')
            return item

    def list_sent_messages(self, user, app_id):
        self.app(user, app_id)
        with self.store._lock:
            db = self.store._db
            items = []
            rows = db.execute(
                'select id,recipient,document,read_at,acknowledged_at from v1_messages '
                'where app=? and sender=? order by rowid desc', (app_id, user.id)
            ).fetchall()
            for row in rows:
                note = json.loads(row[2])
                if not self.projects.visible(user, note['project']):
                    continue
                items.append(self._message_delivery_item(row))
            return {'items': items}

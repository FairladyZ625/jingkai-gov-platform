"""平台知识库：条目、版本、审核状态、可见范围、引用反查与检索。

数据表（migrations 4）：
  kb_entries  —— 条目主文档 JSON（标题/主分类/标签/来源应用/权限标记/最新与已发布版本号）
  kb_versions —— 版本行（entry_id + version 主键，file_id 可反查 v1 原件与 v1_file_uses）

原件沿用 v1 文件存储：版本只登记 v1 文件 ID，换版追加新文件、不覆盖旧原件。
写操作全部留痕；读操作不加留痕（参见 CAP-04 §5 与任务计划）。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from haiknow_sdk import DataError

from ..stability import AppUnavailable

CATEGORIES = (
    '01-制度标准通知', '02-工程产品图纸', '03-项目商务资料', '04-采购供应商',
    '05-制造质量交付', '06-仓储盘点', '07-人员行政培训', '08-品牌内容客户',
)
# 未审核 / 待核 / 已发布 / 已替代；条目的 status 跟随最新版本。
STATUSES = ('unreviewed', 'pending', 'published', 'superseded')
VISIBILITIES = ('public', 'internal', 'restricted')
MAX_TEXT = 20000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class EntryBody(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=20)
    sourceApp: str = Field(min_length=1, max_length=100)
    project: str | None = Field(default=None, max_length=100)
    scope: Literal['project', 'company'] = 'project'
    visibility: Literal['public', 'internal', 'restricted'] = 'internal'
    roles: list[str] = Field(default_factory=list, max_length=100)
    departments: list[str] = Field(default_factory=list, max_length=100)
    purpose: str = Field(default='knowledge', max_length=100)
    note: str = Field(default='', max_length=500)
    text: str = Field(default='', max_length=MAX_TEXT)


class VersionBody(StrictModel):
    project: str | None = Field(default=None, max_length=100)
    purpose: str = Field(default='knowledge', max_length=100)
    note: str = Field(default='', max_length=500)
    text: str = Field(default='', max_length=MAX_TEXT)


class UpdateBody(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=40)
    tags: list[str] | None = Field(default=None, max_length=20)
    scope: Literal['project', 'company'] | None = None
    visibility: Literal['public', 'internal', 'restricted'] | None = None
    roles: list[str] | None = Field(default=None, max_length=100)
    departments: list[str] | None = Field(default=None, max_length=100)


class StatusBody(StrictModel):
    version: int = Field(strict=True, gt=0)


class SearchBody(StrictModel):
    q: str | None = Field(default=None, max_length=200)
    category: str | None = None
    status: str | None = None
    app: str | None = Field(default=None, max_length=100)
    updatedAfter: float | None = None
    updatedBefore: float | None = None
    includeUnpublished: StrictBool = False
    limit: int = Field(default=50, strict=True, ge=1, le=200)
    offset: int = Field(default=0, strict=True, ge=0, le=100000)


def parse(model, body):
    try:
        return model.model_validate(body).model_dump()
    except ValidationError as exc:
        raise DataError('invalid_request', '请求字段缺失或类型不正确') from exc


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def clean_names(values, field):
    names = []
    for value in values or []:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 40:
            raise DataError('invalid_request', f'{field} 每项须为 1–40 字')
        if value.strip() not in names:
            names.append(value.strip())
    return names


class Knowledge:
    def __init__(self, data):
        self.data = data
        self.store = data.store
        # 部门可见性由线 A 合入后注入：plat.directory.departments_of(user.id)；
        # 没有该能力时受限条目只按角色判断（任务计划要求的最小回退）。
        self.directory = None

    # ---------- 读取与校验 ----------

    def _entry(self, db, entry_id):
        row = db.execute('select document from kb_entries where id=?', (entry_id,)).fetchone()
        if not row:
            raise DataError('not_found', '知识库条目不存在')
        return json.loads(row[0])

    def _version(self, db, entry_id, version):
        row = db.execute('select document from kb_versions where entry_id=? and version=?',
                         (entry_id, version)).fetchone()
        if not row:
            raise DataError('not_found', '条目版本不存在')
        return json.loads(row[0])

    def _versions(self, db, entry_id):
        return [json.loads(row[0]) for row in db.execute(
            'select document from kb_versions where entry_id=? order by version', (entry_id,))]

    def _meta(self, body):
        category = body['category']
        if category not in CATEGORIES:
            raise DataError('invalid_request', '主分类必须是八个固定分类之一')
        tags = clean_names(body['tags'], '标签')
        roles = clean_names(body['roles'], '可见角色')
        departments = clean_names(body['departments'], '可见部门')
        if body['visibility'] == 'restricted' and not (roles or departments):
            raise DataError('invalid_request', '受限条目必须指定可见角色或部门')
        return {**body, 'tags': tags, 'roles': roles, 'departments': departments}

    def _manage(self, user, entry):
        for app_id in (entry['sourceApp'], 'knowledge-base'):
            if 'operate' in self.data.rbac.actions(user, app_id) or 'approve' in self.data.rbac.actions(user, app_id):
                return True
        return False

    def _approve(self, user, entry):
        for app_id in (entry['sourceApp'], 'knowledge-base'):
            if 'approve' in self.data.rbac.actions(user, app_id):
                return
        raise DataError('forbidden', '没有发布知识库条目的权限', action='approve')

    def _can_share_company(self, user, app_id):
        return 'admin' in self.data.rbac.actions(user, '*') or any(
            'approve' in self.data.rbac.actions(user, candidate)
            for candidate in (app_id, 'knowledge-base'))

    def _require_project(self, user, entry):
        project = entry.get('project')
        if project and 'admin' not in self.data.rbac.actions(user, '*') \
                and not self.data.projects.visible(user, project):
            raise DataError('not_found', '项目或资源不存在')

    def allowed(self, user, entry) -> bool:
        """先验证项目范围，再验证条目的公开/应用/角色/部门可见性。"""
        if 'admin' in self.data.rbac.actions(user, '*'):
            return True
        project = entry.get('project')
        if project and entry.get('scope', 'project') != 'company' \
                and not self.data.projects.visible(user, project):
            return False
        if user.id == entry['uploader']:
            return True
        if entry['visibility'] == 'public':
            return True
        if entry['visibility'] == 'internal':
            return 'view' in self.data.rbac.actions(user, entry['sourceApp'])
        if set(entry['roles']) & set(user.roles):
            return True
        if not entry['departments']:
            return False
        directory = self.directory
        if directory is None or not hasattr(directory, 'departments_of'):
            return False
        return bool(set(directory.departments_of(user.id)) & set(entry['departments']))

    def _require_view(self, user, entry):
        if not self.allowed(user, entry):
            raise DataError('forbidden', '没有查看此知识库条目的权限', entryId=entry['id'])

    def _require_readable(self, user, entry, version):
        """未审核/待核版本只有维护/审核人可读，已发布与被替代版本按条目可见范围可读。"""
        self._require_view(user, entry)
        if version['status'] not in ('published', 'superseded') and not self._manage(user, entry):
            raise DataError('forbidden', '此版本尚未发布，不能作为依据读取', version=version['version'])

    @staticmethod
    def _summary(version):
        return {key: version[key] for key in (
            'version', 'fileId', 'sha256', 'size', 'name', 'note', 'uploader', 'status', 'createdAt')}

    def _view(self, db, entry):
        versions = self._versions(db, entry['id'])
        latest = versions[-1]
        effective = next((v for v in versions if v['status'] == 'published'), None)
        return {
            **{key: entry[key] for key in (
                'id', 'title', 'category', 'tags', 'sourceApp', 'uploader', 'status', 'visibility',
                'roles', 'departments', 'synthetic', 'createdAt', 'updatedAt')},
            'project': entry.get('project'),
            'scope': entry.get('scope', 'project'),
            'latestVersion': latest['version'],
            'publishedVersion': effective['version'] if effective else None,
            'latest': self._summary(latest),
            'effective': self._summary(effective) if effective else None,
        }

    # ---------- 写入 ----------

    def _write_entry(self, user, body, *, upload, file_id):
        body = self._meta(parse(EntryBody, body))
        app_id = body['sourceApp']
        self.data.app(user, app_id, 'operate')
        if body['scope'] == 'company' and not self._can_share_company(user, app_id):
            raise DataError('forbidden', '只有管理员或发布权限人员可以声明公司共享', action='approve')
        if (upload is None) == (file_id is None):
            raise DataError('invalid_request', '上传原件或登记已上传文件必须二选一')
        if upload is not None:
            if not body.get('project'):
                raise DataError('invalid_request', '上传原件必须指定项目')
            file_doc = self.data.save_file(user, app_id, body['project'], body['purpose'], upload[0], upload[1])
        else:
            with self.store._lock:
                file_doc = self.data._file(self.store._db, user, file_id)
            if file_doc['appId'] != app_id:
                raise DataError('invalid_request', '只能登记本应用上传的原件')
        now = time.time()
        entry_id = uuid.uuid4().hex
        entry = {
            'id': entry_id, 'title': body['title'], 'category': body['category'], 'tags': body['tags'],
            'sourceApp': app_id, 'project': file_doc['project'], 'uploader': user.id,
            'scope': body['scope'],
            'status': 'unreviewed', 'visibility': body['visibility'], 'roles': body['roles'],
            'departments': body['departments'], 'synthetic': False,
            'latestVersion': 1, 'publishedVersion': None, 'createdAt': now, 'updatedAt': now,
        }
        version = {
            'entryId': entry_id, 'version': 1, 'fileId': file_doc['fileId'], 'sha256': file_doc['sha256'],
            'size': file_doc['size'], 'name': file_doc['name'], 'uploader': user.id, 'note': body['note'],
            'text': body['text'], 'status': 'unreviewed', 'createdAt': now,
        }
        with self.store._lock, self.store._db:
            db = self.store._db
            db.execute('insert into kb_entries values (?,?)', (entry_id, encode(entry)))
            db.execute('insert into kb_versions values (?,?,?,?)', (entry_id, 1, file_doc['fileId'], encode(version)))
            self.store.audit(app_id, user.id, 'knowledge.entry.create',
                             {'entryId': entry_id, 'version': 1, 'fileId': file_doc['fileId'],
                              'scope': body['scope']}, connection=db)
        return self.get(user, entry_id)

    def create_entry(self, user, body, *, upload=None, file_id=None):
        return self._write_entry(user, body, upload=upload, file_id=file_id)

    def add_version(self, user, entry_id, body, *, upload=None, file_id=None):
        body = parse(VersionBody, body)
        with self.store._lock:
            entry = self._entry(self.store._db, entry_id)
        self._require_project(user, entry)
        self.data.app(user, entry['sourceApp'], 'operate')
        if (upload is None) == (file_id is None):
            raise DataError('invalid_request', '上传原件或登记已上传文件必须二选一')
        if upload is not None:
            project = body['project'] or entry['project']
            if project != entry.get('project'):
                raise DataError('invalid_reference', '版本原件必须属于条目的项目范围')
            file_doc = self.data.save_file(user, entry['sourceApp'], project, body['purpose'], upload[0], upload[1])
        else:
            with self.store._lock:
                file_doc = self.data._file(self.store._db, user, file_id)
            if file_doc['appId'] != entry['sourceApp']:
                raise DataError('invalid_request', '只能登记本应用上传的原件')
        if file_doc['project'] != entry.get('project'):
            raise DataError('invalid_reference', '版本原件必须属于条目的项目范围')
        with self.store._lock, self.store._db:
            db = self.store._db
            entry = self._entry(db, entry_id)
            number = entry['latestVersion'] + 1
            now = time.time()
            version = {
                'entryId': entry_id, 'version': number, 'fileId': file_doc['fileId'],
                'sha256': file_doc['sha256'], 'size': file_doc['size'], 'name': file_doc['name'],
                'uploader': user.id, 'note': body['note'], 'text': body['text'],
                'status': 'unreviewed', 'createdAt': now,
            }
            entry.update(latestVersion=number, status='unreviewed', updatedAt=now)
            db.execute('update kb_entries set document=? where id=?', (encode(entry), entry_id))
            db.execute('insert into kb_versions values (?,?,?,?)', (entry_id, number, file_doc['fileId'], encode(version)))
            self.store.audit(entry['sourceApp'], user.id, 'knowledge.entry.version',
                             {'entryId': entry_id, 'version': number, 'fileId': file_doc['fileId']}, connection=db)
        return self.get(user, entry_id)

    def submit(self, user, entry_id, body):
        version_no = parse(StatusBody, body)['version']
        with self.store._lock, self.store._db:
            db = self.store._db
            entry = self._entry(db, entry_id)
            self._require_project(user, entry)
            self.data.app(user, entry['sourceApp'], 'operate')
            version = self._version(db, entry_id, version_no)
            if version_no != entry['latestVersion']:
                raise DataError('stale_version', '只有最新版本可以提交审核', currentVersion=entry['latestVersion'])
            if version['status'] != 'unreviewed':
                raise DataError('invalid_state', '只有未审核版本可以提交审核')
            version['status'] = 'pending'
            entry.update(status='pending', updatedAt=time.time())
            db.execute('update kb_versions set document=? where entry_id=? and version=?',
                       (encode(version), entry_id, version_no))
            db.execute('update kb_entries set document=? where id=?', (encode(entry), entry_id))
            self.store.audit(entry['sourceApp'], user.id, 'knowledge.entry.submit',
                             {'entryId': entry_id, 'version': version_no}, connection=db)
        return self.get(user, entry_id)

    def publish(self, user, entry_id, body):
        version_no = parse(StatusBody, body)['version']
        with self.store._lock, self.store._db:
            db = self.store._db
            entry = self._entry(db, entry_id)
            self._require_project(user, entry)
            self._approve(user, entry)
            version = self._version(db, entry_id, version_no)
            if version_no != entry['latestVersion']:
                raise DataError('stale_version', '只有最新版本可以发布', currentVersion=entry['latestVersion'])
            if version['status'] not in ('unreviewed', 'pending'):
                raise DataError('invalid_state', '此版本已发布或已替代')
            now = time.time()
            replaced = []
            for other in self._versions(db, entry_id):
                if other['status'] == 'published':
                    other['status'] = 'superseded'
                    replaced.append(other['version'])
                    db.execute('update kb_versions set document=? where entry_id=? and version=?',
                               (encode(other), entry_id, other['version']))
            version['status'] = 'published'
            entry.update(status='published', publishedVersion=version_no, updatedAt=now)
            db.execute('update kb_versions set document=? where entry_id=? and version=?',
                       (encode(version), entry_id, version_no))
            db.execute('update kb_entries set document=? where id=?', (encode(entry), entry_id))
            self.store.audit(entry['sourceApp'], user.id, 'knowledge.entry.publish',
                             {'entryId': entry_id, 'version': version_no, 'replaced': replaced}, connection=db)
        return self.get(user, entry_id)

    def update(self, user, entry_id, body):
        patch = parse(UpdateBody, body)
        patch = {key: value for key, value in patch.items() if value is not None}
        if not patch:
            raise DataError('invalid_request', '没有可更新的字段')
        with self.store._lock, self.store._db:
            db = self.store._db
            entry = self._entry(db, entry_id)
            self._require_project(user, entry)
            self.data.app(user, entry['sourceApp'], 'operate')
            merged = self._meta({**entry, 'scope': entry.get('scope', 'project'), **patch})
            if merged['scope'] != entry.get('scope', 'project') and not self._can_share_company(
                    user, entry['sourceApp']):
                raise DataError('forbidden', '只有管理员或发布权限人员可以更改共享范围', action='approve')
            if merged['visibility'] != entry['visibility'] and not (
                    'approve' in self.data.rbac.actions(user, entry['sourceApp'])
                    or 'approve' in self.data.rbac.actions(user, 'knowledge-base')):
                raise DataError('forbidden', '只有审核人可以更改可见范围', action='approve')
            entry.update({key: merged[key] for key in
                          ('title', 'category', 'tags', 'scope', 'visibility', 'roles', 'departments')})
            entry['updatedAt'] = time.time()
            db.execute('update kb_entries set document=? where id=?', (encode(entry), entry_id))
            self.store.audit(entry['sourceApp'], user.id, 'knowledge.entry.update',
                             {'entryId': entry_id, 'fields': sorted(patch),
                              'scope': entry.get('scope', 'project')}, connection=db)
        return self.get(user, entry_id)

    # ---------- 查询 ----------

    def get(self, user, entry_id):
        with self.store._lock:
            db = self.store._db
            entry = self._entry(db, entry_id)
            self._require_view(user, entry)
            if entry['publishedVersion'] is None and not self._manage(user, entry):
                raise DataError('forbidden', '条目尚未发布', entryId=entry_id)
            view = self._view(db, entry)
            view['versions'] = [self._summary(v) for v in self._versions(db, entry_id)]
            return view

    def get_version(self, user, entry_id, version):
        with self.store._lock:
            db = self.store._db
            entry = self._entry(db, entry_id)
            doc = self._version(db, entry_id, version)
            self._require_readable(user, entry, doc)
            return {**self._summary(doc), 'entryId': entry_id,
                    'effective': doc['status'] == 'published'}

    def search(self, user, body):
        body = parse(SearchBody, body)
        if body['category'] is not None and body['category'] not in CATEGORIES:
            raise DataError('invalid_request', '主分类必须是八个固定分类之一')
        if body['status'] is not None and body['status'] not in ('unreviewed', 'pending', 'published'):
            raise DataError('invalid_request', '状态筛选只支持 unreviewed / pending / published')
        needle = (body['q'] or '').strip().lower()
        with self.store._lock:
            db = self.store._db
            items = []
            for (raw,) in db.execute('select document from kb_entries').fetchall():
                entry = json.loads(raw)
                if not self.allowed(user, entry):
                    continue
                if not body['includeUnpublished'] and entry['publishedVersion'] is None:
                    continue
                if body['status'] is not None and entry['status'] != body['status']:
                    continue
                if body['category'] is not None and entry['category'] != body['category']:
                    continue
                if body['app'] is not None and entry['sourceApp'] != body['app']:
                    continue
                if body['updatedAfter'] is not None and entry['updatedAt'] < body['updatedAfter']:
                    continue
                if body['updatedBefore'] is not None and entry['updatedAt'] > body['updatedBefore']:
                    continue
                view = self._view(db, entry)
                if needle:
                    # 只检索作为依据的版本正文；未发布版本的解析文本不参与检索。
                    effective = entry['publishedVersion'] if entry['publishedVersion'] is not None \
                        else entry['latestVersion']
                    text = self._version(db, entry['id'], effective).get('text', '').lower()
                    haystack = ' '.join([entry['title'].lower(), *entry['tags'], text])
                    if needle not in haystack:
                        continue
                items.append(view)
            items.sort(key=lambda item: item['updatedAt'], reverse=True)
            total = len(items)
            page = items[body['offset']:body['offset'] + body['limit']]
            return {'items': page, 'total': total, 'limit': body['limit'], 'offset': body['offset']}

    def references(self, user, entry_id):
        """反查「哪些记录的哪一版本引用了哪一文件版本」；按调用人权限过滤记录。"""
        with self.store._lock:
            db = self.store._db
            entry = self._entry(db, entry_id)
            self._require_view(user, entry)
            versions = {v['fileId']: v for v in self._versions(db, entry_id)}
            if not versions:
                return {'items': []}
            marks = ','.join('?' for _ in versions)
            rows = db.execute(
                'select file_id,record_id,version from v1_file_uses where file_id in (' + marks + ') order by rowid desc',
                tuple(versions)).fetchall()
            items = []
            for file_id, record_id, version in rows:
                record = db.execute('select app,latest from v1_records where id=?', (record_id,)).fetchone()
                if not record:
                    continue
                try:
                    self.data._record(db, user, record[0], record_id, version)
                except AppUnavailable:
                    continue
                except DataError as exc:
                    if exc.code != 'not_found':
                        raise
                    continue
                state = db.execute('select status from v1_states where record_id=? and version=?',
                                   (record_id, version)).fetchone()
                doc = versions[file_id]
                items.append({'appId': record[0], 'recordId': record_id, 'recordVersion': version,
                              'recordStatus': state[0] if state else None,
                              'latest': record[1] == version, 'fileId': file_id,
                              'entryVersion': doc['version'], 'fileStatus': doc['status']})
            return {'items': items, 'entryId': entry_id}

    def record_files(self, user, app_id, record_id, version):
        """记录侧取回当时引用的文件版本；未登记或无权查看的条目不出现在结果里。"""
        with self.store._lock:
            db = self.store._db
            self.data._record(db, user, app_id, record_id, version)
            rows = db.execute('select file_id from v1_file_uses where record_id=? and version=? order by file_id',
                              (record_id, version)).fetchall()
            items = []
            for (file_id,) in rows:
                linked = db.execute(
                    'select e.document,v.document from kb_versions v join kb_entries e on e.id=v.entry_id '
                    'where v.file_id=? order by v.entry_id,v.version', (file_id,)).fetchall()
                for entry_raw, version_raw in linked:
                    entry, doc = json.loads(entry_raw), json.loads(version_raw)
                    if not self.allowed(user, entry):
                        continue
                    items.append({
                        'fileId': file_id, 'entryId': entry['id'], 'entryVersion': doc['version'],
                        'title': entry['title'], 'category': entry['category'],
                        'fileStatus': doc['status'], 'sha256': doc['sha256'], 'size': doc['size'],
                    })
                    break  # 一个原件只归属一条条目：按条目 ID 稳定取第一条
                else:
                    registered = db.execute('select 1 from kb_versions where file_id=? limit 1', (file_id,)).fetchone()
                    if not registered:
                        items.append({'fileId': file_id, 'entryId': None, 'registered': False})
            return {'appId': app_id, 'recordId': record_id, 'version': version, 'items': items}

    def read(self, user, entry_id, version=None):
        """读取原件字节；版本默认取已发布版，维护人可直接读最新版。"""
        with self.store._lock:
            db = self.store._db
            entry = self._entry(db, entry_id)
            if version is None:
                version = entry['publishedVersion'] if entry['publishedVersion'] is not None \
                    else entry['latestVersion']
            doc = self._version(db, entry_id, version)
            self._require_readable(user, entry, doc)
            blob = self.data.blobs / doc['sha256']
            if not blob.is_file():
                raise DataError('invalid_state', '原件缺失，请联系管理员核对备份')
            return blob.read_bytes(), doc

    # ---------- v1 文件授权挂点 ----------

    def guard_file(self, user, file_id):
        """DataService._file 的挂点：返回是否因公司共享而跳过文件项目校验。"""
        with self.store._lock:
            rows = self.store._db.execute(
                'select document from kb_entries where id in (select entry_id from kb_versions where file_id=?)',
                (file_id,)).fetchall()
        shared = bool(rows)
        for (raw,) in rows:
            entry = json.loads(raw)
            project = entry.get('project')
            if not project or entry.get('scope', 'project') != 'company':
                shared = False
                if project and not self.data.projects.visible(user, project):
                    raise DataError('not_found', '项目或资源不存在')
            if not self.allowed(user, entry):
                raise DataError('forbidden', '原件受知识库权限限制', fileId=file_id)
        return shared

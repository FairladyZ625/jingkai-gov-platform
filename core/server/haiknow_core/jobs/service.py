"""单进程持久队列：任务、检查点、通知与审计共用平台 SQLite 事务。"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field, JsonValue, ValidationError
from starlette.requests import Request

from haiknow_sdk import DataError, ModelError
from haiknow_sdk.ai import AIError

from ..error_codes import public_error_code


STATES = ('queued', 'running', 'done', 'failed', 'cancelling', 'cancelled')
TERMINAL = ('done', 'failed', 'cancelled')


class SubmitBody(BaseModel):
    appId: str = Field(min_length=1, max_length=100)
    project: str = Field(min_length=1, max_length=100)
    operation: str = Field(min_length=1, max_length=100)
    idempotencyKey: str = Field(min_length=1, max_length=200)
    input: dict[str, JsonValue]


def encode(value):
    """只在输入、步骤结果、最终结果的写入边界检查 JSON。"""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise DataError('invalid_request', '任务输入和结果必须是有限 JSON 值') from e


class Cancelled(Exception):
    pass


class Interrupted(Exception):
    pass


class Execution:
    def __init__(self, service, doc):
        self._s = service
        self.id, self.attempt = doc['id'], doc['attempt']
        self.project = doc['project']
        # 与真实应用请求复用同一个身份、权限和 SDK 上下文构造路径。
        request = Request({'type': 'http', 'path': f"/api/apps/{doc['appId']}/jobs", 'query_string': b'', 'headers': [],
                           'app': service.app, 'session': {'uid': doc['submitter']}})
        self.context = service.platform.resolve(request)
        self._step = None

    def check_cancelled(self):
        with self._s.store._lock:
            doc = self._s._load(self.id)
            if doc['status'] == 'cancelling':
                raise Cancelled()
            self._s._authorize(self.context.user, doc, action='operate')
        if self._s.stopping.is_set():
            raise Interrupted()

    def step(self, name, fn):
        """已完成步骤直接读结果；fn 接收稳定步骤键，用于外部副作用去重。"""
        if not isinstance(name, str) or not name or len(name) > 100 or self._step is not None:
            raise DataError('invalid_request', '步骤名称不能为空、超过 100 字或嵌套执行')
        self.check_cancelled()
        with self._s.store._lock, self._s.store._db:
            doc = self._s._load(self.id)
            step = next((s for s in doc['steps'] if s['name'] == name), None)
            if step and step['status'] == 'done':
                return step['result']
            if step is None:
                step = {'name': name, 'key': f'{self.id}:{name}', 'result': None}
                doc['steps'].append(step)
            step.update(status='running', startedAt=time.time(), finishedAt=None, progress=None)
            self._s._save(doc, 'step.running')
        self._step = name
        try:
            result = fn(step['key'])
            encode(result)
            with self._s.store._lock, self._s.store._db:
                doc = self._s._load(self.id)
                step = next(s for s in doc['steps'] if s['name'] == name)
                step.update(status='done', result=result, finishedAt=time.time())
                self._s._save(doc, 'step.done')
            return result
        finally:
            self._step = None

    def progress(self, current: int, total: int):
        if (self._step is None or type(current) is not int or type(total) is not int
                or not 0 <= current <= total or total < 1):
            raise DataError('invalid_request', '请在步骤内提交有效的进度与总量')
        self.check_cancelled()
        with self._s.store._lock, self._s.store._db:
            doc = self._s._load(self.id)
            step = next(s for s in doc['steps'] if s['name'] == self._step)
            step['progress'] = {'current': current, 'total': total}
            # 高频进度只更新快照，步骤开始/结束另有审计。
            self._s._write(doc)


class JobService:
    def __init__(self, platform, app):
        self.platform, self.app, self.store = platform, app, platform.store
        self.operations = {}
        for app_id, entry in platform.apps.items():
            if entry.status != 'ok':
                continue
            module = sys.modules.get('haiknow_apps.' + app_id.replace('-', '_') + '.router')
            definitions = getattr(module, '__haiknow_jobs__', {})
            self.operations.update({(app_id, name): value for name, value in definitions.items()})
        self.stopping = threading.Event()

    def _load(self, jid):
        row = self.store._db.execute('select document from v1_jobs where id=?', (jid,)).fetchone()
        if not row:
            raise DataError('not_found', '任务不存在')
        return json.loads(row[0])

    def _authorize(self, user, doc, action='view', app_id=None):
        if app_id is not None and doc['appId'] != app_id:
            raise DataError('not_found', '任务不存在')
        self.platform.data.projects.require(user, doc['project'])
        self.platform.data.app(user, doc['appId'])
        if user.id != doc['submitter'] and 'admin' not in self.platform.rbac.actions(user, doc['appId']):
            raise DataError('not_found', '任务不存在')
        self.platform.data.app(user, doc['appId'], action)

    def _write(self, doc):
        doc['updatedAt'] = time.time()
        self.store._db.execute('update v1_jobs set status=?,document=? where id=?',
                               (doc['status'], encode(doc), doc['id']))

    def _save(self, doc, action, *, actor=None):
        self._write(doc)
        self.store.audit(doc['appId'], actor or doc['submitter'], 'job.' + action,
                         {'jobId': doc['id'], 'attempt': doc['attempt']}, connection=self.store._db)

    def _data_error_code(self, doc, code):
        entry = self.platform.apps.get(doc['appId'])
        return public_error_code(code, app_dir=entry.dir if entry else None)

    def _view(self, doc, *, public):
        # doc 是本次从 SQLite 解码的快照。HTTP 和 Python SDK 都隐藏内部存储字段。
        http_code = doc.pop('errorHttpCode', None)
        if public and (error := doc.get('error')):
            if http_code is None:
                # 无来源的旧记录按所属应用的精确登记解释。
                http_code = self._data_error_code(doc, error['code'])
            doc['error'] = {**error, 'code': http_code}
        return doc

    def _finish(self, doc, status, *, result=None, error=None, http_code=None, actor=None):
        doc.update(status=status, result=result, error=error, finishedAt=time.time())
        if http_code is not None:
            doc['errorHttpCode'] = http_code
        for step in doc['steps']:
            if step['status'] == 'running':
                step.update(status='cancelled' if status == 'cancelled' else 'failed', finishedAt=time.time())
        self._save(doc, status, actor=actor)
        nid = uuid.uuid4().hex
        note = {'id': nid, 'jobId': doc['id'], 'appId': doc['appId'], 'attempt': doc['attempt'],
                'status': status, 'createdAt': time.time(), 'read': False}
        self.store._db.execute('insert into v1_job_notifications values (?,?,?,?)',
                               (nid, doc['id'], doc['attempt'], encode(note)))

    def submit(self, user, body, *, public=False):
        try:
            body = SubmitBody.model_validate(body).model_dump()
        except ValidationError as e:
            raise DataError('invalid_request', '请求字段缺失或类型不正确') from e
        app_id = body['appId']
        self.platform.data.projects.require(user, body['project'])
        self.platform.data.app(user, app_id, 'operate')
        request = encode({k: body[k] for k in ('operation', 'project', 'input')})
        with self.store._lock, self.store._db:
            row = self.store._db.execute('select request,document from v1_jobs where app=? and submitter=? and dedup_key=?',
                                         (app_id, user.id, body['idempotencyKey'])).fetchone()
            if row:
                doc = json.loads(row[1])
                if row[0] != request:
                    raise DataError('invalid_state', '防重复编号已用于其他内容，请换编号', jobId=doc['id'])
                return self._view(doc, public=public)
            operation = self.operations.get((app_id, body['operation']))
            if operation is None:
                raise DataError('invalid_request', '任务操作未登记')
            doc = {'id': uuid.uuid4().hex, **body, 'submitter': user.id, 'version': operation[0],
                   'status': 'queued', 'attempt': 1, 'steps': [], 'result': None, 'error': None,
                   'createdAt': time.time(), 'updatedAt': time.time(), 'startedAt': None, 'finishedAt': None}
            self.store._db.execute('insert into v1_jobs values (?,?,?,?,?,?,?)',
                                   (doc['id'], app_id, user.id, body['idempotencyKey'], request, 'queued', encode(doc)))
            self._save(doc, 'submit')
            return doc

    def get(self, user, jid, *, app_id=None, public=False):
        with self.store._lock:
            doc = self._load(jid)
            self._authorize(user, doc, app_id=app_id)
        return self._view(doc, public=public)

    def list(self, user, *, app_id=None, project=None, status=None, public=False):
        if app_id is not None:
            self.platform.data.app(user, app_id)
        if project is not None:
            self.platform.data.projects.require(user, project)
        if status is not None and status not in STATES:
            raise DataError('invalid_request', '任务状态无效')
        with self.store._lock:
            items = []
            for (raw,) in self.store._db.execute('select document from v1_jobs order by rowid desc').fetchall():
                doc = json.loads(raw)
                if ((app_id is not None and doc['appId'] != app_id) or
                        (project is not None and doc['project'] != project) or
                        (status is not None and doc['status'] != status)):
                    continue
                try:
                    self._authorize(user, doc)
                except DataError as e:
                    if e.code != 'not_found':
                        raise
                    continue
                items.append(doc)
        return {'items': [self._view(doc, public=public) for doc in items]}

    def cancel(self, user, jid, *, app_id=None):
        with self.store._lock, self.store._db:
            doc = self._load(jid)
            self._authorize(user, doc, 'operate', app_id)
            if doc['status'] == 'queued':
                self._finish(doc, 'cancelled', actor=user.id)
            elif doc['status'] == 'running':
                doc['status'] = 'cancelling'
                self._save(doc, 'cancel', actor=user.id)
            elif doc['status'] in ('done', 'failed'):
                raise DataError('invalid_state', '任务已经结束，不能取消', jobId=jid)
            return doc

    def retry(self, user, jid, *, app_id=None):
        with self.store._lock, self.store._db:
            doc = self._load(jid)
            self._authorize(user, doc, 'operate', app_id)
            if doc['status'] != 'failed':
                raise DataError('invalid_state', '只有失败任务可以重试', jobId=jid)
            self._operation(doc)
            doc.update(status='queued', attempt=doc['attempt'] + 1, error=None, result=None,
                       startedAt=None, finishedAt=None)
            doc.pop('errorHttpCode', None)
            self._save(doc, 'retry', actor=user.id)
            return doc

    def _operation(self, doc):
        operation = self.operations.get((doc['appId'], doc['operation']))
        if not operation or operation[0] != doc['version']:
            raise DataError('invalid_state', '任务操作版本不可用，请恢复原版本', jobId=doc['id'])
        return operation[1]

    def notifications(self, user, *, app_id=None):
        if app_id is not None:
            self.platform.data.app(user, app_id)
        with self.store._lock:
            items = []
            for (raw,) in self.store._db.execute('select document from v1_job_notifications order by rowid desc').fetchall():
                note = json.loads(raw)
                doc = self._load(note['jobId'])
                if note['read'] or doc['submitter'] != user.id or (app_id is not None and note['appId'] != app_id):
                    continue
                try:
                    self._authorize(user, doc)
                except DataError as e:
                    if e.code != 'not_found':
                        raise
                    continue
                items.append(note)
            return {'items': items}

    def read_notification(self, user, nid, *, app_id=None):
        with self.store._lock, self.store._db:
            row = self.store._db.execute('select document from v1_job_notifications where id=?', (nid,)).fetchone()
            if not row:
                raise DataError('not_found', '通知不存在')
            note = json.loads(row[0])
            doc = self._load(note['jobId'])
            self._authorize(user, doc, app_id=app_id)
            if doc['submitter'] != user.id:
                raise DataError('not_found', '通知不存在')
            if not note['read']:
                note['read'] = True
                self.store._db.execute('update v1_job_notifications set document=? where id=?', (encode(note), nid))
                self._save(doc, 'notification.read')
            return note

    def start(self):
        self.stopping.clear()
        with self.store._lock, self.store._db:
            for (jid,) in self.store._db.execute("select id from v1_jobs where status in ('running','cancelling')").fetchall():
                doc = self._load(jid)
                if doc['status'] == 'cancelling':
                    self._finish(doc, 'cancelled')
                else:
                    doc['status'] = 'queued'
                    self._save(doc, 'recover')
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='haiknow-job')
        self.thread = threading.Thread(target=self._dispatch, name='haiknow-jobs', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.thread.join()
        self.pool.shutdown(wait=True)

    def _dispatch(self):
        running = set()
        while not self.stopping.is_set():
            for future in list(running):
                if future.done():
                    future.result()
                    running.remove(future)
            with self.store._lock, self.store._db:
                ids = self.store._db.execute("select id from v1_jobs where status='queued' order by rowid limit ?",
                                             (3 - len(running),)).fetchall()
                for (jid,) in ids:
                    doc = self._load(jid)
                    doc.update(status='running', startedAt=time.time())
                    self._save(doc, 'running')
            for (jid,) in ids:
                running.add(self.pool.submit(self._run, jid))
            self.stopping.wait(.02)

    def _run(self, jid):
        http_code = None
        try:
            with self.store._lock:
                doc = self._load(jid)
                user = self.platform.rbac.users.get(doc['submitter'])
                if user is None:
                    raise DataError('not_found', '任务提交人已不可用')
                self._authorize(user, doc, 'operate')
            execution = Execution(self, doc)
            execution.check_cancelled()
            result = self._operation(doc)(execution, doc['input'])
            encode(result)
            status, error = 'done', None
        except Interrupted:
            with self.store._lock, self.store._db:
                doc = self._load(jid)
                if doc['status'] == 'cancelling':
                    self._finish(doc, 'cancelled')
                else:
                    doc['status'] = 'queued'
                    self._save(doc, 'interrupted')
            return
        except Cancelled:
            status, result, error = 'cancelled', None, None
        except Exception as e:
            status, result = 'failed', None
            if isinstance(e, DataError):
                error = e.error
            elif isinstance(e, (AIError, ModelError)):
                error = {'code': e.kind, 'message': str(e), 'retryable': getattr(e, 'retryable', False)}
                http_code = e.kind.upper()
            else:
                logging.getLogger('haiknow').error('后台任务 %s 失败：%s', jid, type(e).__name__)
                error = DataError('internal_error', '任务执行失败，请联系管理员').error
            error = {**error, 'jobId': jid}
        with self.store._lock, self.store._db:
            doc = self._load(jid)
            # 正在执行的同步调用无法撤回；等调用返回后才确认取消。
            if doc['status'] == 'cancelling':
                status, result, error, http_code = 'cancelled', None, None, None
            elif error is not None and http_code is None:
                http_code = self._data_error_code(doc, error['code'])
            self._finish(doc, status, result=result, error=error, http_code=http_code)

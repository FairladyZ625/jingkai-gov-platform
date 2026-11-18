"""应用上架状态、前端版本与运行记录。"""
from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, ConfigDict, Field

from .manifest import VERSION_RE


def now():
    return datetime.now(timezone.utc).isoformat()


def snapshot_path(store, app_id, version):
    # 版本号会拼进 data/app-versions 目录；清单校验之外的调用方也不能越界。
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError('应用版本必须是安全的路径名称')
    return store.data_dir / 'app-versions' / app_id / version


def register(plat, directory, manifest, initial=None):
    """initial=(state, audience) 让新应用一登记就是灰度/草稿，不经过全员可见的瞬间。"""
    store, app_id = plat.store, manifest['id']
    version = str(manifest.get('version', '0'))
    target = snapshot_path(store, app_id, version)
    web = directory / 'web'
    # 首次见到版本时保存快照，部署覆盖旧目录后才能回滚。
    if web.is_dir() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(web, target)
    with store._lock, store._db:
        db = store._db
        row = db.execute('select deployed_version from app_registry where app_id=?', (app_id,)).fetchone()
        if row is None:
            state = 'live' if store.app_enabled(app_id) else 'disabled'
            audience = '[]'
            if initial:
                state, audience = initial[0], json.dumps(initial[1], ensure_ascii=False)
            db.execute('insert into app_registry values (?,?,?,?,?,?,?,?,?)',
                       (app_id, state, audience, version, None, None, now(), 'system', version))
        elif row[0] != version:
            db.execute('update app_registry set previous_version=version, version=?, deployed_version=?, updated_at=?, updated_by=? where app_id=?',
                       (version, version, now(), 'system', app_id))


def registry(plat, app_id):
    with plat.store._lock:
        row = plat.store._db.execute('select state,audience_json,version,previous_version,disabled_reason,updated_at,updated_by,deployed_version from app_registry where app_id=?', (app_id,)).fetchone()
    return dict(zip(('state', 'audience_json', 'version', 'previous_version', 'disabled_reason', 'updated_at', 'updated_by', 'deployed_version'), row))


def visible(plat, app_id, user, admin):
    if admin:
        return True
    row = registry(plat, app_id)
    if row['state'] == 'draft':
        return False
    if row['state'] != 'gray':
        return True
    directory = getattr(plat, 'directory', None)
    roles = directory.roles_of(user.id) if directory else frozenset(user.roles)
    depts = directory.departments_of(user.id) if directory else frozenset()
    groups = {'user': {user.id}, 'role': roles, 'dept': depts}
    return any(item['id'] in groups[item['type']] for item in json.loads(row['audience_json']))


class VersionedStaticFiles(StaticFiles):
    def __init__(self, plat, app_id, directory):
        super().__init__(directory=directory)
        self.plat, self.app_id, self.original = plat, app_id, str(directory)

    def lookup_path(self, path):
        row = registry(self.plat, self.app_id)
        directory = self.original if row['version'] == row['deployed_version'] else str(snapshot_path(self.plat.store, self.app_id, row['version']))
        # 不修改共享 StaticFiles 状态，避免并发请求之间串目录。
        return StaticFiles(directory=directory).lookup_path(path)


class Audience(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['user', 'role', 'dept']
    id: str = Field(min_length=1)


class Patch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    state: Literal['draft', 'gray', 'live', 'disabled'] | None = None
    audience: list[Audience] | None = None
    disabledReason: str | None = None


def update(plat, app_id, user, state=None, audience=None, reason=None, legacy=False):
    store = plat.store
    with store._lock, store._db:
        db = store._db
        row = registry(plat, app_id)
        state = state if state is not None else row['state']
        audience = json.dumps(audience, ensure_ascii=False) if audience is not None else row['audience_json']
        reason = reason if reason is not None else row['disabled_reason']
        enabled = state != 'disabled'
        db.execute('update app_registry set state=?,audience_json=?,disabled_reason=?,updated_at=?,updated_by=? where app_id=?',
                   (state, audience, reason, now(), user.id, app_id))
        db.execute('insert into app_control values (?,?) on conflict(app_id) do update set enabled=excluded.enabled', (app_id, int(enabled)))
        store.audit('platform', user.id, 'app.update', {'appId': app_id, 'state': state}, connection=db)
        if legacy:
            store.audit(app_id, user.id, 'app.enable' if enabled else 'app.disable', {}, connection=db)
        plat.apps[app_id].enabled = enabled


def record_run(plat, app_id, user_id, method, path, status, ms, error):
    with plat.store._lock, plat.store._db:
        db = plat.store._db
        db.execute('insert into app_runs values (?,?,?,?,?,?,?,?)', (now(), app_id, user_id, method, path, status, ms, error))
        # 每应用最多保留最新一万条，按插入顺序裁剪。
        db.execute('delete from app_runs where app_id=? and rowid not in (select rowid from app_runs where app_id=? order by rowid desc limit 10000)', (app_id, app_id))


def install(app, plat, current_user):
    def admin(user=Depends(current_user)):
        if 'admin' not in plat.rbac.actions(user, '*'):
            raise HTTPException(403, '需要管理员权限')
        return user

    def get_app(app_id):
        if app_id not in plat.apps:
            raise HTTPException(404, '应用不存在')
        return plat.apps[app_id]

    previous_http_handler = app.exception_handlers[StarletteHTTPException]
    previous_validation_handler = app.exception_handlers[RequestValidationError]

    @app.exception_handler(StarletteHTTPException)
    async def admin_errors(request, exc):
        if request.url.path.startswith('/api/admin/apps'):
            codes = {400: 'invalid_request', 401: 'unauthorized', 403: 'forbidden', 404: 'not_found', 409: 'conflict'}
            return JSONResponse({'error': {'code': codes.get(exc.status_code, 'error').upper(), 'message': str(exc.detail)}}, status_code=exc.status_code, headers=exc.headers)
        return await previous_http_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def admin_validation_errors(request, exc):
        if request.url.path.startswith('/api/admin/apps'):
            return JSONResponse({'error': {'code': 'INVALID_REQUEST', 'message': '请求参数无效'}}, status_code=400)
        return await previous_validation_handler(request, exc)

    def view(app_id):
        entry = get_app(app_id)
        row = registry(plat, app_id)
        return {'id': app_id, 'name': entry.manifest['name'], 'version': row['version'], 'previousVersion': row['previous_version'],
                'state': row['state'], 'audience': json.loads(row['audience_json']), 'enabled': entry.enabled,
                'available': not bool(entry.unavailable_reason()), 'error': entry.unavailable_reason() or None,
                'disabledReason': row['disabled_reason'], 'updatedAt': row['updated_at'], 'updatedBy': row['updated_by']}

    @app.get('/api/admin/apps')
    def list_apps(user=Depends(admin)):
        return {'apps': [view(app_id) for app_id in plat.apps]}

    @app.patch('/api/admin/apps/{app_id}')
    def patch_app(app_id: str, body: Patch, user=Depends(admin)):
        get_app(app_id)
        update(plat, app_id, user, body.state, [a.model_dump() for a in body.audience] if body.audience is not None else None, body.disabledReason)
        return view(app_id)

    @app.post('/api/admin/apps/{app_id}/rollback')
    def rollback(app_id: str, user=Depends(admin)):
        get_app(app_id)
        with plat.store._lock, plat.store._db:
            row = registry(plat, app_id)
            previous = row['previous_version']
            if not previous or not snapshot_path(plat.store, app_id, previous).is_dir():
                raise HTTPException(409, '没有可用的上一版本前端快照')
            plat.store._db.execute('update app_registry set version=?, previous_version=?, updated_at=?, updated_by=? where app_id=?', (previous, row['version'], now(), user.id, app_id))
            plat.store.audit('platform', user.id, 'app.rollback', {'appId': app_id, 'version': previous}, connection=plat.store._db)
        return view(app_id)

    @app.get('/api/admin/apps/{app_id}/logs')
    def logs(app_id: str, since: str | None = None, level: Literal['error', 'info'] | None = None, limit: int = Query(100, ge=1, le=10000), user=Depends(admin)):
        get_app(app_id)
        sql, args = 'select ts,user_id,method,path,status,ms,error from app_runs where app_id=?', [app_id]
        if since:
            try:
                since = datetime.fromisoformat(since.replace('Z', '+00:00')).astimezone(timezone.utc).isoformat()
            except ValueError:
                raise HTTPException(400, 'since 必须是 ISO8601 时间')
            sql += ' and ts>=?'; args.append(since)
        if level == 'error': sql += ' and (status>=500 or error is not null)'
        if level == 'info': sql += ' and status<500 and error is null'
        with plat.store._lock:
            rows = plat.store._db.execute(sql + ' order by rowid desc limit ?', (*args, limit)).fetchall()
        return {'logs': [dict(zip(('ts', 'userId', 'method', 'path', 'status', 'ms', 'error'), row)) for row in rows]}

    @app.get('/api/admin/apps/{app_id}/stats')
    def stats(app_id: str, hours: int = Query(24, ge=1, le=8760), user=Depends(admin)):
        get_app(app_id)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        with plat.store._lock:
            rows = plat.store._db.execute('select status,ms,error from app_runs where app_id=? and ts>=?', (app_id, cutoff)).fetchall()
        durations = sorted(r[1] for r in rows)
        return {'requests': len(rows), 'errors': sum(1 for status, _, error in rows if status >= 500 or error), 'p95ms': durations[math.ceil(len(durations)*.95)-1] if durations else 0}

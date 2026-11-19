"""角色、授权、应用发布状态与平台设置的 v1 路由。"""

import json
import math
from typing import Literal

import yaml
from fastapi import Depends, Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from starlette.routing import get_route_path

from haiknow_core import admin_apps
from haiknow_core.identity_http import Body, Name
from haiknow_core.identity_models import GRANT_ACTIONS
from jkq.auth import ROLE_ORDER, AuthError, current_user

from ..app_catalogs import internal_app_ids
from .common import record_change, write

_ACTION_NAMES = ('查看', '操作', '审签', '管理')
_APP_NAMES = {
    '*': '全部应用', 'policy': '政策兑现咨询', 'enterprise': '企业管理维护', 'meeting': '会议记录',
    'document': '公文协作', 'kb': '知识库', 'skills': '技能中心', 'computer': '电脑操作',
}
_PUBLIC_APP_FIELDS = (
    'id', 'name', 'short', 'icon', 'color', 'kind', 'owner', 'summary', 'tools',
    'uses', 'rating', 'starters', 'sector', 'scenes',
)
_ROLE_KEY = 'jkq.role:'
_MAINTENANCE_KEY = 'jkq.app.maintenance'
AppStatus = Literal['published', 'live', 'maintenance', 'disabled', 'draft', 'gray']
Action = Literal['view', 'operate', 'approve', 'admin']


class RolePatch(Body):
    desc: str = Field(default=None, max_length=1000)
    mask: bool = None


class GrantUpdate(Body):
    actions: list[Action]


class AppPatch(Body):
    status: AppStatus = None
    statusNote: str = Field(default=None, max_length=1000)


class SettingsFields(Body):
    platformName: Name = None
    sessionMinutes: int = Field(default=None, ge=1, le=43200)
    sessionHours: float = Field(default=None, ge=1 / 60, le=720)
    watermark: bool = None
    defaultHome: str = Field(default=None, max_length=100, pattern=r'^(?:#/)?[a-z][a-z0-9/-]*$')
    orgName: Name = None


class SettingsUpdate(SettingsFields):
    settings: SettingsFields = None
    seats: int = Field(default=None, ge=1)


class RefreshAppState:
    """让已运行实例在下一个应用请求读取已提交的开关。"""

    def __init__(self, app, platform):
        self.app, self.platform = app, platform

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            path = get_route_path(scope)
            for prefix in ('/api/apps/', '/api/v1/apps/'):
                if path.startswith(prefix):
                    app_id = path[len(prefix):].split('/', 1)[0]
                    if app_id in self.platform.apps:
                        await run_in_threadpool(self.refresh, app_id)
                    break
        await self.app(scope, receive, send)

    def refresh(self, app_id):
        store = self.platform.store
        with store._lock:
            self.platform.apps[app_id].enabled = store.app_enabled(app_id)


def _settings_value(db, key, default):
    row = db.execute('select value from settings where key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def _save_settings(db, changes):
    db.executemany(
        'insert into settings(key,value) values (?,?) on conflict(key) do update set value=excluded.value',
        [(key, json.dumps(value, ensure_ascii=False)) for key, value in changes.items()],
    )


def _roles(db, defaults):
    names = dict(db.execute('select id,name from roles order by id'))
    items = {}
    for ident in dict.fromkeys((*ROLE_ORDER, *names)):
        if ident not in names:
            continue
        spec = defaults.get(ident, {})
        metadata = {'desc': spec.get('desc', ''), 'mask': spec.get('mask', False)}
        metadata.update(_settings_value(db, _ROLE_KEY + ident, {}))
        items[ident] = dict(id=ident, name=names[ident], **metadata)
    return items


def _actions(values):
    return [action for action in GRANT_ACTIONS if action in values]


def _matrix(db, roles):
    matrix = {role: {} for role in roles}
    for role, app, action in db.execute('select role_id,app_id,action from role_grants order by role_id,app_id'):
        if role in matrix:
            matrix[role].setdefault(app, []).append(action)
    return {role: {app: _actions(actions) for app, actions in grants.items()} for role, grants in matrix.items()}


def _app_status(db, app_id, row):
    state = row['state']
    if state == 'disabled':
        marker = db.execute('select value from kv where app_id=? and key=?',
                            (app_id, _MAINTENANCE_KEY)).fetchone()
        if marker:
            audit_id = json.loads(marker[0])
            # 保留备注、灰度人群及版本更新前的维护标记。显式开关或离开停用态时接管。
            if not db.execute(
                "select 1 from audit where id>? and ((app_id=? and action in ('app.enable','app.disable')) "
                "or (app_id='platform' and action='app.update' and json_valid(detail) "
                "and json_extract(detail,'$.appId')=? and json_extract(detail,'$.state')<>'disabled')) limit 1",
                (audit_id, app_id, app_id),
            ).fetchone():
                state = 'maintenance'
    return {'status': 'published' if state == 'live' else state, 'statusNote': row['disabled_reason'] or ''}


def _app_item(entry, row, status, actions):
    return {
        **{key: entry.manifest[key] for key in _PUBLIC_APP_FIELDS if key in entry.manifest},
        **status, 'version': row['version'], 'enabled': entry.enabled, 'available': not entry.unavailable_reason(),
        'hasWeb': entry.has_web, 'actions': _actions(actions),
    }


def _settings(platform, db):
    settings = platform.directory.settings()
    settings['sessionHours'] = settings['sessionMinutes'] / 60
    settings['watermark'] = _settings_value(db, 'watermark', False)
    settings['orgName'] = _settings_value(db, 'orgName', platform.directory.company()['name'])
    return dict(settings=settings, seats=_settings_value(db, 'seats', 25))


def _settings_changes(body):
    changes = body.model_dump(exclude_unset=True, exclude={'settings'})
    if body.settings is not None:
        for key, value in body.settings.model_dump(exclude_unset=True).items():
            if key in changes and changes[key] != value:
                raise AuthError(400, 'INVALID_REQUEST', '同一设置的值不一致', field=key)
            changes[key] = value
    if 'sessionHours' in changes:
        minutes = changes.pop('sessionHours') * 60
        rounded = round(minutes)
        if not math.isclose(minutes, rounded, rel_tol=0, abs_tol=1e-9):
            raise AuthError(400, 'INVALID_REQUEST', '会话时长须换算为整分钟', field='sessionHours')
        if changes.get('sessionMinutes', rounded) != rounded:
            raise AuthError(400, 'INVALID_REQUEST', '会话时长的小时数和分钟数不一致')
        changes['sessionMinutes'] = rounded
    return changes


def register(router, platform, admin):
    store = platform.store
    config = yaml.safe_load((platform.config_dir / 'roles.yaml').read_text(encoding='utf-8'))
    defaults = config['roles']
    configured_apps = config.get('apps', [])

    def app_names():
        return {
            **{ident: _APP_NAMES.get(ident, ident) for ident in ('*', *configured_apps)},
            **{ident: entry.manifest['name'] for ident, entry in platform.apps.items()},
        }

    @router.get('/api/v1/admin/roles')
    def list_roles(user=Depends(admin)):
        with store._lock:
            return {'items': list(_roles(store._db, defaults).values())}

    @router.patch('/api/v1/admin/roles/{role_id}')
    def patch_role(role_id: str, body: RolePatch, request: Request, user=Depends(admin)):
        with write(platform, user) as db:
            before = _roles(db, defaults).get(role_id)
            if before is None:
                raise AuthError(404, 'NOT_FOUND', '角色不存在')
            after = before | body.model_dump(exclude_unset=True)
            _save_settings(db, {_ROLE_KEY + role_id: {'desc': after['desc'], 'mask': after['mask']}})
            record_change(platform, db, user, request, action='identity.role.update',
                          target=role_id, before=before, after=after)
        return {'item': after}

    @router.get('/api/v1/admin/grants')
    def list_grants(user=Depends(admin)):
        with store._lock:
            db = store._db
            roles = _roles(db, defaults)
            # 内部续跑等 internal 应用不进授权矩阵（#135）。
            hidden = internal_app_ids(platform)
            grants = {role: {app: acts for app, acts in items.items() if app not in hidden}
                      for role, items in _matrix(db, roles).items()}
            return dict(roles=list(roles.values()),
                        apps=[dict(id=ident, name=name) for ident, name in app_names().items()
                              if ident not in hidden],
                        grants=grants, actions=list(zip(GRANT_ACTIONS, _ACTION_NAMES)))

    @router.put('/api/v1/admin/grants/{role_id}/{app_id}')
    def update_grant(role_id: str, app_id: str, body: GrantUpdate, request: Request, user=Depends(admin)):
        with write(platform, user) as db:
            roles = _roles(db, defaults)
            if role_id not in roles:
                raise AuthError(404, 'NOT_FOUND', '角色不存在')
            if app_id not in app_names():
                raise AuthError(404, 'NOT_FOUND', '应用不存在')
            actions = _actions(body.actions)
            if role_id == 'admin' and app_id == '*' and 'admin' not in actions:
                raise AuthError(400, 'SELF_LOCK', '不能收回管理员角色的全局管理权限')
            old = _actions({row[0] for row in db.execute(
                'select action from role_grants where role_id=? and app_id=?', (role_id, app_id)
            )})
            db.execute('delete from role_grants where role_id=? and app_id=?', (role_id, app_id))
            db.executemany('insert into role_grants values (?,?,?)',
                           [(role_id, app_id, action) for action in actions])
            if app_id == '*' and 'admin' in old and not platform.directory.has_admin(db, active_only=True):
                raise AuthError(400, 'LAST_ADMIN', '必须保留至少一位启用的管理员')
            after = dict(role=role_id, app=app_id, actions=actions)
            record_change(platform, db, user, request, action='identity.grant.update',
                          app=app_id if app_id != '*' else 'platform', target=f'{role_id}/{app_id}',
                          before=after | {'actions': old}, after=after)
            grants = _matrix(db, roles)
        return dict(item=after, grants=grants)

    @router.get('/api/v1/apps')
    def list_apps(request: Request, user=Depends(current_user)):
        bridge = request.app.state.apps_bridge
        with store._lock, store._db as db:
            db.execute('BEGIN')
            is_admin = 'admin' in platform.rbac.actions(user, '*')
            items = []
            for app_id, entry in platform.apps.items():
                actions = platform.rbac.actions(user, app_id)
                if 'view' in actions and admin_apps.visible(platform, app_id, user, is_admin):
                    row = admin_apps.registry(platform, app_id)
                    entry.enabled = store.app_enabled(app_id)
                    item = _app_item(entry, row, _app_status(db, app_id, row), actions)
                    public = bridge.catalog_fields(entry, actions, is_admin)
                    if public.get('tools'):
                        item['tools'] = public['tools']
                    items.append(public | item)
        return {'items': items, 'skills': bridge.list_skills(user)}

    @router.patch('/api/v1/admin/apps/{app_id}')
    def patch_app(app_id: str, body: AppPatch, request: Request, user=Depends(admin)):
        with store._lock:
            with write(platform, user) as db:
                entry = platform.apps.get(app_id)
                if entry is None:
                    raise AuthError(404, 'NOT_FOUND', '应用不存在')
                row = admin_apps.registry(platform, app_id)
                before = _app_status(db, app_id, row)
                status = 'published' if body.status == 'live' else body.status or before['status']
                note = row['disabled_reason'] if body.statusNote is None else body.statusNote
                # 维护态沿用 core 的停用态，兼容旧接口的备注和运行开关逻辑。
                state = {'published': 'live', 'maintenance': 'disabled'}.get(status, status)
                enabled = state != 'disabled'
                stamp = admin_apps.now()
                db.execute(
                    'update app_registry set state=?,disabled_reason=?,updated_at=?,updated_by=? where app_id=?',
                    (state, note, stamp, user.id, app_id),
                )
                db.execute('insert into app_control values (?,?) on conflict(app_id) do update set enabled=excluded.enabled',
                           (app_id, int(enabled)))
                after = {'status': status, 'statusNote': note or ''}
                record_change(platform, db, user, request, action='app.update',
                              app=app_id, target=app_id, before=before, after=after)
                if status == 'maintenance':
                    audit_id, ts = db.execute(
                        'select id,ts from audit where id=last_insert_rowid()'
                    ).fetchone()
                    db.execute(
                        'insert into kv values (?,?,?,?) on conflict(app_id,key) '
                        'do update set value=excluded.value,updated=excluded.updated',
                        (app_id, _MAINTENANCE_KEY, json.dumps(audit_id), ts),
                    )
                else:
                    db.execute('delete from kv where app_id=? and key=?', (app_id, _MAINTENANCE_KEY))
            # 同一锁内先提交持久状态。审计或提交失败时，运行状态保持原值。
            entry.enabled = enabled
            return {'item': _app_item(entry, row, after, platform.rbac.actions(user, app_id))}

    @router.get('/api/v1/admin/settings')
    def get_settings(user=Depends(admin)):
        with store._lock:
            return _settings(platform, store._db)

    @router.put('/api/v1/admin/settings')
    def update_settings(body: SettingsUpdate, request: Request, user=Depends(admin)):
        changes = _settings_changes(body)
        with write(platform, user) as db:
            before = _settings(platform, db)
            _save_settings(db, changes)
            after = _settings(platform, db)
            record_change(platform, db, user, request, action='identity.settings.update',
                          target='settings', before=before, after=after)
        return after

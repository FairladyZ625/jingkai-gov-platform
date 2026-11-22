"""经开区账号接口与下游路由的授权依赖。"""

import json
import os
import time
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

import yaml
from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import Field

from haiknow_core.admin_identity import Administration
from haiknow_core.identity_http import Body, Identifier
from haiknow_core.passwords import hash_password, verify_password
from haiknow_sdk import ACTIONS

from ..app_catalogs import internal_app_ids
from .seeds import seed_identities


RoleId = Literal['admin', 'leader', 'member', 'partner']
ROLE_ORDER = ('admin', 'leader', 'member', 'partner')
LOCK_SECONDS = 10 * 60
BEIJING = ZoneInfo('Asia/Shanghai')


class AuthError(Exception):
    def __init__(self, status, code, message, **details):
        super().__init__(message)
        self.status = status
        self.error = dict(code=code, message=message, details=details)


def _error_response(error):
    return JSONResponse({'error': error.error}, status_code=error.status)


class AuthRoute(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def respond(request):
            try:
                return await handle(request)
            except RequestValidationError:
                # FastAPI 默认的错误详情会回显请求字段内容。
                error = AuthError(400, 'INVALID_REQUEST', '请求字段缺失或格式不正确')
                return _error_response(error)

        return respond


class LoginBody(Body):
    username: Identifier
    password: str = Field(max_length=1024)


class PasswordBody(Body):
    old: str = Field(max_length=1024)
    new: str = Field(max_length=1024)


class PrefsBody(Body):
    theme: Literal['light', 'dark', 'system'] = None
    defaultModel: Identifier = None
    operatorEnabled: bool = None


class RoleBody(Body):
    role: RoleId


def _session_user(request):
    platform = request.app.state.platform
    uid = request.session.get('uid')
    return platform.directory.session_user(uid, request.session.get('gen', 0)) if uid else None


def current_user(request: Request):
    """从卫华签名会话解析当前用户，供经开区路由注入。"""
    user = _session_user(request)
    if user is None:
        raise AuthError(401, 'UNAUTHENTICATED', '请先登录')
    return user


def require_action(app_id, action):
    """检查即时授权并留痕，供经开区路由注入。"""
    def check(request: Request, user=Depends(current_user)):
        platform = request.app.state.platform
        if action not in platform.rbac.actions(user, app_id):
            detail = dict(app=app_id, need=action)
            platform.store.audit(app_id, user.id, 'permission.denied', detail)
            raise AuthError(403, 'FORBIDDEN', '当前角色缺少所需权限', **detail)
        return user

    return check


def _settings_key(user):
    return 'jkq.prefs:' + user.id


def _prefs(db, user):
    row = db.execute('select value from settings where key=?', (_settings_key(user),)).fetchone()
    return json.loads(row[0]) if row else {}


def install(app, *, demo=None, clock=time.time):
    """在卫华 create_app() 后、经开区静态兜底和兼容层注册前调用。"""
    platform = app.state.platform
    directory, store = platform.directory, platform.store
    if directory.demo_login:
        raise RuntimeError('经开区实例须关闭 HAIKNOW_DEMO_LOGIN，演示模式请使用 JKQ_DEMO_MODE')
    if demo is None:
        demo = os.environ.get('JKQ_DEMO_MODE') == '1'
    deployed = os.environ.get('JKQ_DEPLOY_RUNTIME') == '1'

    config = yaml.safe_load((platform.config_dir / 'roles.yaml').read_text(encoding='utf-8'))
    demo_users = []
    if demo:
        demo_users = yaml.safe_load((platform.config_dir / 'users.yaml').read_text(encoding='utf-8'))['demoUsers']
    seed_identities(store, config['roles'], demo_users)
    directory.demo_login = demo
    profiles = {user['id']: user for user in demo_users}

    def document(user):
        db = store._db
        profile = profiles.get(user.id, {})
        identity = directory.profile(user)
        department = next(iter(identity['departments']), {})
        position = next(iter(identity['positions']), {})
        last_login = db.execute('select last_login from users where id=?', (user.id,)).fetchone()[0]
        role_id = next((role for role in ROLE_ORDER if role in user.roles), next(iter(user.roles), None))
        roles = directory.role_names()
        spec = config['roles'].get(role_id, {})
        return dict(
            id=user.id, username=identity['username'], name=user.name,
            deptId=department.get('id', profile.get('deptId')),
            dept=department.get('name', profile.get('dept', '')),
            title=position.get('name', profile.get('title', '')),
            role=role_id, status='active', lastLogin=last_login,
        ), dict(id=role_id, name=roles.get(role_id, ''), desc=spec.get('desc', ''), mask=spec.get('mask', False))

    def session_document(user):
        public_user, role = document(user)
        grants = {}
        internal = internal_app_ids(platform)
        for app_id in dict.fromkeys(('*', *config['apps'], *platform.apps)):
            if app_id in internal:
                continue
            allowed = platform.rbac.actions(user, app_id)
            grants[app_id] = [action for action in ACTIONS if action in allowed]
        return dict(user=public_user, role=role, grants=grants)

    router = APIRouter(route_class=AuthRoute)

    @router.post('/api/auth/login', include_in_schema=False)
    @router.post('/api/v1/auth/login')
    def login(body: LoginBody, request: Request):
        error = AuthError(401, 'BAD_CREDENTIALS', '账号或密码不正确')
        result = None
        with store._lock, store._db as db:
            store.begin_write()
            now = clock()
            row = db.execute(
                'select id,password_hash,status,failed_logins,locked_until,demo from users where username=?',
                (body.username,),
            ).fetchone()
            uid = row[0] if row and (demo or not row[5]) else None
            if uid is None:
                hash_password(body.password)
            elif row[2] != 'active':
                if verify_password(body.password, row[1]):
                    error = AuthError(403, 'ACCOUNT_DISABLED', '账号已停用，请联系管理员')
            elif row[4] > now:
                error = AuthError(409, 'LOCKED', '登录失败次数过多，请稍后重试', retryAt=datetime.fromtimestamp(
                    row[4], BEIJING).isoformat())
            elif not verify_password(body.password, row[1]):
                failures = (0 if row[4] else row[3]) + 1
                db.execute(
                    'update users set failed_logins=?,locked_until=? where id=?',
                    (failures, now + LOCK_SECONDS if failures >= 5 else 0, uid),
                )
            else:
                db.execute(
                    'update users set failed_logins=0,locked_until=0,last_login=? where id=?',
                    (datetime.fromtimestamp(now, BEIJING).isoformat(), uid),
                )
                generation = directory.session_gen(uid)
                result = session_document(directory.user(uid))
            if result is None:
                store.audit('platform', uid or 'anonymous', 'auth.login.failed',
                            {'code': error.error['code']}, connection=db)
            else:
                store.audit('platform', uid, 'login', {}, connection=db)

        if result is None:
            raise error
        request.session.clear()
        request.session.update(uid=uid, gen=generation)
        return result

    @router.post('/api/auth/logout', include_in_schema=False)
    @router.post('/api/v1/auth/logout')
    def logout(request: Request):
        with store._lock, store._db as db:
            store.begin_write()
            user = _session_user(request)
            if user:
                directory.bump_session_gen(db, user.id)
                store.audit('platform', user.id, 'logout', {}, connection=db)
        request.session.clear()
        return {'ok': True}

    @router.get('/api/auth/session', include_in_schema=False)
    @router.get('/api/v1/auth/session')
    def session(request: Request):
        with store._lock:
            user = _session_user(request)
            return {'user': document(user)[0] if user else None}

    @router.get('/api/v1/me')
    def me(request: Request):
        with store._lock:
            user = current_user(request)
            db = store._db
            used = db.execute("select count(*) from users where status='active' and (demo=0 or ?)", (demo,)).fetchone()[0]
            settings = directory.settings()
            seats = db.execute("select value from settings where key='seats'").fetchone()
            extra = {'isAdmin': 'admin' in platform.rbac.actions(user, '*')}
            models = getattr(request.app.state, 'jkq_models', None)
            if models is not None:  # 与 jkq.models 的 /me 默认模型保持一致
                extra['defaultModel'] = models.current(user.id)
                settings = {**settings, 'defaultModel': extra['defaultModel']}
            return dict(
                **session_document(user),
                org=dict(**directory.company(), seats=json.loads(seats[0]) if seats else None, used=used),
                settings=settings, prefs=_prefs(db, user), **extra,
            )

    @router.post('/api/auth/password', include_in_schema=False)
    @router.put('/api/v1/me/password')
    def password(body: PasswordBody, request: Request):
        with store._lock, store._db as db:
            store.begin_write()
            user = current_user(request)
            stored = db.execute('select password_hash from users where id=?', (user.id,)).fetchone()[0]
            if not verify_password(body.old, stored):
                raise AuthError(400, 'BAD_PASSWORD', '原密码不正确')
            if len(body.new) < 6:
                raise AuthError(400, 'WEAK_PASSWORD', '新密码至少 6 位')
            db.execute('update users set password_hash=?,failed_logins=0,locked_until=0 where id=?',
                       (hash_password(body.new), user.id))
            generation = directory.bump_session_gen(db, user.id)
            store.audit('platform', user.id, 'auth.password', {}, connection=db)
        request.session['gen'] = generation
        return {'ok': True}

    @router.patch('/api/v1/me/prefs')
    def update_prefs(body: PrefsBody, request: Request):
        changes = body.model_dump(exclude_unset=True)
        with store._lock, store._db as db:
            store.begin_write()
            user = current_user(request)
            prefs = _prefs(db, user) | changes
            db.execute(
                'insert into settings(key,value) values (?,?) on conflict(key) do update set value=excluded.value',
                (_settings_key(user), json.dumps(prefs, ensure_ascii=False)),
            )
            store.audit('platform', user.id, 'auth.prefs', {'fields': sorted(changes)}, connection=db)
        return {'prefs': prefs}

    if demo:
        # 演示视角可暂时不含管理员，首管引导仍须关闭。
        @router.get('/api/auth/state', include_in_schema=False)
        @router.get('/api/v1/auth/state', include_in_schema=False)
        def demo_auth_state():
            return {'needsBootstrap': False, 'demoLogin': False}

        @router.post('/api/auth/bootstrap', include_in_schema=False)
        @router.post('/api/v1/auth/bootstrap', include_in_schema=False)
        def demo_bootstrap_unavailable():
            raise AuthError(404, 'NOT_FOUND', '接口不存在')

        @router.put('/api/v1/me/role')
        def set_role(body: RoleBody, request: Request):
            if deployed:
                # 部署实例的演示须验证目标账号口令，不能在原会话内直接改授权。
                user = current_user(request)
                store.audit('platform', user.id, 'permission.denied', {'operation': 'auth.role'})
                raise AuthError(403, 'FORBIDDEN', '部署实例不能直接切换角色')
            with store._lock, store._db as db:
                store.begin_write()
                user = current_user(request)
                if user.id not in profiles:
                    raise AuthError(403, 'FORBIDDEN', '仅演示账号可切换角色')
                db.execute('delete from user_roles where user_id=?', (user.id,))
                db.execute('insert into user_roles values (?,?)', (user.id, body.role))
                store.audit('platform', user.id, 'auth.role', {'role': body.role}, connection=db)
                return session_document(directory.user(user.id))
    else:
        @router.put('/api/v1/me/role', include_in_schema=False)
        def role_unavailable():
            raise AuthError(404, 'NOT_FOUND', '接口不存在')

    # 复用 core 的管理读入口，权限失败在经开区边界写一次审计。
    administration = Administration(platform)
    admin = require_action('*', 'admin')

    @router.get('/api/admin/users', include_in_schema=False)
    @router.get('/api/v1/admin/users', include_in_schema=False)
    def users(q: str = '', dept: str = '', status: Literal['active', 'disabled'] = None, user=Depends(admin)):
        return administration.users(q, dept, status)

    # 两个路径入口共用一套校验，兼容层映射后也不得落回卫华的旧口令规则。
    routes = app.router.routes
    offset = len(routes)
    app.include_router(router)
    routes[:] = routes[offset:] + routes[:offset]

    @app.exception_handler(AuthError)
    async def auth_error(_request, error):
        return _error_response(error)

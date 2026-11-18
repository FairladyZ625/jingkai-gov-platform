"""口令登录、一次性首管引导与持久锁定；继续使用签名会话 cookie。"""
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone

import yaml
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import Field, model_validator
from starlette.middleware.sessions import SessionMiddleware

from .identity_http import Body, Identifier, IdentityError, IdentityRoute, Name, Password
from .passwords import hash_password, verify_password


def timestamp():
    return datetime.fromtimestamp(time.time(), timezone.utc).isoformat()


class PlatformSessions:
    """每次读取会话时长，避免并发请求改写共享 middleware 的 max_age。"""
    def __init__(self, app, directory, secret_key):
        self.app, self.directory, self.secret_key = app, directory, secret_key

    async def __call__(self, scope, receive, send):
        middleware = SessionMiddleware(self.app, secret_key=self.secret_key,
            session_cookie=os.environ.get('HAIKNOW_SESSION_COOKIE', 'haiknow_session'), same_site='lax',
            max_age=self.directory.settings()['sessionMinutes'] * 60)
        await middleware(scope, receive, send)


class BootstrapBody(Body):
    username: Identifier
    name: Name
    password: Password


class LoginBody(Body):
    username: Identifier | None = None
    password: str | None = Field(default=None, max_length=1024)
    user_id: Identifier | None = None

    @model_validator(mode='after')
    def credentials(self):
        if self.user_id is not None:
            if self.username is not None or self.password is not None:
                raise ValueError('一次只能使用一种登录方式')
        elif self.username is None or self.password is None:
            raise ValueError('请填写用户名和口令')
        return self


class PasswordBody(Body):
    old: str = Field(max_length=1024)
    new: Password


def install(app, plat, current_user):
    directory, store = plat.directory, plat.store
    demo = directory.demo_login
    router = APIRouter(prefix='/api/auth', route_class=IdentityRoute)

    @app.exception_handler(IdentityError)
    async def identity_error(request, error):
        return JSONResponse({'error': error.error}, status_code=error.status)

    @router.get('/state')
    def state():
        with store._lock:
            return {'needsBootstrap': not directory.has_admin(store._db), 'demoLogin': demo}

    @router.get('/users')
    def demo_users():
        if not demo:
            raise IdentityError(404, 'not_found', '演示登录未启用')
        with store._lock:
            names = directory.role_names()
            ids = [r[0] for r in store._db.execute("select id from users where demo=1 and status='active' order by rowid")]
            profiles = {}
            try:
                specs = yaml.safe_load((plat.config_dir / 'users.yaml').read_text(encoding='utf-8')) or {}
                profiles = {spec['id']: spec for spec in specs.get('users', [])}
            except (OSError, UnicodeError, yaml.YAMLError):
                pass
            apps = [entry.manifest for entry in plat.apps.values()]
            result = []
            for uid in ids:
                user = directory.user(uid)
                profile = profiles.get(uid, {})
                role_ids = directory.roles_of(uid)
                operate_apps = [dict(id=manifest['id'], name=manifest['name'], sector=manifest['sector'])
                                for manifest in apps if 'operate' in directory.actions(uid, manifest['id'])]
                approve_apps = [dict(id=manifest['id'], name=manifest['name'], sector=manifest['sector'])
                                for manifest in apps if 'approve' in directory.actions(uid, manifest['id'])]
                result.append(dict(
                    id=uid,
                    name=user.name,
                    position=profile.get('position') or (names.get(next(iter(sorted(role_ids)), ''), '')),
                    sector=profile.get('sector', 'other'),
                    roles=[names.get(role, role) for role in sorted(role_ids)],
                    operateApps=operate_apps,
                    approveApps=approve_apps,
                ))
            return result

    @router.post('/bootstrap')
    def bootstrap(body: BootstrapBody, request: Request):
        password = hash_password(body.password)
        with store._lock, store._db:
            db = store._db
            db.execute('begin immediate')
            if directory.has_admin(db):
                raise IdentityError(409, 'already_bootstrapped', '已存在管理员，请直接登录')
            uid = uuid.uuid4().hex
            try:
                db.execute('insert into users values (?,?,?,?,?,?,0,0,0,1,0)',
                           (uid, body.username, body.name, password, 'active', timestamp()))
            except sqlite3.IntegrityError as error:
                raise IdentityError(409, 'conflict', '用户名已存在') from error
            db.execute("insert or ignore into roles values ('admin','平台管理员',1)")
            db.execute("insert into user_roles values (?,'admin')", (uid,))
            db.executemany("insert or ignore into role_grants values ('admin','*',?)",
                           [(action,) for action in ('view', 'operate', 'approve', 'admin')])
            store.audit('platform', uid, 'auth.bootstrap', {'userId': uid}, connection=db)
        request.session.clear()
        request.session['uid'] = uid
        request.session['gen'] = directory.session_gen(uid)
        return {'ok': True}

    @router.post('/login')
    def login(body: LoginBody, request: Request):
        error = None
        with store._lock, store._db:
            db = store._db
            db.execute('begin immediate')
            row = db.execute('select id,password_hash,status,failed_logins,locked_until,demo from users where ' +
                             ('id=?' if body.user_id is not None else 'username=?'),
                             (body.user_id if body.user_id is not None else body.username,)).fetchone()
            uid = row[0] if row else 'anonymous'
            if body.user_id is not None and (not demo or not row or not row[5]):
                error = IdentityError(401, 'invalid_credentials', '用户名或口令不正确')
            elif not row or row[2] != 'active' or (row[5] and not demo):
                if body.password is not None:
                    hash_password(body.password)
                error = IdentityError(401, 'invalid_credentials', '用户名或口令不正确')
            elif row[4] > time.time():
                error = IdentityError(423, 'locked', '登录失败次数过多，请在 5 分钟后重试')
            elif body.user_id is None and not verify_password(body.password, row[1]):
                failures = (0 if row[4] else row[3]) + 1
                locked_until = time.time() + 300 if failures >= 5 else 0
                db.execute('update users set failed_logins=?,locked_until=? where id=?', (failures, locked_until, uid))
                error = IdentityError(423 if locked_until else 401, 'locked' if locked_until else 'invalid_credentials',
                                      '登录失败次数过多，请在 5 分钟后重试' if locked_until else '用户名或口令不正确')
            else:
                db.execute('update users set failed_logins=0,locked_until=0,last_login=? where id=?', (timestamp(), uid))
            store.audit('platform', uid, 'auth.login.failed' if error else 'login',
                        {'code': error.error['code']} if error else {}, connection=db)
        if error:
            raise error
        request.session.clear()
        request.session['uid'] = uid
        request.session['gen'] = directory.session_gen(uid)
        return {'ok': True}

    @router.post('/logout')
    def logout(request: Request):
        uid = request.session.get('uid')
        with store._lock, store._db:
            db = store._db
            db.execute('begin immediate')
            # 只对仍然有效的会话递增：被复制但已失效的 cookie 不能反复踢掉用户的其他会话。
            if uid and directory.session_user(uid, request.session.get('gen', 0)):
                directory.bump_session_gen(db, uid)
            store.audit('platform', uid or 'anonymous', 'logout', {}, connection=db)
        request.session.clear()
        return {'ok': True}

    @router.post('/password')
    def password(body: PasswordBody, request: Request, user=Depends(current_user)):
        with store._lock, store._db:
            db = store._db
            db.execute('begin immediate')
            stored = db.execute('select password_hash from users where id=?', (user.id,)).fetchone()[0]
            if not verify_password(body.old, stored):
                raise IdentityError(401, 'invalid_credentials', '原口令不正确')
            db.execute('update users set password_hash=?,failed_logins=0,locked_until=0 where id=?',
                       (hash_password(body.new), user.id))
            gen = directory.bump_session_gen(db, user.id)
            store.audit('platform', user.id, 'auth.password', {'userId': user.id}, connection=db)
        # 改密的这台设备继续用；其他设备持有的是旧代数，下一次请求即 401。
        request.session['gen'] = gen
        return {'ok': True}

    app.include_router(router)

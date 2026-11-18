"""用户、组织、授权、项目与平台设置；所有写入与 platform 留痕同事务。"""
from contextlib import contextmanager
import json
import sqlite3
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends

from .identity_http import IdentityError, IdentityRoute
from .identity_models import (
    DepartmentCreate, DepartmentPatch, Grants, GRANT_ACTIONS, Members, PositionCreate,
    PositionPatch, ProjectCreate, ResetPassword, RoleCreate, RolePatch, Settings, UserCreate, UserPatch,
    CrossProjectGrant,
)
from .passwords import hash_password

RELATIONS = {'departments': ('user_departments', 'department_id', 'departments'),
             'positions': ('user_positions', 'position_id', 'positions'),
             'roles': ('user_roles', 'role_id', 'roles')}


class Administration:
    def __init__(self, platform):
        self.platform, self.store, self.directory = platform, platform.store, platform.directory

    def admin(self, user):
        if 'admin' not in self.platform.rbac.actions(user, '*'):
            raise IdentityError(403, 'forbidden', '需要平台管理员权限')
        return user

    @contextmanager
    def write(self, user, action, detail, *, protect_admin=False):
        try:
            with self.store._lock, self.store._db:
                db = self.store._db
                db.execute('begin immediate')
                self.admin(user)
                yield db
                if protect_admin and not db.execute(
                    "select 1 from users u join user_roles r on u.id=r.user_id join role_grants g on r.role_id=g.role_id "
                    "where u.status='active' and g.app_id='*' and g.action='admin' limit 1"
                ).fetchone():
                    raise IdentityError(409, 'last_admin', '必须保留至少一个启用的管理员')
                self.store.audit('platform', user.id, action, detail, connection=db)
        except sqlite3.IntegrityError as error:
            raise IdentityError(409, 'conflict', '用户名或编号已存在') from error

    def require(self, db, table, ident):
        # 表名只来自模块内固定映射，用户输入一律作为参数绑定。
        if not db.execute(f'select 1 from {table} where id=?', (ident,)).fetchone():
            raise IdentityError(404, 'not_found', '资源不存在')

    def references(self, db, table, ids):
        if any(not db.execute(f'select 1 from {table} where id=?', (ident,)).fetchone() for ident in ids):
            raise IdentityError(400, 'invalid_request', '关联的用户、组织、角色或公司不存在')

    def relations(self, db, uid, body):
        for key, (table, column, target) in RELATIONS.items():
            if key in body:
                values = list(dict.fromkeys(body[key]))
                self.references(db, target, values)
                db.execute(f'delete from {table} where user_id=?', (uid,))
                db.executemany(f'insert into {table}(user_id,{column}) values (?,?)', [(uid, value) for value in values])

    def user_document(self, uid):
        db = self.store._db
        row = db.execute('select id,username,name,status,last_login from users where id=?', (uid,)).fetchone()
        doc = dict(zip(('id', 'username', 'name', 'status', 'lastLoginAt'), row))
        for key, (table, column, _) in RELATIONS.items():
            doc[key] = [r[0] for r in db.execute(f'select {column} from {table} where user_id=? order by rowid', (uid,))]
        scope = self.directory.project_ids(uid)
        doc['projects'] = [p for p in self.directory.projects() if '*' in scope or p in scope]
        return doc

    def users(self, q, dept, status):
        with self.store._lock:
            users = [self.user_document(r[0]) for r in self.store._db.execute('select id from users order by rowid')]
            return {'users': [u for u in users if (not q or q.casefold() in (u['username'] + ' ' + u['name']).casefold())
                             and (not dept or dept in u['departments']) and (not status or status == u['status'])]}

    def create_user(self, user, body):
        uid = uuid.uuid4().hex
        password = hash_password(body.password)
        with self.write(user, 'identity.user.create', {'userId': uid}) as db:
            db.execute('insert into users values (?,?,?,?,?,null,0,0,0,0,0)', (uid, body.username, body.name, password, 'active'))
            self.relations(db, uid, body.model_dump())
            return self.user_document(uid)

    def update_user(self, user, uid, body):
        value = body.model_dump(exclude_unset=True)
        with self.write(user, 'identity.user.update', {'userId': uid, 'fields': list(value)}, protect_admin=True) as db:
            self.require(db, 'users', uid)
            for field in ('name', 'status'):
                if field in value:
                    db.execute(f'update users set {field}=? where id=?', (value[field], uid))
            self.relations(db, uid, value)
            return self.user_document(uid)

    def reset_password(self, user, uid, password):
        encoded = hash_password(password)
        with self.write(user, 'identity.user.reset-password', {'userId': uid}) as db:
            self.require(db, 'users', uid)
            db.execute('update users set password_hash=?,failed_logins=0,locked_until=0 where id=?', (encoded, uid))
            # 重置后该用户在所有设备上的旧会话与路径令牌立即失效。
            self.directory.bump_session_gen(db, uid)
        return {'ok': True}

    def sign_out(self, user, uid):
        with self.write(user, 'identity.user.sign-out', {'userId': uid}) as db:
            self.require(db, 'users', uid)
            self.directory.bump_session_gen(db, uid)
        return {'ok': True}

    def org(self):
        with self.store._lock:
            db = self.store._db
            return {'company': self.directory.company(),
                    'departments': [dict(id=r[0], name=r[1], parentId=r[2]) for r in db.execute('select * from departments order by rowid')],
                    'positions': [dict(id=r[0], name=r[1], departmentId=r[2]) for r in db.execute('select * from positions order by rowid')]}

    def org_write(self, user, kind, ident, value, *, create=False):
        table, relation = ('departments', 'parent_id') if kind == 'department' else ('positions', 'department_id')
        parent_key = 'parentId' if kind == 'department' else 'departmentId'
        ident = ident or uuid.uuid4().hex
        with self.write(user, f'identity.{kind}.create' if create else f'identity.{kind}.update', {'id': ident}) as db:
            if not create:
                self.require(db, table, ident)
            parent = value.get(parent_key)
            if parent is not None:
                self.references(db, 'departments', [parent])
                if kind == 'department':
                    cursor = parent
                    while cursor is not None:
                        if cursor == ident:
                            raise IdentityError(409, 'org_cycle', '部门不能属于自身或下级部门')
                        cursor = db.execute('select parent_id from departments where id=?', (cursor,)).fetchone()[0]
            if create:
                db.execute(f'insert into {table} values (?,?,?)', (ident, value['name'], parent))
            else:
                for key, column in [('name', 'name'), (parent_key, relation)]:
                    if key in value:
                        db.execute(f'update {table} set {column}=? where id=?', (value[key], ident))
            row = db.execute(f'select * from {table} where id=?', (ident,)).fetchone()
            return dict(zip(('id', 'name', parent_key), row))

    def org_delete(self, user, kind, ident):
        table, members, column = ('departments', 'user_departments', 'department_id') if kind == 'department' else ('positions', 'user_positions', 'position_id')
        with self.write(user, f'identity.{kind}.delete', {'id': ident}) as db:
            self.require(db, table, ident)
            in_use = db.execute(f'select 1 from {members} where {column}=? limit 1', (ident,)).fetchone()
            if kind == 'department':
                in_use = in_use or db.execute('select 1 from departments where parent_id=?', (ident,)).fetchone() or db.execute(
                    'select 1 from positions where department_id=?', (ident,)).fetchone()
            if in_use:
                raise IdentityError(409, 'in_use', '仍有关联成员、下级部门或岗位，请先调整关联')
            db.execute(f'delete from {table} where id=?', (ident,))
        return {'ok': True}

    def roles(self):
        with self.store._lock:
            return {'roles': [dict(id=r[0], name=r[1], builtin=bool(r[2]), userCount=r[3]) for r in self.store._db.execute(
                'select r.id,r.name,r.builtin,count(u.user_id) from roles r left join user_roles u on u.role_id=r.id group by r.id order by r.rowid')]}

    def role_write(self, user, ident, name, *, create=False):
        with self.write(user, 'identity.role.create' if create else 'identity.role.update', {'roleId': ident}) as db:
            if create:
                db.execute('insert into roles values (?,?,0)', (ident, name))
            else:
                self.require(db, 'roles', ident)
                db.execute('update roles set name=? where id=?', (name, ident))
            return next(r for r in self.roles()['roles'] if r['id'] == ident)

    def role_delete(self, user, ident):
        with self.write(user, 'identity.role.delete', {'roleId': ident}, protect_admin=True) as db:
            self.require(db, 'roles', ident)
            if db.execute('select builtin from roles where id=?', (ident,)).fetchone()[0]:
                raise IdentityError(409, 'builtin_role', '内置角色不可删除')
            now = time.time()
            grants = db.execute(
                "select id,app_id,subject_field,subject_value,principal_id from cross_project_grants "
                "where principal_type='role' and principal_id=? and revoked_at is null",
                (ident,),
            ).fetchall()
            for grant_id, app_id, subject_field, subject_value, principal_id in grants:
                db.execute('update cross_project_grants set revoked_by=?,revoked_at=? where id=?',
                           (user.id, now, grant_id))
                self.store.audit('platform', user.id, 'cross_project.grant.revoke', {
                    'grantId': grant_id, 'appId': app_id, 'subjectField': subject_field,
                    'subjectValue': subject_value, 'principalType': 'role', 'principalId': principal_id,
                }, connection=db)
            db.execute('delete from user_roles where role_id=?', (ident,))
            db.execute('delete from role_grants where role_id=?', (ident,))
            db.execute('delete from roles where id=?', (ident,))
        return {'ok': True}

    def grants(self):
        with self.store._lock:
            grants = {role: {} for role in self.directory.role_names()}
            for role, app, action in self.store._db.execute('select role_id,app_id,action from role_grants'):
                grants[role].setdefault(app, []).append(action)
            for apps in grants.values():
                for app, actions in apps.items():
                    apps[app] = [action for action in GRANT_ACTIONS if action in actions]
            return {'actions': GRANT_ACTIONS, 'apps': [dict(id=e.manifest['id'], name=e.manifest['name']) for e in self.platform.apps.values()], 'grants': grants}

    def grant(self, user, role_id, app_id, actions):
        with self.write(user, 'identity.grant.update', {'roleId': role_id, 'appId': app_id, 'actions': actions}, protect_admin=True) as db:
            self.require(db, 'roles', role_id)
            if app_id != '*' and app_id not in self.platform.apps:
                raise IdentityError(404, 'not_found', '应用不存在')
            db.execute('delete from role_grants where role_id=? and app_id=?', (role_id, app_id))
            db.executemany('insert into role_grants values (?,?,?)',
                           [(role_id, app_id, action) for action in dict.fromkeys(actions)])
        return {'ok': True}

    def cross_project_grants(self):
        return self.platform.data.list_cross_grants()

    def cross_project_grant(self, user, body):
        self.admin(user)
        return self.platform.data.create_cross_grant(user, body.model_dump())

    def cross_project_revoke(self, user, grant_id):
        self.admin(user)
        return self.platform.data.revoke_cross_grant(user, grant_id)

    def projects(self):
        with self.store._lock:
            db = self.store._db
            return {'projects': [dict(id=p['id'], name=p['name'], members=[r[0] for r in db.execute(
                'select id from users where all_projects=1 or id in (select user_id from project_members where project_id=?) order by rowid', (p['id'],))])
                for p in self.directory.projects().values()]}

    def create_project(self, user, body):
        ident = body.id or uuid.uuid4().hex
        with self.write(user, 'identity.project.create', {'projectId': ident}) as db:
            company = body.companyId or self.directory.company()['id']
            self.references(db, 'companies', [company])
            self.references(db, 'users', body.members)
            products = [p.model_dump() for p in body.products]
            if len({p['id'] for p in products}) != len(products):
                raise IdentityError(400, 'invalid_request', '产品编号不能重复')
            db.execute('insert into projects values (?,?,?,?)', (ident, body.name, company, json.dumps(products, ensure_ascii=False)))
            db.executemany('insert into project_members values (?,?)', [(ident, uid) for uid in dict.fromkeys(body.members)])
            return next(p for p in self.projects()['projects'] if p['id'] == ident)

    def members(self, user, ident, members):
        with self.write(user, 'identity.project.members', {'projectId': ident, 'members': members}) as db:
            self.require(db, 'projects', ident)
            self.references(db, 'users', members)
            # 旧种子的 * 在首次被排除时展开成显式成员，保证 PUT 真正替换当前项目范围。
            global_users = [r[0] for r in db.execute('select id from users where all_projects=1') if r[0] not in members]
            for uid in global_users:
                db.executemany('insert or ignore into project_members values (?,?)', [(pid, uid) for pid in self.directory.projects()])
                db.execute('update users set all_projects=0 where id=?', (uid,))
            db.execute('delete from project_members where project_id=?', (ident,))
            db.executemany('insert into project_members values (?,?)', [(ident, uid) for uid in dict.fromkeys(members)])
            return next(p for p in self.projects()['projects'] if p['id'] == ident)

    def settings(self, user, body):
        value = body.model_dump(exclude_unset=True)
        with self.write(user, 'identity.settings.update', {'fields': list(value)}) as db:
            db.executemany('update settings set value=? where key=?', [(json.dumps(v, ensure_ascii=False), k) for k, v in value.items()])
            return self.directory.settings()


def install(app, platform, current_user):
    service = Administration(platform)
    router = APIRouter(prefix='/api/admin', route_class=IdentityRoute)

    def admin(user=Depends(current_user)):
        return service.admin(user)

    @router.get('/users')
    def users(q: str = '', dept: str = '', status: Literal['active', 'disabled'] | None = None, user=Depends(admin)):
        return service.users(q, dept, status)

    @router.post('/users', status_code=201)
    def create_user(body: UserCreate, user=Depends(admin)):
        return service.create_user(user, body)

    @router.patch('/users/{ident}')
    def update_user(ident: str, body: UserPatch, user=Depends(admin)):
        return service.update_user(user, ident, body)

    @router.post('/users/{ident}/reset-password')
    def reset_password(ident: str, body: ResetPassword, user=Depends(admin)):
        return service.reset_password(user, ident, body.password)

    @router.post('/users/{ident}/sign-out')
    def sign_out(ident: str, user=Depends(admin)):
        return service.sign_out(user, ident)

    @router.get('/org')
    def org(user=Depends(admin)):
        return service.org()

    @router.post('/org/departments', status_code=201)
    def department_create(body: DepartmentCreate, user=Depends(admin)):
        return service.org_write(user, 'department', body.id, body.model_dump(), create=True)

    @router.patch('/org/departments/{ident}')
    def department_update(ident: str, body: DepartmentPatch, user=Depends(admin)):
        return service.org_write(user, 'department', ident, body.model_dump(exclude_unset=True))

    @router.delete('/org/departments/{ident}')
    def department_delete(ident: str, user=Depends(admin)):
        return service.org_delete(user, 'department', ident)

    @router.post('/org/positions', status_code=201)
    def position_create(body: PositionCreate, user=Depends(admin)):
        return service.org_write(user, 'position', body.id, body.model_dump(), create=True)

    @router.patch('/org/positions/{ident}')
    def position_update(ident: str, body: PositionPatch, user=Depends(admin)):
        return service.org_write(user, 'position', ident, body.model_dump(exclude_unset=True))

    @router.delete('/org/positions/{ident}')
    def position_delete(ident: str, user=Depends(admin)):
        return service.org_delete(user, 'position', ident)

    @router.get('/roles')
    def roles(user=Depends(admin)):
        return service.roles()

    @router.post('/roles', status_code=201)
    def role_create(body: RoleCreate, user=Depends(admin)):
        return service.role_write(user, body.id, body.name, create=True)

    @router.patch('/roles/{ident}')
    def role_update(ident: str, body: RolePatch, user=Depends(admin)):
        return service.role_write(user, ident, body.name)

    @router.delete('/roles/{ident}')
    def role_delete(ident: str, user=Depends(admin)):
        return service.role_delete(user, ident)

    @router.get('/grants')
    def grants(user=Depends(admin)):
        return service.grants()

    @router.put('/grants/{role_id}/{app_id}')
    def grant(role_id: str, app_id: str, body: Grants, user=Depends(admin)):
        return service.grant(user, role_id, app_id, body.actions)

    @router.get('/cross-project-grants')
    def cross_project_grants(user=Depends(admin)):
        return service.cross_project_grants()

    @router.post('/cross-project-grants', status_code=201)
    def cross_project_grant(body: CrossProjectGrant, user=Depends(admin)):
        return service.cross_project_grant(user, body)

    @router.delete('/cross-project-grants/{grant_id}')
    def cross_project_revoke(grant_id: str, user=Depends(admin)):
        return service.cross_project_revoke(user, grant_id)

    @router.get('/projects')
    def projects(user=Depends(admin)):
        return service.projects()

    @router.post('/projects', status_code=201)
    def project_create(body: ProjectCreate, user=Depends(admin)):
        return service.create_project(user, body)

    @router.put('/projects/{ident}/members')
    def members(ident: str, body: Members, user=Depends(admin)):
        return service.members(user, ident, body.members)

    @router.get('/settings')
    def settings(user=Depends(admin)):
        return platform.directory.settings()

    @router.put('/settings')
    def settings_update(body: Settings, user=Depends(admin)):
        return service.settings(user, body)

    app.include_router(router)

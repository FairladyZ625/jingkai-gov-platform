"""经开区用户与部门。组织关系和授权均保存在核心身份表中。"""
import secrets
from typing import Annotated, Literal
from uuid import uuid4

import yaml
from fastapi import Depends, Request
from pydantic import AliasChoices, Field

from haiknow_core.identity_http import Body, Identifier, Name
from haiknow_core.passwords import hash_password
from jkq.auth import AuthError, RoleId

from .common import record_change, write


Password = Annotated[str, Field(min_length=6, max_length=1024)]
Title = Annotated[str, Field(max_length=100)]
Status = Literal['active', 'disabled']


class UserCreate(Body):
    username: Identifier
    name: Name
    role: RoleId = 'member'
    deptId: Identifier | None = None
    title: Title = ''
    password: Password = None


class UserPatch(Body):
    name: Name = None
    role: RoleId = None
    status: Status = None
    deptId: Identifier | None = None
    title: Title = None
    resetPassword: Password | bool = None


class DepartmentCreate(Body):
    name: Name
    parent: Identifier | None = Field(default=None, validation_alias=AliasChoices('parent', 'parentId'))


class Rename(Body):
    name: Name


def _set_title(db, uid, title):
    db.execute('delete from user_positions where user_id=?', (uid,))
    if title:
        row = db.execute('select id from positions where name=? and department_id is null order by rowid limit 1',
                         (title,)).fetchone()
        pid = row[0] if row else uuid4().hex
        if not row:
            db.execute('insert into positions values (?,?,null)', (pid, title))
        db.execute('insert into user_positions values (?,?)', (uid, pid))


def _seed_org(platform):
    if not platform.directory.demo_login:
        return
    profiles = yaml.safe_load((platform.config_dir / 'users.yaml').read_text())['demoUsers']
    with platform.store._lock, platform.store._db as db:
        platform.store.begin_write()
        if not db.execute("insert or ignore into settings values ('jkq.admin.seedOrg.v1','true')").rowcount:
            return
        # 组织层级沿用演示配置；已有核心关联优先，包括多部门和多岗位。
        for did, name, parent in (
            ('d-root', '北京经开区管委会', None), ('d-ext', '外部协作单位', None),
            ('d-cyc', '产业促进局', 'd-root'),
        ):
            db.execute('insert or ignore into departments values (?,?,?)', (did, name, parent))
        for profile in profiles:
            uid, did = profile['id'], profile['deptId']
            parent = {'d-yzsk': 'd-ext', 'd-qyfw': 'd-cyc'}.get(did, 'd-root')
            db.execute('insert or ignore into departments values (?,?,?)',
                       (did, profile['dept'].split(' · ')[-1], parent))
            db.execute('insert into user_departments select ?,? where not exists '
                       '(select 1 from user_departments where user_id=?)', (uid, did, uid))
            if not db.execute('select 1 from user_positions where user_id=?', (uid,)).fetchone():
                _set_title(db, uid, profile['title'])


def _department(db, did):
    row = db.execute('select id,name,parent_id from departments where id=?', (did,)).fetchone()
    if not row:
        raise AuthError(404, 'NOT_FOUND', '部门不存在')
    return dict(zip(('id', 'name', 'parent'), row))


def _users(db, demo, *, uid='', q='', dept='', role='', status=None):
    # 列表展示主关系，筛选按全部关联判断，保留核心已有的多部门/多角色账号。
    sql = """
        select u.id,u.username,u.name,u.status,u.last_login,
          (select d.department_id from user_departments d where d.user_id=u.id order by rowid limit 1),
          (select p.name from positions p join user_positions x on x.position_id=p.id
             where x.user_id=u.id order by x.rowid limit 1),
          (select r.role_id from user_roles r where r.user_id=u.id order by
             case r.role_id when 'admin' then 0 when 'leader' then 1 when 'member' then 2
             when 'partner' then 3 else 4 end, r.rowid limit 1)
        from users u where (u.demo=0 or :demo) and (:uid='' or u.id=:uid)
          and (:status is null or u.status=:status)
          and (:dept='' or exists(select 1 from user_departments where user_id=u.id and department_id=:dept))
          and (:role='' or exists(select 1 from user_roles where user_id=u.id and role_id=:role))
        order by u.rowid
    """
    names = dict(db.execute('select id,name from departments'))
    result = []
    for ident, username, name, state, login, did, title, primary_role in db.execute(
        sql, dict(demo=demo, uid=uid, status=status, dept=dept, role=role)
    ):
        if q.casefold() in (username + ' ' + name).casefold():
            result.append(dict(id=ident, username=username, name=name, status=state, lastLogin=login,
                               deptId=did, dept=names.get(did, ''), title=title or '', role=primary_role))
    return result


def _assign(db, uid, values):
    if 'role' in values:
        role = values['role']
        if not db.execute('select 1 from roles where id=?', (role,)).fetchone():
            raise AuthError(400, 'INVALID_REQUEST', '角色不存在')
        db.execute('delete from user_roles where user_id=?', (uid,))
        db.execute('insert into user_roles values (?,?)', (uid, role))
    if 'deptId' in values:
        did = values['deptId']
        db.execute('delete from user_departments where user_id=?', (uid,))
        if did:
            _department(db, did)
            db.execute('insert into user_departments values (?,?)', (uid, did))
    if 'title' in values:
        _set_title(db, uid, values['title'])


def register(router, platform, admin):
    _seed_org(platform)
    store, directory = platform.store, platform.directory
    users = '/api/v1/admin/users'
    departments = '/api/v1/admin/departments'

    def item(db, uid):
        rows = _users(db, directory.demo_login, uid=uid)
        if not rows:
            raise AuthError(404, 'NOT_FOUND', '用户不存在')
        return rows[0]

    @router.get(users)
    def list_users(q: str = '', dept: str = '', role: str = '', status: Status = None, user=Depends(admin)):
        with store._lock:
            return {'items': _users(store._db, directory.demo_login, q=q, dept=dept, role=role, status=status)}

    @router.post(users)
    def create_user(body: UserCreate, request: Request, user=Depends(admin)):
        uid = uuid4().hex
        with write(platform, user) as db:
            if db.execute('select 1 from users where username=?', (body.username,)).fetchone():
                raise AuthError(409, 'DUPLICATE', '用户名已存在')
            db.execute("insert into users(id,username,name,password_hash,status,failed_logins,locked_until,"
                       "demo,all_projects,session_gen) values (?,?,?,?,'active',0,0,0,0,0)",
                       (uid, body.username, body.name, hash_password(body.password or secrets.token_urlsafe(32))))
            _assign(db, uid, body.model_dump())
            after = item(db, uid)
            record_change(platform, db, user, request, action='identity.user.create', target=uid,
                          before=None, after=after)
        return {'item': after}

    @router.patch(users + '/{uid}')
    def patch_user(uid: str, body: UserPatch, request: Request, user=Depends(admin)):
        values = body.model_dump(exclude_unset=True)
        with write(platform, user) as db:
            before = item(db, uid)
            for field in ('status', 'name'):
                if field in values:
                    db.execute(f'update users set {field}=? where id=?', (values[field], uid))
            _assign(db, uid, values)
            if ('role' in values or 'status' in values) and not directory.has_admin(db, active_only=True):
                raise AuthError(400, 'LAST_ADMIN', '必须保留至少一位启用的管理员')
            if body.resetPassword:
                password = body.resetPassword if isinstance(body.resetPassword, str) else secrets.token_urlsafe(32)
                db.execute('update users set password_hash=?,failed_logins=0,locked_until=0 where id=?',
                           (hash_password(password), uid))
            if body.resetPassword or (body.status == 'disabled' and before['status'] == 'active'):
                directory.bump_session_gen(db, uid)
            after = item(db, uid)
            record_change(platform, db, user, request, action='identity.user.update', target=uid,
                          before=before, after=after)
        return {'item': after}

    @router.get(departments)
    def list_departments(user=Depends(admin)):
        with store._lock:
            rows = store._db.execute('select id,name,parent_id from departments order by rowid')
            return {'items': [dict(id=did, name=name, parent=parent) for did, name, parent in rows]}

    @router.post(departments)
    def create_department(body: DepartmentCreate, request: Request, user=Depends(admin)):
        did = uuid4().hex
        with write(platform, user) as db:
            if body.parent:
                _department(db, body.parent)
            db.execute('insert into departments values (?,?,?)', (did, body.name, body.parent))
            after = _department(db, did)
            record_change(platform, db, user, request, action='identity.department.create', target=did,
                          before=None, after=after)
        return {'item': after}

    @router.patch(departments + '/{did}')
    def rename_department(did: str, body: Rename, request: Request, user=Depends(admin)):
        with write(platform, user) as db:
            before = _department(db, did)
            db.execute('update departments set name=? where id=?', (body.name, did))
            after = _department(db, did)
            record_change(platform, db, user, request, action='identity.department.update', target=did,
                          before=before, after=after)
        return {'item': after}

    @router.delete(departments + '/{did}')
    def delete_department(did: str, request: Request, user=Depends(admin)):
        with write(platform, user) as db:
            before = _department(db, did)
            if db.execute('select 1 from user_departments where department_id=? union all '
                          'select 1 from departments where parent_id=? union all '
                          'select 1 from positions where department_id=? limit 1', (did, did, did)).fetchone():
                raise AuthError(409, 'NOT_EMPTY', '部门仍有成员、下级部门或岗位')
            db.execute('delete from departments where id=?', (did,))
            record_change(platform, db, user, request, action='identity.department.delete', target=did,
                          before=before, after=None)
        return {'ok': True}

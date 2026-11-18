"""数据库身份目录；yaml 只作一次性种子，读路径不缓存授权。"""
from __future__ import annotations

import json

import yaml

from haiknow_sdk import ACTIONS, User
from .passwords import hash_password

DEFAULT_SETTINGS = {'platformName': 'HAiKnow 小应用接入平台', 'defaultHome': '#/home',
                    'sessionMinutes': 20160}


class Directory:
    def __init__(self, store, *, demo_login=False):
        self.store = store
        self.demo_login = demo_login

    def has_admin(self, db, *, active_only=False):
        return db.execute(
            "select 1 from users u join user_roles r on u.id=r.user_id "
            "join role_grants g on r.role_id=g.role_id "
            "where g.app_id='*' and g.action='admin' and (u.demo=0 or ?) "
            "and (not ? or u.status='active') limit 1",
            (self.demo_login, active_only),
        ).fetchone() is not None

    @staticmethod
    def _yaml(path):
        """配置损坏时保留已初始化库可启动；下一次修复配置后继续补齐。"""
        try:
            return yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            return {}

    def _seed_demo(self, db, config_dir, roles):
        """只补缺失演示身份；同 id 的已有身份完全由数据库接管。"""
        users = self._yaml(config_dir / 'users.yaml').get('users', [])
        missing_users = [user for user in users
                         if not db.execute('select 1 from users where id=?', (user['id'],)).fetchone()]
        demo_role_ids = {role for user in missing_users for role in user.get('roles', [])}
        for role in demo_role_ids:
            spec = roles.get('roles', {}).get(role, {})
            db.execute('insert or ignore into roles values (?,?,1)', (role, spec.get('name', role)))
            for app_id, actions in (spec.get('grants') or {}).items():
                db.executemany('insert or ignore into role_grants values (?,?,?)',
                               [(role, app_id, action) for action in set(actions) if action in ACTIONS])
        # 演示账号共用公开口令 demo1234；scrypt 每次约 50ms，只算一次，避免每次启动按账号数线性变慢。
        demo_hash = hash_password('demo1234') if missing_users else None
        for user in missing_users:
            uid = user['id']
            db.execute('insert into users values (?,?,?,?,?,null,0,0,1,?,0)',
                       (uid, user.get('username', uid), user.get('name', uid),
                        demo_hash, 'active', int('*' in user.get('projects', []))))
            for role in user.get('roles', []):
                db.execute('insert or ignore into roles values (?,?,1)',
                           (role, roles.get('roles', {}).get(role, {}).get('name', role)))
                db.execute('insert or ignore into user_roles values (?,?)', (uid, role))
            for project in user.get('projects', []):
                if project != '*':
                    db.execute('insert or ignore into project_members values (?,?)', (project, uid))

    def seed(self, config_dir, manifests, *, demo):
        with self.store._lock:
            db = self.store._db
            db.execute('begin immediate')
            try:
                initial = db.execute("select 1 from settings where key='identity.seeded'").fetchone() is None
                roles = self._yaml(config_dir / 'roles.yaml') if (initial or demo) else {}
                if initial:
                    projects = self._yaml(config_dir / 'projects.yaml')
                    for role, spec in roles.get('roles', {}).items():
                        db.execute('insert into roles values (?,?,1)', (role, spec.get('name', role)))
                    db.execute("insert or ignore into roles values ('admin','平台管理员',1)")
                    for company in projects.get('companies', []):
                        db.execute('insert into companies values (?,?)', (company['id'], company['name']))
                        for project in company['projects']:
                            db.execute('insert into projects values (?,?,?,?)',
                                       (project['id'], project['name'], company['id'], json.dumps(project.get('products', []))))
                    if not projects.get('companies'):
                        db.execute("insert into companies values ('company','演示公司')")
                    for key, value in DEFAULT_SETTINGS.items():
                        db.execute('insert into settings values (?,?)', (key, json.dumps(value, ensure_ascii=False)))
                    db.execute("insert into settings values ('identity.seeded','true')")
                if demo:
                    self._seed_demo(db, config_dir, roles)
                for manifest in manifests:
                    app_id = manifest['id']
                    if db.execute('select 1 from identity_apps where app_id=?', (app_id,)).fetchone():
                        continue
                    for role, actions in (manifest.get('defaultRoles') or {}).items():
                        db.execute('insert or ignore into roles values (?,?,0)', (role, role))
                        db.executemany('insert or ignore into role_grants values (?,?,?)',
                                       [(role, app_id, action) for action in actions if action in ACTIONS])
                    db.execute('insert into identity_apps values (?)', (app_id,))
                if initial:
                    # 初始 yaml 覆盖清单默认授权，此后不再读取配置文件。
                    for role, spec in roles.get('roles', {}).items():
                        for app_id, actions in spec.get('grants', {}).items():
                            db.execute('delete from role_grants where role_id=? and app_id=?', (role, app_id))
                            db.executemany('insert into role_grants values (?,?,?)',
                                           [(role, app_id, action) for action in set(actions) if action in ACTIONS])
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def departments_of(self, user_id) -> frozenset[str]:
        with self.store._lock:
            return frozenset(r[0] for r in self.store._db.execute(
                'select department_id from user_departments where user_id=?', (user_id,)))

    def roles_of(self, user_id) -> frozenset[str]:
        with self.store._lock:
            return frozenset(r[0] for r in self.store._db.execute(
                'select role_id from user_roles where user_id=?', (user_id,)))

    def project_ids(self, user_id) -> tuple[str, ...]:
        with self.store._lock:
            db = self.store._db
            row = db.execute('select all_projects from users where id=?', (user_id,)).fetchone()
            if row and row[0]:
                return ('*',)
            return tuple(r[0] for r in db.execute('select project_id from project_members where user_id=? order by rowid', (user_id,)))

    def user(self, user_id) -> User | None:
        with self.store._lock:
            row = self.store._db.execute("select id,name from users where id=? and status='active'", (user_id,)).fetchone()
            return User(row[0], row[1], tuple(sorted(self.roles_of(user_id))), self.project_ids(user_id)) if row else None

    def session_gen(self, user_id) -> int:
        """当前会话代数；上线前签发的旧行没有值，按 0 处理。"""
        with self.store._lock:
            row = self.store._db.execute('select coalesce(session_gen,0) from users where id=?', (user_id,)).fetchone()
        return row[0] if row else 0

    def session_user(self, user_id, generation) -> User | None:
        with self.store._lock:
            eligible = self.store._db.execute(
                'select 1 from users where id=? and coalesce(session_gen,0)=? and (demo=0 or ?)',
                (user_id, generation, self.demo_login),
            ).fetchone()
            return self.user(user_id) if eligible else None

    def bump_session_gen(self, db, user_id) -> int:
        """在调用方事务内递增并返回新代数；登出、改密与强制下线共用。"""
        db.execute('update users set session_gen=coalesce(session_gen,0)+1 where id=?', (user_id,))
        row = db.execute('select coalesce(session_gen,0) from users where id=?', (user_id,)).fetchone()
        return row[0] if row else 0

    def users(self) -> dict[str, User]:
        with self.store._lock:
            ids = [r[0] for r in self.store._db.execute("select id from users where status='active' order by rowid")]
            return {uid: self.user(uid) for uid in ids}

    def role_names(self):
        with self.store._lock:
            return dict(self.store._db.execute('select id,name from roles'))

    def actions(self, user_id, app_id):
        with self.store._lock:
            return frozenset(r[0] for r in self.store._db.execute(
                "select distinct g.action from role_grants g join user_roles r on r.role_id=g.role_id "
                "join users u on u.id=r.user_id where u.id=? and u.status='active' and g.app_id in ('*',?)", (user_id, app_id)))

    def company(self):
        with self.store._lock:
            row = self.store._db.execute('select id,name from companies order by rowid limit 1').fetchone()
            return dict(id=row[0], name=row[1])

    def projects(self):
        with self.store._lock:
            return {r[0]: dict(id=r[0], name=r[1], company=r[2], products=json.loads(r[3]))
                    for r in self.store._db.execute('select id,name,company_id,products from projects order by rowid')}

    def companies(self):
        with self.store._lock:
            projects = self.projects().values()
            return [dict(id=r[0], name=r[1], projects=[{k: v for k, v in p.items() if k != 'company'}
                        for p in projects if p['company'] == r[0]])
                    for r in self.store._db.execute('select id,name from companies order by rowid')]

    def settings(self):
        with self.store._lock:
            return {k: json.loads(v) for k, v in self.store._db.execute('select key,value from settings') if k in DEFAULT_SETTINGS}

    def profile(self, user):
        with self.store._lock:
            db = self.store._db
            username = db.execute('select username from users where id=?', (user.id,)).fetchone()[0]
            departments = [dict(id=r[0], name=r[1]) for r in db.execute(
                'select d.id,d.name from departments d join user_departments u on u.department_id=d.id where u.user_id=?', (user.id,))]
            positions = [dict(id=r[0], name=r[1]) for r in db.execute(
                'select p.id,p.name from positions p join user_positions u on u.position_id=p.id where u.user_id=?', (user.id,))]
            scope = self.project_ids(user.id)
            projects = [dict(id=p['id'], name=p['name']) for p in self.projects().values() if '*' in scope or p['id'] in scope]
            return dict(username=username, departments=departments, positions=positions, projects=projects)

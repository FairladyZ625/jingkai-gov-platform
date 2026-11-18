"""补齐经开区内建角色和演示账号，复用卫华身份表与口令哈希。"""

import os
import secrets
import sys

from haiknow_core.passwords import hash_password
from haiknow_sdk import ACTIONS


def seed_identities(store, roles, users):
    generated = []
    with store._lock, store._db as db:
        store.begin_write()
        for role, spec in roles.items():
            inserted = db.execute(
                'insert into roles values (?,?,1) on conflict(id) do nothing', (role, spec['name']),
            )
            if inserted.rowcount:
                db.executemany('insert into role_grants values (?,?,?)', (
                    (role, app_id, action)
                    for app_id, actions in spec['grants'].items()
                    for action in set(actions) if action in ACTIONS
                ))

        for user in users:
            existing = db.execute(
                'select demo, username from users where id=?', (user['id'],)
            ).fetchone()
            if existing:
                if existing != (1, user['username']):
                    raise RuntimeError(f"演示账号编号冲突：{user['id']}")
                continue

            name = user['passwordEnv']
            password = os.environ.get(name)
            if password is None:
                if not sys.stderr.isatty():
                    raise RuntimeError(f"无终端可显示首次生成的演示口令，请设置 {name}")
                password = secrets.token_urlsafe(18)
                generated.append((user['username'], password))
            if not 6 <= len(password) <= 1024:
                raise RuntimeError(f"{name} 的口令长度须为 6 至 1024 位")

            db.execute(
                'insert into users (id,username,name,password_hash,status,last_login,'
                'failed_logins,locked_until,demo,all_projects,session_gen) '
                "values (?,?,?,?,'active',null,0,0,1,1,0)",
                (user['id'], user['username'], user['name'], hash_password(password)),
            )
            db.execute('insert into user_roles values (?,?)', (user['id'], user['role']))

        # 输出及刷新成功后才提交。中断时回滚，下一次启动可重新生成或使用环境变量。
        for username, password in generated:
            print(f"经开区演示账号 {username} 的首次口令：{password}", file=sys.stderr, flush=True)

"""项目成员可见的团队动态。事件生产者在自己的业务事务内写入 jkq_feed。"""
import time
import uuid
from datetime import datetime, timedelta, timezone


def ensure_table(db):
    db.execute("""create table if not exists jkq_feed (
        id text primary key, project text not null, title text not null, at real not null)""")


def publish(db, project, title, *, at=None, ident=None):
    """业务模块在自己的事务里写一条项目团队动态（#28/#34 等生产方使用）。"""
    ensure_table(db)
    ident = ident or uuid.uuid4().hex
    db.execute('insert into jkq_feed(id, project, title, at) values (?,?,?,?)',
               (ident, project, title, time.time() if at is None else at))
    return ident


def local_time(timestamp):
    return datetime.fromtimestamp(timestamp, timezone(timedelta(hours=8))).isoformat()


def feed_page(db, projects, limit, offset):
    # 项目范围来自当前会话，通配成员可见所有团队动态。
    where = '' if '*' in projects else ' where project in (' + ','.join('?' for _ in projects) + ')'
    args = () if '*' in projects else tuple(projects)
    total, = db.execute('select count(*) from jkq_feed' + where, args).fetchone()
    rows = db.execute('select id, project, title, at from jkq_feed' + where
                      + ' order by at desc, id desc limit ? offset ?', (*args, limit, offset))
    return {'items': [dict(id=i, project=p, title=t, at=local_time(at)) for i, p, t, at in rows],
            'total': total}

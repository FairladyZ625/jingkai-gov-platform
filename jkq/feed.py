"""项目成员可见的团队动态。事件生产者在自己的业务事务内写入 jkq_feed。"""
from datetime import datetime, timedelta, timezone


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

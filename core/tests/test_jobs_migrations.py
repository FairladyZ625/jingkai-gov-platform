"""长任务表由迁移 4 创建；保留 v3 数据、升级前备份与同版本启动。"""
import json
import sqlite3

from haiknow_core.migrations import MIGRATIONS
from haiknow_core.store import Store


def test_v3_upgrade_adds_job_tables_and_preserves_old_data(tmp_path):
    with sqlite3.connect(tmp_path / 'platform.db') as db:
        for _, sql in MIGRATIONS[:3]:
            db.executescript(sql)
        db.execute('create table schema_versions(version integer primary key, applied_at real not null)')
        db.executemany('insert into schema_versions values (?,0)', [(1,), (2,), (3,)])
        db.execute('insert into kv values (?,?,?,?)', ('demo', 'saved', json.dumps({'value': 19}), 1))
        db.execute('insert into external_sources values (?,?,?)', ('source', '{}', b''))
        db.execute('insert into app_control values (?,?)', ('demo', 0))
    store = Store(tmp_path)
    assert store._db.execute('select version from schema_versions order by version').fetchall() == [(v,) for v in range(1, len(MIGRATIONS) + 1)]
    tables = {r[0] for r in store._db.execute("select name from sqlite_master where type='table'")}
    assert {'v1_jobs', 'v1_job_notifications'} <= tables
    assert store.kv_get('demo', 'saved') == {'value': 19}
    assert store._db.execute('select id from external_sources').fetchall() == [('source',)]
    assert not store.app_enabled('demo')
    backups = list((tmp_path / 'backups').glob('*-3.db'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute('select max(version) from schema_versions').fetchone() == (3,)
        assert backup.execute("select name from sqlite_master where name='v1_jobs'").fetchall() == []
        assert backup.execute('select value from kv').fetchone() == ('{"value": 19}',)
    Store(tmp_path)
    assert len(list((tmp_path / 'backups').glob('*.db'))) == 1


def test_job_service_initialization_does_not_execute_ddl(make_client):
    from haiknow_core.jobs.service import JobService
    c = make_client()
    store = c.app.state.platform.store
    statements = []
    store._db.set_trace_callback(statements.append)
    try:
        JobService(c.app.state.platform, c.app)
    finally:
        store._db.set_trace_callback(None)
    assert not any(s.lstrip().lower().startswith(('create ', 'alter ', 'drop ')) for s in statements), statements

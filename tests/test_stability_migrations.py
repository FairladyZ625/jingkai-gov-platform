"""升级先备份，迁移失败原子回滚；禁止破坏旧 schema/数据。"""
import sqlite3

import pytest

from haiknow_core.store import Store
from haiknow_core.migrations import MIGRATIONS

CURRENT = len(MIGRATIONS)
_ALL_MIGRATIONS = MIGRATIONS


def test_legacy_database_is_backed_up_before_upgrade(tmp_path):
    dbfile = tmp_path / 'platform.db'
    with sqlite3.connect(dbfile) as db:
        db.executescript('create table kv(app_id text not null,key text not null,value text not null,updated real not null,primary key(app_id,key));')
        db.execute('insert into kv values (?,?,?,?)', ('sample', 'old', '{"value":1}', 1))
    store = Store(tmp_path)
    assert store.kv_get('sample', 'old') == {'value': 1}
    versions = store._db.execute('select version from schema_versions order by version').fetchall()
    assert versions == [(v,) for v in range(1, CURRENT + 1)]
    backups = list((tmp_path / 'backups').glob('*-0.db'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute('select value from kv').fetchone() == ('{"value":1}',)
        assert db.execute("select name from sqlite_master where name='schema_versions'").fetchall() == []
    Store(tmp_path)
    assert len(list((tmp_path / 'backups').glob('*.db'))) == 1


def test_new_database_and_standalone_ai_settings_use_same_version(tmp_path):
    from haiknow_core.settings import AISettings
    settings = AISettings(tmp_path)
    store = Store(tmp_path)
    assert not (tmp_path / 'backups').exists()
    assert settings._db.execute('select max(version) from schema_versions').fetchone() == (CURRENT,)
    assert store._db.execute('select max(version) from schema_versions').fetchone() == (CURRENT,)


def test_nullable_column_upgrade_is_additive(tmp_path, monkeypatch):
    from haiknow_core import migrations
    Store(tmp_path).kv_put('sample', 'old', 1)
    monkeypatch.setattr(migrations, 'MIGRATIONS', (*migrations.MIGRATIONS, (CURRENT + 1, 'alter table kv add column note text;')))
    store = Store(tmp_path)
    assert store.kv_get('sample', 'old') == 1
    assert store._db.execute('select note from kv').fetchone() == (None,)
    assert len(list((tmp_path / 'backups').glob(f'*-{CURRENT}.db'))) == 1


@pytest.mark.parametrize('sql', [
    'drop table kv;', 'delete from kv;', "update kv set value='2';",
    'alter table kv rename to old_kv;', 'alter table kv drop column value;',
    'alter table kv add column required text not null default "x";',
    'alter table kv add column defaulted text default "x";',
    'create trigger wipe after insert on kv begin delete from kv; end;',
    'create unique index kv_unique on kv(value);',
])
def test_destructive_migration_rejected_without_changing_data(tmp_path, monkeypatch, sql):
    from haiknow_core import migrations
    Store(tmp_path).kv_put('sample', 'old', 1)
    monkeypatch.setattr(migrations, 'MIGRATIONS', (*migrations.MIGRATIONS, (CURRENT + 1, sql)))
    with pytest.raises(RuntimeError, match='数据库升级失败'):
        Store(tmp_path)
    with sqlite3.connect(tmp_path / 'platform.db') as db:
        assert db.execute('select value from kv').fetchone() == ('1',)
        assert db.execute('select max(version) from schema_versions').fetchone() == (CURRENT,)


def test_failed_migration_rolls_back_all_steps_and_refuses_platform_start(tmp_path, monkeypatch):
    from haiknow_core import migrations
    from haiknow_core.main import create_app
    from conftest import ROOT
    store = Store(tmp_path)
    store.kv_put('sample', 'old', 1)
    sql = 'create table added (id text); create table invalid(id text, id text);'
    monkeypatch.setattr(migrations, 'MIGRATIONS', (*migrations.MIGRATIONS, (CURRENT + 1, sql)))
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path))
    with pytest.raises(RuntimeError, match='数据库升级失败.*拒绝启动'):
        create_app(ROOT)
    with sqlite3.connect(tmp_path / 'platform.db') as db:
        assert db.execute("select name from sqlite_master where name='added'").fetchall() == []
        assert db.execute('select max(version) from schema_versions').fetchone() == (CURRENT,)
    backup = next((tmp_path / 'backups').glob(f'*-{CURRENT}.db'))
    with sqlite3.connect(backup) as db:
        assert db.execute('select value from kv').fetchone() == ('1',)


def test_backup_failure_prevents_any_schema_change(tmp_path, monkeypatch):
    from haiknow_core import migrations
    Store(tmp_path)
    (tmp_path / 'backups').write_text('模拟不可创建目录')
    monkeypatch.setattr(migrations, 'MIGRATIONS', (*migrations.MIGRATIONS, (CURRENT + 1, 'create table added(id text);')))
    with pytest.raises(RuntimeError, match='数据库升级失败'):
        Store(tmp_path)
    with sqlite3.connect(tmp_path / 'platform.db') as db:
        assert db.execute('select max(version) from schema_versions').fetchone() == (CURRENT,)
        assert db.execute("select name from sqlite_master where name='added'").fetchall() == []


def test_published_migrations_are_append_only():
    import json
    from conftest import ROOT
    from haiknow_core.migrations import MIGRATIONS
    frozen = json.loads((ROOT / 'tests/compat/schema-migrations.json').read_text())
    assert [list(m) for m in MIGRATIONS[:len(frozen)]] == frozen, '已发布迁移不能改写，只能在末尾追加'


def test_main_version_three_database_upgrades_to_app_registry(tmp_path, monkeypatch):
    """main 已到版本 3 的现存库：升级到当前版本后补出应用上架的表，平台仍能启动。"""
    from conftest import ROOT
    from haiknow_core import migrations
    from haiknow_core.main import create_app

    published = migrations.MIGRATIONS
    # 只应用 main 已发布的 1–3，构造升级前就停在版本 3 的数据目录。
    monkeypatch.setattr(migrations, 'MIGRATIONS', published[:3])
    Store(tmp_path)
    with sqlite3.connect(tmp_path / 'platform.db') as db:
        assert db.execute('select max(version) from schema_versions').fetchone() == (3,)
        assert db.execute("select name from sqlite_master where name='app_registry'").fetchall() == []

    monkeypatch.setattr(migrations, 'MIGRATIONS', published)
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path))
    create_app(ROOT)

    with sqlite3.connect(tmp_path / 'platform.db') as db:
        assert db.execute('select max(version) from schema_versions').fetchone() == (len(published),)
        tables = {row[0] for row in db.execute("select name from sqlite_master where type='table'")}
    assert {'app_registry', 'app_runs'} <= tables
    assert len(list((tmp_path / 'backups').glob('*-3.db'))) == 1


def test_version_eight_database_upgrades_users_with_default_generation(tmp_path, monkeypatch):
    """已到版本 8 的库升级到 9：users 追加可空 session_gen，旧用户读作代数 0，会话不被迫重登。"""
    from haiknow_core import migrations
    from haiknow_core.identity import Directory

    published = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, 'MIGRATIONS', published[:8])
    Store(tmp_path)
    with sqlite3.connect(tmp_path / 'platform.db') as db:
        db.execute("insert into users values ('legacy','legacy','旧用户','x','active',null,0,0,1,0)")
        assert db.execute('select max(version) from schema_versions').fetchone() == (8,)

    monkeypatch.setattr(migrations, 'MIGRATIONS', published)
    store = Store(tmp_path)
    assert store._db.execute("select session_gen from users where id='legacy'").fetchone() == (None,)
    assert store._db.execute('select max(version) from schema_versions').fetchone() == (len(published),)
    assert Directory(store).session_gen('legacy') == 0

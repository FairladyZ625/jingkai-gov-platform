import sqlite3
from contextlib import closing

from conftest import set_provider_credential
from haiknow_core import migrations
from haiknow_core.settings import AISettings
from haiknow_core.store import Store


def test_credentials_are_available_only_from_environment(tmp_path, monkeypatch):
    settings = AISettings(tmp_path)
    url = 'https://provider.example.test/v1'
    settings.put_provider('one', 'openai', url, ['model'], True)
    assert not settings.providers()[0]['has_key']
    assert settings.provider('one')['api_key'] == ''
    set_provider_credential(monkeypatch, 'one', url, 'sample-runtime-only')
    assert settings.providers()[0]['has_key']
    assert settings.providers()[0]['api_key'] == '********'
    assert AISettings(tmp_path).provider('one')['api_key'] == 'sample-runtime-only'
    assert b'sample-runtime-only' not in (tmp_path / 'platform.db').read_bytes()
    assert not list(tmp_path.glob('*.key'))
    settings.put_provider('one', 'openai', 'https://other.example.test/v1', ['model'], True)
    assert settings.provider('one')['api_key'] == ''


def test_upgrade_removes_legacy_credentials_from_database_and_new_backup(tmp_path, monkeypatch):
    published = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, 'MIGRATIONS', published[:13])
    with closing(Store(tmp_path)._db) as db, db:
        db.execute('insert into ai_provider values (?,?,?,?,?,?,?)', (
            'old', 'openai', 'https://old.example.test/v1', b'model-ciphertext-fixture', '["m"]', 1, 'public'))
        db.execute('insert into ai_route values (?,?,?,?,?)', ('chat', 'old', 'm', None, None))
        columns = {row[1] for row in db.execute('pragma table_info(feishu_config)')}
        assert 'encrypt_key' in columns
        db.execute("insert into feishu_config values ('fixture','sample',X'',?,NULL,1,'system')",
                   (b'other-ciphertext-fixture',))
    monkeypatch.setattr(migrations, 'MIGRATIONS', published)
    for _ in range(2):
        settings = AISettings(tmp_path)
        with closing(settings._db) as db:
            assert 'secret' not in {row[1] for row in db.execute('pragma table_info(ai_provider)')}
            assert 'encrypt_key' not in {row[1] for row in db.execute('pragma table_info(feishu_config)')}
            assert settings.provider('old')['api_key'] == ''
            assert settings.provider('old')['allow_outbound'] == 'public'
            assert settings.route('chat')['model'] == 'm'
    backups = list((tmp_path / 'backups').glob('*.db'))
    assert len(backups) == 1
    for path in (tmp_path / 'platform.db', *backups):
        data = path.read_bytes()
        assert b'model-ciphertext-fixture' not in data
        assert b'other-ciphertext-fixture' not in data
    assert not list(tmp_path.glob('*.key'))


def test_quota_reservation_is_atomic_across_connections(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    stores = [AISettings(tmp_path), AISettings(tmp_path)]
    stores[0].put_quota('demo', 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reservations = list(pool.map(lambda store: store.reserve('demo', 'chat', 'mock', 0, 'hash'), stores))
    assert sum(value is not None for value in reservations) == 1

import sqlite3
from contextlib import closing

from conftest import set_provider_credential
from haiknow_core.settings import AISettings


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


def test_schema_has_no_model_credential_columns(tmp_path):
    AISettings(tmp_path)
    with closing(sqlite3.connect(tmp_path / 'platform.db')) as db:
        provider_columns = {row[1] for row in db.execute('pragma table_info(ai_provider)')}
        assert provider_columns == {'id', 'kind', 'base_url', 'models', 'enabled', 'allow_outbound'}
        feishu_columns = {row[1] for row in db.execute('pragma table_info(feishu_config)')}
        assert feishu_columns == {'id', 'app_id', 'app_secret', 'verification_token', 'updated_at', 'updated_by'}
    assert not list(tmp_path.glob('*.key'))


def test_quota_reservation_is_atomic_across_connections(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    stores = [AISettings(tmp_path), AISettings(tmp_path)]
    stores[0].put_quota('demo', 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reservations = list(pool.map(lambda store: store.reserve('demo', 'chat', 'mock', 0, 'hash'), stores))
    assert sum(value is not None for value in reservations) == 1

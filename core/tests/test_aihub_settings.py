from haiknow_core.settings import AISettings


def test_secrets_persist_encrypted_and_masked(tmp_path):
    settings = AISettings(tmp_path)
    settings.put_provider('one', 'mock', '', 'sensitive-value', ['model'], True)
    assert settings.providers()[0]['api_key'] == '********'
    assert b'sensitive-value' not in (tmp_path / 'platform.db').read_bytes()
    assert AISettings(tmp_path).provider('one')['api_key'] == 'sensitive-value'


def test_quota_reservation_is_atomic_across_connections(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    stores = [AISettings(tmp_path), AISettings(tmp_path)]
    stores[0].put_quota('demo', 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reservations = list(pool.map(lambda store: store.reserve('demo', 'chat', 'mock', 0, 'hash'), stores))
    assert sum(value is not None for value in reservations) == 1

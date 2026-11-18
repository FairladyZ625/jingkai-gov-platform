from fastapi.testclient import TestClient
from haiknow_core.main import create_app


def test_admin_configuration_and_app_call(tmp_path, monkeypatch):
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path))
    client = TestClient(create_app())
    assert client.get('/api/v1/admin/ai/providers').status_code == 401
    client.post('/api/auth/login', json={'user_id': 'sampleadmin'})
    provider = {'kind': 'mock', 'base_url': '', 'api_key': 'dummy', 'models': ['m'], 'enabled': True}
    assert client.put('/api/v1/admin/ai/providers/a', json=provider).status_code == 200
    assert client.put('/api/v1/admin/ai/routes/chat', json={'provider': 'a', 'model': 'm'}).status_code == 200
    assert client.app.state.platform.model.aihub.call('demo', 'chat', {'messages': [{'role': 'user', 'content': '示例'}]})['result'].startswith('[模拟模型]')
    assert client.get('/api/v1/admin/ai/usage').json()['items'][0]['calls'] == 1


def test_switch_quota_and_disabled_provider(tmp_path, monkeypatch):
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path))
    client = TestClient(create_app())
    client.post('/api/auth/login', json={'user_id': 'sampleadmin'})
    gateway = client.app.state.platform.model.aihub
    for name in ('first', 'second'):
        assert client.put(f'/api/v1/admin/ai/providers/{name}', json={'kind': 'mock', 'models': ['m'], 'api_key': 'dummy'}).status_code == 200
    route = '/api/v1/admin/ai/routes/image'
    assert client.put(route, json={'provider': 'first', 'model': 'm'}).status_code == 200
    call = lambda: gateway.call('sample-app', 'image', {'prompt': '虚构样例'})
    assert call()['result'][0]['url'] == 'mock://first'
    assert client.put(route, json={'provider': 'second', 'model': 'm'}).status_code == 200
    assert call()['result'][0]['url'] == 'mock://second'
    assert sum(row['calls'] for row in client.get('/api/v1/admin/ai/usage').json()['items']) == 2
    assert client.put('/api/v1/admin/ai/quotas/sample-app', json={'max_calls': 2}).status_code == 200
    from haiknow_core.aihub.errors import AIError
    import pytest
    with pytest.raises(AIError, match='限额') as error:
        call()
    assert error.value.kind == 'quota_exceeded'
    assert client.put('/api/v1/admin/ai/quotas/sample-app', json={'max_calls': 5}).status_code == 200
    assert client.put('/api/v1/admin/ai/providers/second', json={'kind': 'mock', 'models': ['m'], 'enabled': False}).status_code == 200
    with pytest.raises(AIError) as error:
        call()
    assert error.value.kind == 'not_configured'
    assert client.delete(route).status_code == 200
    with pytest.raises(AIError) as error:
        call()
    assert error.value.kind == 'not_configured'
    client.post('/api/auth/login', json={'user_id': 'sampleoperator'})
    assert client.get('/api/v1/admin/ai/providers').status_code == 403


def test_sdk_and_error_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path))
    app = create_app()
    from fastapi import Depends
    from haiknow_sdk import AppContext, app_context
    @app.get('/api/apps/sample-app/test-ai')
    def use_ai(ctx: AppContext = Depends(app_context)):
        return ctx.ai.image('虚构样例')
    client = TestClient(app)
    client.post('/api/auth/login', json={'user_id': 'sampleadmin'})
    response = client.get('/api/apps/sample-app/test-ai')
    assert response.status_code == 503
    assert response.json()['error'] == {'code': 'not_configured', 'message': '该能力尚未配置。', 'retryable': False}
    client.put('/api/v1/admin/ai/providers/demo', json={'kind': 'mock', 'models': ['m']})
    client.put('/api/v1/admin/ai/routes/image', json={'provider': 'demo', 'model': 'm'})
    assert client.get('/api/apps/sample-app/test-ai').json()['result'][0]['url'] == 'mock://demo'


def test_legacy_model_prefers_system_config_and_keeps_string(tmp_path, monkeypatch):
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path))
    client = TestClient(create_app())
    client.post('/api/auth/login', json={'user_id': 'sampleadmin'})
    client.put('/api/v1/admin/ai/providers/demo', json={'kind': 'mock', 'models': ['m']})
    client.put('/api/v1/admin/ai/routes/chat', json={'provider': 'demo', 'model': 'm'})
    legacy = client.app.state.platform.model.for_app('sample-app')
    assert legacy.available
    assert isinstance(legacy.chat([{'role': 'user', 'content': '示例'}]), str)
    client.put('/api/v1/admin/ai/providers/demo', json={'kind': 'mock', 'models': ['m'], 'enabled': False})
    assert not legacy.available


def test_invalid_admin_body_does_not_echo_secret(tmp_path, monkeypatch):
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path))
    client = TestClient(create_app())
    client.post('/api/auth/login', json={'user_id': 'sampleadmin'})
    response = client.put('/api/v1/admin/ai/providers/p', json={'kind': 'mock', 'models': [], 'api_key': 'private-placeholder'})
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'invalid_request'  # 请求体校验统一走 v1 信封
    assert 'private-placeholder' not in response.text


def test_legacy_model_preserves_error_kind_with_configured_route(tmp_path, monkeypatch):
    import httpx
    import pytest
    from haiknow_sdk import ModelError
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path))
    client = TestClient(create_app())
    client.post('/api/auth/login', json={'user_id': 'sampleadmin'})
    client.put('/api/v1/admin/ai/providers/p', json={'kind': 'openai', 'base_url': 'https://example.test', 'api_key': 'dummy', 'models': ['m']})
    client.put('/api/v1/admin/ai/routes/chat', json={'provider': 'p', 'model': 'm'})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})), **kw))
    with pytest.raises(ModelError) as error:
        client.app.state.platform.model.for_app('demo').chat([{'role': 'user', 'content': '示例'}])
    assert error.value.kind == 'bad_response'


def test_legacy_retries_and_preserves_http_status(tmp_path, monkeypatch):
    import httpx
    import pytest
    from haiknow_sdk import ModelError
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path))
    client = TestClient(create_app())
    client.post('/api/auth/login', json={'user_id': 'sampleadmin'})
    client.put('/api/v1/admin/ai/providers/p', json={'kind': 'openai', 'base_url': 'https://example.test', 'api_key': 'dummy', 'models': ['m']})
    client.put('/api/v1/admin/ai/routes/chat', json={'provider': 'p', 'model': 'm'})
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(503)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(ModelError) as error:
        client.app.state.platform.model.for_app('demo').chat([{'role': 'user', 'content': '示例'}])
    assert error.value.kind == 'http' and error.value.status_code == 503
    assert len(requests) == 2


def _admin_client(tmp_path, monkeypatch):
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path))
    client = TestClient(create_app())
    assert client.post('/api/auth/login', json={'user_id': 'sampleadmin'}).status_code == 200
    return client


def _deepseek(client):
    return client.put('/api/v1/admin/ai/providers/ds', json={
        'kind': 'deepseek', 'base_url': 'https://api.deepseek.example.test/v1',
        'api_key': 'test-placeholder-key', 'models': ['deepseek-chat']})


def test_route_rejects_capability_unsupported_by_provider(tmp_path, monkeypatch):
    client = _admin_client(tmp_path, monkeypatch)
    assert _deepseek(client).status_code == 200
    refused = client.put('/api/v1/admin/ai/routes/image', json={'provider': 'ds', 'model': 'deepseek-chat'})
    assert refused.status_code == 400
    assert refused.json()['error']['code'] == 'invalid_request'
    assert refused.json()['error']['message'] == '服务商 ds 不支持能力 image'
    assert client.get('/api/v1/admin/ai/routes').json()['items'] == []
    # 阳性对照：同一服务商支持的能力照常保存。
    assert client.put('/api/v1/admin/ai/routes/chat', json={'provider': 'ds', 'model': 'deepseek-chat'}).status_code == 200


def test_route_rejects_capability_unsupported_by_fallback(tmp_path, monkeypatch):
    client = _admin_client(tmp_path, monkeypatch)
    assert client.put('/api/v1/admin/ai/providers/fake', json={'kind': 'mock', 'models': ['m']}).status_code == 200
    assert client.put('/api/v1/admin/ai/providers/mineru', json={
        'kind': 'mineru', 'base_url': 'https://mineru.example.test/api/v4',
        'api_key': 'test-placeholder-key', 'models': ['vlm']}).status_code == 200
    refused = client.put('/api/v1/admin/ai/routes/chat', json={
        'provider': 'fake', 'model': 'm', 'fallback_provider': 'mineru', 'fallback_model': 'vlm'})
    assert refused.status_code == 400
    assert refused.json()['error']['message'] == '服务商 mineru 不支持能力 chat'
    assert client.get('/api/v1/admin/ai/routes').json()['items'] == []
    assert client.put('/api/v1/admin/ai/routes/parse', json={
        'provider': 'mineru', 'model': 'vlm', 'fallback_provider': 'fake', 'fallback_model': 'm'}).status_code == 200


def test_http_provider_reports_insecure_transport_warning(tmp_path, monkeypatch):
    client = _admin_client(tmp_path, monkeypatch)
    saved = client.put('/api/v1/admin/ai/providers/lan', json={
        'kind': 'openai', 'base_url': 'http://192.168.1.10:8000/v1', 'api_key': 'test-placeholder-key', 'models': ['m']})
    assert saved.status_code == 200
    assert saved.json()['warnings'] == [{'code': 'insecure_transport', 'message': '接入地址使用 http，密钥将以明文传输。'}]
    items = {row['id']: row for row in client.get('/api/v1/admin/ai/providers').json()['items']}
    assert items['lan']['warnings'] == saved.json()['warnings']
    assert items['lan']['api_key'] == '********'
    # 阴性：https、假服务商与内置读取器都没有传输告警。
    https = client.put('/api/v1/admin/ai/providers/cloud', json={
        'kind': 'deepseek', 'base_url': 'https://api.deepseek.example.test/v1', 'api_key': 'test-placeholder-key', 'models': ['deepseek-chat']})
    assert https.json()['warnings'] == []
    assert client.put('/api/v1/admin/ai/providers/fake', json={'kind': 'mock', 'models': ['m']}).json()['warnings'] == []
    assert client.put('/api/v1/admin/ai/providers/reader', json={'kind': 'builtin', 'models': ['reader-v1']}).json()['warnings'] == []
    items = {row['id']: row for row in client.get('/api/v1/admin/ai/providers').json()['items']}
    assert items['cloud']['warnings'] == [] and items['reader']['warnings'] == []


def test_delete_provider_with_route_reference_is_rejected(tmp_path, monkeypatch):
    client = _admin_client(tmp_path, monkeypatch)
    for name in ('main', 'backup'):
        assert client.put(f'/api/v1/admin/ai/providers/{name}', json={'kind': 'mock', 'models': ['m']}).status_code == 200
    assert client.put('/api/v1/admin/ai/routes/chat', json={
        'provider': 'main', 'model': 'm', 'fallback_provider': 'backup', 'fallback_model': 'm'}).status_code == 200
    for ident, expected in (('backup', ['chat']), ('main', ['chat'])):
        refused = client.delete(f'/api/v1/admin/ai/providers/{ident}')
        assert refused.status_code == 409
        assert refused.json()['error']['code'] == 'invalid_state'
        assert refused.json()['error']['capabilities'] == expected
        assert ident in refused.json()['error']['message']
    # 拒绝删除不级联：服务商和路由都还在，能力照常可查。
    assert [row['id'] for row in client.get('/api/v1/admin/ai/providers').json()['items']] == ['backup', 'main']
    assert client.get('/api/v1/admin/ai/routes').json()['items'][0]['fallback_provider'] == 'backup'


def test_delete_provider_clears_record_and_audits(tmp_path, monkeypatch):
    import sqlite3
    client = _admin_client(tmp_path, monkeypatch)
    assert client.put('/api/v1/admin/ai/providers/old', json={
        'kind': 'openai', 'base_url': 'https://example.test/v1', 'api_key': 'test-placeholder-key', 'models': ['m']}).status_code == 200
    assert client.put('/api/v1/admin/ai/routes/chat', json={'provider': 'old', 'model': 'm'}).status_code == 200
    assert client.delete('/api/v1/admin/ai/routes/chat').status_code == 200
    assert client.delete('/api/v1/admin/ai/providers/old').status_code == 200
    assert client.get('/api/v1/admin/ai/providers').json()['items'] == []
    with sqlite3.connect(tmp_path / 'platform.db') as db:
        assert db.execute('select count(*) from ai_provider where id=?', ('old',)).fetchone()[0] == 0
    assert client.delete('/api/v1/admin/ai/providers/old').status_code == 404
    audit = client.get('/api/audit?app_id=platform').json()['items']
    deleted = [item for item in audit if item['action'] == 'ai.provider.delete']
    assert deleted and deleted[0]['detail'] == {'provider': 'old'}
    assert 'test-placeholder-key' not in str(audit)


def test_capability_support_table_covers_every_provider_kind():
    from typing import get_args
    from haiknow_core.aihub.api import ProviderBody
    from haiknow_core.aihub.gateway import CAPABILITIES, CAPABILITY_SUPPORT
    assert set(CAPABILITY_SUPPORT) == set(get_args(ProviderBody.model_fields['kind'].annotation))
    assert set().union(*CAPABILITY_SUPPORT.values()) == CAPABILITIES


def test_one_click_test_samples_cover_every_capability():
    """新增能力时忘补最小样例，一键测试会静默不可用；这里让 CI 直接红。"""
    from haiknow_core.aihub.gateway import CAPABILITIES, TEST_SAMPLES
    assert set(TEST_SAMPLES) == CAPABILITIES


def test_provider_kind_change_rejects_capabilities_used_by_routes(tmp_path, monkeypatch):
    client = _admin_client(tmp_path, monkeypatch)
    assert client.put('/api/v1/admin/ai/providers/p', json={
        'kind': 'ark', 'base_url': 'https://ark.example.test/api/v3',
        'api_key': 'test-placeholder-key', 'models': ['m']}).status_code == 200
    assert client.put('/api/v1/admin/ai/routes/image', json={'provider': 'p', 'model': 'm'}).status_code == 200
    refused = client.put('/api/v1/admin/ai/providers/p', json={
        'kind': 'deepseek', 'base_url': 'https://api.deepseek.example.test/v1',
        'api_key': 'test-placeholder-key', 'models': ['m']})
    assert refused.status_code == 409
    assert refused.json()['error']['code'] == 'invalid_state'
    assert refused.json()['error']['capabilities'] == ['image']
    assert 'deepseek' in refused.json()['error']['message'] and 'image' in refused.json()['error']['message']
    assert client.get('/api/v1/admin/ai/providers').json()['items'][0]['kind'] == 'ark'
    # 阳性对照：新类型仍支持该能力时照常保存。
    assert client.put('/api/v1/admin/ai/providers/p', json={
        'kind': 'openai', 'base_url': 'https://example.test/v1',
        'api_key': 'test-placeholder-key', 'models': ['m']}).status_code == 200


def test_provider_model_removal_rejects_models_used_by_routes(tmp_path, monkeypatch):
    client = _admin_client(tmp_path, monkeypatch)
    assert client.put('/api/v1/admin/ai/providers/p', json={
        'kind': 'openai', 'base_url': 'https://example.test/v1',
        'api_key': 'test-placeholder-key', 'models': ['m1', 'm2']}).status_code == 200
    assert client.put('/api/v1/admin/ai/routes/chat', json={'provider': 'p', 'model': 'm1'}).status_code == 200
    refused = client.put('/api/v1/admin/ai/providers/p', json={
        'kind': 'openai', 'base_url': 'https://example.test/v1',
        'api_key': 'test-placeholder-key', 'models': ['m2']})
    assert refused.status_code == 409
    assert refused.json()['error']['capabilities'] == ['chat']
    assert 'chat·m1' in refused.json()['error']['message']
    assert client.get('/api/v1/admin/ai/providers').json()['items'][0]['models'] == ['m1', 'm2']
    # 阳性对照：保留路由正在用的模型即可保存。
    assert client.put('/api/v1/admin/ai/providers/p', json={
        'kind': 'openai', 'base_url': 'https://example.test/v1',
        'api_key': 'test-placeholder-key', 'models': ['m1', 'm2', 'm3']}).status_code == 200


def _fake_http(monkeypatch, respond):
    import httpx
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))


def _image_provider(client, ident='ark'):
    return client.put(f'/api/v1/admin/ai/providers/{ident}', json={
        'kind': 'ark', 'base_url': 'https://ark.example.test/api/v3',
        'api_key': 'test-placeholder-key', 'models': ['image-model']})


def test_route_test_returns_success_preview_and_audits(tmp_path, monkeypatch):
    import httpx
    client = _admin_client(tmp_path, monkeypatch)
    assert _image_provider(client).status_code == 200
    assert client.put('/api/v1/admin/ai/routes/image', json={'provider': 'ark', 'model': 'image-model'}).status_code == 200
    _fake_http(monkeypatch, lambda request: httpx.Response(200, json={
        'data': [{'url': 'data:image/png;base64,AAAA'}]}))
    response = client.post('/api/v1/admin/ai/routes/image/test')
    assert response.status_code == 200
    body = response.json()
    assert body['ok'] is True and body['capability'] == 'image'
    assert body['provider'] == 'ark' and body['model'] == 'image-model'
    assert isinstance(body['elapsed_ms'], int)
    assert body['preview'] == {'kind': 'image', 'url': 'data:image/png;base64,AAAA'}
    assert 'test-placeholder-key' not in response.text
    # 测试不占应用配额与用量。
    assert client.get('/api/v1/admin/ai/usage').json()['items'] == []
    audit = client.get('/api/audit?app_id=platform').json()['items']
    entry = [item for item in audit if item['action'] == 'ai.route.test'][0]
    assert entry['detail'] == {'capability': 'image', 'provider': 'ark', 'model': 'image-model', 'ok': True,
                               'elapsed_ms': body['elapsed_ms']}


def test_provider_test_without_capability_picks_routed_capability_and_reports_failure(tmp_path, monkeypatch):
    import httpx
    client = _admin_client(tmp_path, monkeypatch)
    assert _image_provider(client).status_code == 200
    assert client.put('/api/v1/admin/ai/routes/image', json={'provider': 'ark', 'model': 'image-model'}).status_code == 200
    _fake_http(monkeypatch, lambda request: httpx.Response(401, json={'error': {'message': 'invalid api key'}}))
    response = client.post('/api/v1/admin/ai/providers/ark/test')
    assert response.status_code == 200
    body = response.json()
    assert body['ok'] is False and body['capability'] == 'image'
    assert body['reason'] == 'auth'
    assert '密钥' in body['message']
    assert 'test-placeholder-key' not in response.text and 'provider_error' not in response.text
    audit = client.get('/api/audit?app_id=platform').json()['items']
    entry = [item for item in audit if item['action'] == 'ai.provider.test'][0]
    assert entry['detail']['provider'] == 'ark' and entry['detail']['ok'] is False


def test_provider_test_reports_unsupported_capability_in_chinese(tmp_path, monkeypatch):
    client = _admin_client(tmp_path, monkeypatch)
    assert client.put('/api/v1/admin/ai/providers/ds', json={
        'kind': 'deepseek', 'base_url': 'https://api.deepseek.example.test/v1',
        'api_key': 'test-placeholder-key', 'models': ['deepseek-chat']}).status_code == 200
    response = client.post('/api/v1/admin/ai/providers/ds/test', json={'capability': 'image'})
    assert response.status_code == 200
    body = response.json()
    assert body['ok'] is False and body['reason'] == 'unsupported'
    assert '不支持此能力' in body['message']


def test_test_endpoints_validate_admin_and_targets(tmp_path, monkeypatch):
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path))
    client = TestClient(create_app())
    client.post('/api/auth/login', json={'user_id': 'sampleadmin'})
    assert client.post('/api/v1/admin/ai/routes/chat/test').status_code == 200
    assert client.post('/api/v1/admin/ai/routes/nope/test').status_code == 400
    assert client.post('/api/v1/admin/ai/providers/missing/test').status_code == 404
    client.post('/api/auth/login', json={'user_id': 'sampleoperator'})
    assert client.post('/api/v1/admin/ai/routes/chat/test').status_code == 403
    assert client.post('/api/v1/admin/ai/providers/missing/test').status_code == 403

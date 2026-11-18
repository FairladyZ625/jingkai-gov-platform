"""AI 工具 HTTP 入口与网关：mock 端到端、校验、出站许可、文件可见性。"""
import asyncio
import hashlib
import json

import httpx
import pytest

from fastapi import Depends
from fastapi.testclient import TestClient

from conftest import set_provider_credential
from haiknow_core.main import create_app
from haiknow_sdk import AppContext, app_context
from haiknow_sdk import AppContext, app_context

SAMPLE = '%PDF-1.4\n虚构样例，不含真实业务数据\n'.encode()
AUDIO = b'RIFF' + b'\x00' * 4 + b'WAVE' + b'\x00' * 32


def login(tmp_path, monkeypatch, user='sampleadmin'):
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path))
    client = TestClient(create_app())
    assert client.post('/api/auth/login', json={'user_id': user}).status_code == 200
    return client


def mock_provider(client, ident='fake', **extra):
    body = {'kind': 'mock', 'models': ['mock-tools'], **extra}
    assert client.put(f'/api/v1/admin/ai/providers/{ident}', json=body).status_code == 200


def mock_routes(client, ident='fake', capabilities=('parse', 'search', 'fetch', 'vision')):
    for capability in capabilities:
        response = client.put(f'/api/v1/admin/ai/routes/{capability}', json={'provider': ident, 'model': 'mock-tools'})
        assert response.status_code == 200


def upload(client, project='sample-project'):
    response = client.post('/api/v1/files', files={'file': ('虚构样例.pdf', SAMPLE, 'application/pdf')},
                           data={'app': 'sample-app', 'project': project, 'purpose': 'parse'})
    assert response.status_code == 201
    return response.json()


def upload_audio(client, project='sample-project'):
    response = client.post('/api/v1/files', files={'file': ('晨会.webm', b'\x1a\x45\xdf\xa3' + b'\x42\x82\x84webm' + '虚构录音'.encode(), 'audio/webm')},
                           data={'app': 'sample-app', 'project': project, 'purpose': 'transcribe'})
    assert response.status_code == 201
    return response.json()


def test_four_capabilities_work_end_to_end_with_mock(tmp_path, monkeypatch):
    client = login(tmp_path, monkeypatch)
    mock_provider(client)
    mock_routes(client)
    document = upload(client)

    parsed = client.post('/api/v1/ai/parse', json={'appId': 'sample-app', 'fileId': document['fileId']})
    assert parsed.status_code == 200, parsed.text
    body = parsed.json()
    assert body['capability'] == 'parse' and body['provider'] == 'fake' and body['model'] == 'mock-tools'
    assert body['status'] == 'success' and isinstance(body['created_at'], float)
    assert body['input'] == {'kind': 'file', 'fileId': document['fileId'], 'name': '虚构样例.pdf', 'sha256': document['sha256']}
    result = body['result']
    assert result['mock'] is True
    assert result['blocks'][0]['type'] == 'text' and result['blocks'][0]['page'] == 1
    assert result['processedPages'] == [1] and result['uncoveredPages'] == []
    assert result['parser']['name'] == 'mock'
    assert result['source']['sha256'] == hashlib.sha256(SAMPLE).hexdigest()

    searched = client.post('/api/v1/ai/search', json={'appId': 'sample-app', 'query': '虚构供应商', 'count': 3})
    assert searched.status_code == 200, searched.text
    search = searched.json()
    assert search['input']['kind'] == 'text' and search['input']['length'] > 0
    assert search['result']['mock'] is True
    assert search['result']['query'] == '虚构供应商'
    assert set(search['result']['results'][0]) == {'url', 'title', 'snippet', 'rank', 'domain', 'publishedAt'}
    assert search['result']['service'] == {'provider': 'fake', 'model': 'mock-tools'}

    fetched = client.post('/api/v1/ai/fetch', json={'appId': 'sample-app', 'url': 'https://example.test/page'})
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()['result']['status'] == 'complete'
    assert fetched.json()['result']['finalUrl'] == 'https://example.test/page'
    assert fetched.json()['result']['reader'] == {'name': 'mock', 'version': 'mock-tools'}

    vision = client.post('/api/v1/ai/vision', json={'appId': 'sample-app', 'fileId': document['fileId'],
                                                    'instruction': '找出图中的标签'})
    assert vision.status_code == 200, vision.text
    assert vision.json()['result']['mock'] is True
    assert vision.json()['result']['candidates'][0]['label'] == '[模拟识别]'
    assert vision.json()['result']['source']['fileId'] == document['fileId']

    usage = client.get('/api/v1/admin/ai/usage').json()['items']
    assert {(row['capability'], row['status']) for row in usage} == {
        ('parse', 'success'), ('search', 'success'), ('fetch', 'success'), ('vision', 'success')}


def test_transcribe_cap09_file_reference_uses_detected_media_type(tmp_path, monkeypatch):
    client = login(tmp_path, monkeypatch)
    mock_provider(client)
    mock_routes(client, capabilities=('transcribe',))
    audio = upload_audio(client)
    response = client.post('/api/v1/ai/transcribe', json={
        'appId': 'sample-app', 'fileId': audio['fileId'], 'classification': 'internal'})
    assert response.status_code == 200, response.text
    assert response.json()['result'] == '[模拟转写]'
    assert response.json()['input']['fileId'] == audio['fileId']


def test_chat_outbound_limit_blocks_before_any_provider_request(tmp_path, monkeypatch):
    client = login(tmp_path, monkeypatch)
    mock_provider(client, 'public-chat', allow_outbound='public')
    assert client.put('/api/v1/admin/ai/routes/chat', json={
        'provider': 'public-chat', 'model': 'mock-tools'}).status_code == 200

    @client.app.get('/api/apps/sample-app/chat-boundary')
    def chat_boundary(ctx: AppContext = Depends(app_context)):
        return ctx.ai.chat([{'role': 'user', 'content': '虚构受限纪要'}], classification='confidential')

    client.post('/api/auth/logout')
    assert client.post('/api/auth/login', json={'user_id': 'sampleoperator'}).status_code == 200
    response = client.get('/api/apps/sample-app/chat-boundary')
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'outbound_denied'
    client.post('/api/auth/logout')
    assert client.post('/api/auth/login', json={'user_id': 'sampleadmin'}).status_code == 200
    denials = [item for item in client.get('/api/audit').json()['items'] if item['action'] == 'ai.outbound_denied']
    assert denials[0]['user'] == 'sampleoperator'


def test_legacy_environment_chat_defaults_internal_and_blocks_confidential(tmp_path, monkeypatch):
    monkeypatch.setenv('HAIKNOW_MODEL_BASE_URL', 'https://legacy.example.test/v1')
    monkeypatch.setenv('HAIKNOW_MODEL_API_KEY', 'test-placeholder-key')
    monkeypatch.setenv('HAIKNOW_MODEL_NAME', 'legacy-model')
    requests = []
    original = httpx.AsyncClient

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': '收到'}}]})

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs))
    client = login(tmp_path, monkeypatch)

    @client.app.get('/api/apps/sample-app/legacy-chat')
    def legacy_chat(ctx: AppContext = Depends(app_context)):
        return ctx.model.chat([{'role': 'user', 'content': '日常输入'}])

    @client.app.get('/api/apps/sample-app/legacy-confidential-chat')
    def legacy_confidential_chat(ctx: AppContext = Depends(app_context)):
        return ctx.model.chat([{'role': 'user', 'content': '受限输入'}], classification='confidential')

    client.post('/api/auth/logout')
    assert client.post('/api/auth/login', json={'user_id': 'sampleoperator'}).status_code == 200
    assert client.get('/api/apps/sample-app/legacy-chat').status_code == 200
    denied = client.get('/api/apps/sample-app/legacy-confidential-chat')
    assert denied.status_code == 403 and denied.json()['kind'] == 'outbound_denied'
    assert len(requests) == 1
    assert 'classification' not in requests[0]

    client.post('/api/auth/logout')
    assert client.post('/api/auth/login', json={'user_id': 'sampleadmin'}).status_code == 200
    denials = [item for item in client.get('/api/audit').json()['items']
               if item['action'] == 'ai.outbound_denied']
    assert denials[0]['user'] == 'sampleoperator'
    assert denials[0]['detail'] == {'capability': 'chat', 'classification': 'confidential'}


def test_request_validation_and_unauthorized_app(tmp_path, monkeypatch):
    client = login(tmp_path, monkeypatch)
    mock_provider(client)
    mock_routes(client, capabilities=('parse', 'vision', 'transcribe'))
    assert client.post('/api/v1/ai/parse', json={}).status_code == 422
    assert client.post('/api/v1/ai/parse', json={'appId': 'sample-app'}).status_code == 422
    assert client.post('/api/v1/ai/vision', json={'appId': 'sample-app', 'fileId': 'f'}).status_code == 422
    assert client.post('/api/v1/ai/search', json={'appId': 'sample-app', 'query': ''}).status_code == 422
    assert client.post('/api/v1/ai/search', json={'appId': 'sample-app', 'query': 'x', 'count': 0}).status_code == 422
    assert client.post('/api/v1/ai/fetch', json={'appId': 'sample-app', 'url': 'https://example.test',
                                                 'classification': 'secret'}).status_code == 422
    missing = client.post('/api/v1/ai/parse', json={'appId': 'sample-app', 'fileId': 'no-such-file'})
    assert missing.status_code == 404 and missing.json()['error']['code'] == 'not_found'
    assert client.post('/api/v1/ai/search', json={'appId': 'no-such-app', 'query': 'x'}).status_code == 404


def test_outbound_limit_blocks_confidential_and_public_provider(tmp_path, monkeypatch):
    client = login(tmp_path, monkeypatch)
    mock_provider(client, 'open', allow_outbound='public')
    mock_routes(client, 'open', ('search',))
    denied = client.post('/api/v1/ai/search', json={'appId': 'sample-app', 'query': '虚构查询'})
    assert denied.status_code == 403 and denied.json()['error']['code'] == 'outbound_denied'
    assert denied.json()['error']['retryable'] is False
    assert client.post('/api/v1/ai/search', json={'appId': 'sample-app', 'query': '虚构查询',
                                                 'classification': 'public'}).status_code == 200
    # 未配置的新服务商按 internal 上限：internal 放行，confidential 拒绝。
    mock_provider(client, 'plain')
    mock_routes(client, 'plain', ('search',))
    assert client.post('/api/v1/ai/search', json={'appId': 'sample-app', 'query': '虚构查询'}).status_code == 200
    secret = client.post('/api/v1/ai/search', json={'appId': 'sample-app', 'query': '虚构查询', 'classification': 'confidential'})
    assert secret.status_code == 403 and secret.json()['error']['code'] == 'outbound_denied'
    providers = {row['id']: row for row in client.get('/api/v1/admin/ai/providers').json()['items']}
    assert providers['plain']['allow_outbound'] == 'internal'
    assert providers['open']['allow_outbound'] == 'public'
    usage = client.get('/api/v1/admin/ai/usage').json()['items']
    assert sum(row['calls'] for row in usage) == 2, '被出站许可拒绝的调用不应计费'
    denials = [item for item in client.get('/api/audit').json()['items'] if item['action'] == 'ai.outbound_denied']
    assert {(item['detail']['capability'], item['detail']['classification']) for item in denials} == {
        ('search', 'internal'), ('search', 'confidential')}
    assert all(item['app'] == 'sample-app' and item['user'] == 'sampleadmin' for item in denials)


def test_file_visibility_is_checked_for_parse_and_vision(tmp_path, monkeypatch):
    client = login(tmp_path, monkeypatch)
    mock_provider(client)
    mock_routes(client, capabilities=('parse', 'vision', 'transcribe'))
    restricted = upload(client, project='limited-project')
    client.post('/api/auth/logout')
    assert client.post('/api/auth/login', json={'user_id': 'sampleoperator'}).status_code == 200
    for capability, extra in (('parse', {}), ('vision', {'instruction': '描述这张图'}), ('transcribe', {})):
        response = client.post(f'/api/v1/ai/{capability}', json={'appId': 'sample-app',
                                                                 'fileId': restricted['fileId'], **extra})
        assert response.status_code == 404
        assert response.json()['error']['code'] == 'not_found'


def test_preview_ai_tools_uses_platform_context(tmp_path, monkeypatch):
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path))
    app = create_app()
    client = TestClient(app)
    assert client.post('/api/auth/login', json={'user_id': 'sampleadmin'}).status_code == 200
    mock_provider(client)
    mock_routes(client, capabilities=('search', 'transcribe'))
    audio = upload_audio(client)

    @app.get('/api/apps/sample-app/preview-tools')
    def preview_tools(ctx: AppContext = Depends(app_context)):
        assert ctx.preview.ai_tools is not None
        return {
            'search': ctx.preview.ai_tools.search('虚构查询', count=2),
            'transcribe': ctx.preview.ai_tools.transcribe(audio['fileId']),
        }

    response = client.get('/api/apps/sample-app/preview-tools')
    assert response.status_code == 200, response.text
    assert response.json()['search']['capability'] == 'search'
    assert response.json()['search']['result']['mock'] is True
    assert response.json()['transcribe']['capability'] == 'transcribe'
    assert response.json()['transcribe']['result'] == '[模拟转写]'


def test_fetch_rejects_malformed_ipv6_with_400(tmp_path, monkeypatch):
    client = login(tmp_path, monkeypatch)
    assert client.put('/api/v1/admin/ai/providers/reader', json={'kind': 'builtin', 'models': ['reader-v1']}).status_code == 200
    assert client.put('/api/v1/admin/ai/routes/fetch', json={'provider': 'reader', 'model': 'reader-v1'}).status_code == 200
    response = client.post('/api/v1/ai/fetch', json={'appId': 'sample-app', 'url': 'http://[::1'})
    assert response.status_code == 400
    assert response.json()['error']['code'] == 'bad_input'


def test_provider_kinds_and_probe_endpoint(tmp_path, monkeypatch):
    client = login(tmp_path, monkeypatch)
    assert client.put('/api/v1/admin/ai/providers/reader', json={'kind': 'builtin', 'models': ['reader-v1']}).status_code == 200
    refused = client.put('/api/v1/admin/ai/providers/mineru', json={'kind': 'mineru', 'models': ['vlm']})
    assert refused.status_code == 422 and refused.json()['error']['code'] == 'invalid_request'
    assert client.put('/api/v1/admin/ai/providers/mineru', json={
        'kind': 'mineru', 'base_url': 'https://mineru.net/api/v4', 'models': ['vlm'], 'allow_outbound': 'confidential'}).status_code == 200
    probed = client.post('/api/v1/admin/ai/providers/reader/probe')
    assert probed.status_code == 200 and probed.json()['ok'] is True
    assert client.post('/api/v1/admin/ai/providers/missing/probe').status_code == 404
    client.post('/api/auth/logout')
    assert client.post('/api/auth/login', json={'user_id': 'sampleoperator'}).status_code == 200
    assert client.post('/api/v1/admin/ai/providers/reader/probe').status_code == 403


def test_timeout_error_carries_task_id(tmp_path, monkeypatch):
    from haiknow_core.aihub import adapters
    from haiknow_core.aihub.errors import AIError
    from haiknow_core.aihub.gateway import Gateway
    from haiknow_core.settings import AISettings
    import httpx

    store = AISettings(tmp_path)
    set_provider_credential(monkeypatch, 'mineru', 'https://mineru.example.test/api/v4', 'test-placeholder-key')
    store.put_provider('mineru', 'mineru', 'https://mineru.example.test/api/v4', ['vlm'], True)
    store.put_route('parse', 'mineru', 'vlm')

    class Files:
        def get_file(self, user, file_id):
            return {'fileId': file_id, 'name': '虚构样例.pdf', 'sha256': 'f' * 64}

        def read_file(self, user, file_id):
            return SAMPLE

    original = httpx.AsyncClient
    def respond(request):
        if request.url.path.endswith('/file-urls/batch'):
            return httpx.Response(200, json={'code': 0, 'data': {'batch_id': 'batch-1', 'file_urls': ['https://upload.example.test/u']}})
        if request.url.host == 'upload.example.test':
            return httpx.Response(200)
        return httpx.Response(200, json={'code': 0, 'data': {'extract_result': [{'state': 'running'}]}})

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setattr(adapters, 'POLL_INTERVAL', 0.01)
    with pytest.raises(AIError) as error:
        Gateway(store, files=Files()).call('sample-app', 'parse', {'file_id': 'f1'}, timeout=0.2, principal='sampleoperator')
    assert error.value.kind == 'timeout'
    assert error.value.retryable is True
    assert error.value.task_id == 'batch-1'

    handler = client_handlers(tmp_path, monkeypatch)
    response = asyncio.run(handler(None, error.value))
    payload = json.loads(response.body)
    assert response.status_code == 504
    assert payload['error']['taskId'] == 'batch-1' and payload['error']['retryable'] is True


def client_handlers(tmp_path, monkeypatch):
    """取平台注册的 AIError 处理器，验证错误信封把任务 ID 交给调用方。"""
    from haiknow_core.aihub.errors import AIError
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path / 'handler'))
    from haiknow_core.main import create_app
    app = create_app()
    return app.exception_handlers[AIError]

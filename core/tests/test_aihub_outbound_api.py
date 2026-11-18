"""稳定入口与 preview/HTTP 共享出站边界，错误不得携带原文或地址。"""
import json

import httpx
import pytest
from fastapi import Depends

from conftest import set_provider_credential
from haiknow_sdk import AppContext, app_context
from test_aihub_adapters import HTML, fake_http, public_dns
from test_aihub_tools import login


def test_embedding_stable_preview_and_http_use_same_policy(tmp_path, monkeypatch):
    client = login(tmp_path, monkeypatch)
    set_provider_credential(monkeypatch, 'p', 'https://provider.test/v1', 'dummy-key')
    provider = {'kind': 'openai', 'base_url': 'https://provider.test/v1', 'models': ['m'], 'allow_outbound': 'public'}
    assert client.put('/api/v1/admin/ai/providers/p', json=provider).status_code == 200
    assert client.put('/api/v1/admin/ai/routes/embedding', json={'provider': 'p', 'model': 'm'}).status_code == 200

    @client.app.get('/api/apps/sample-app/stable-embedding')
    def stable(ctx: AppContext = Depends(app_context)):
        return ctx.ai.embedding('虚构合同原文')

    @client.app.get('/api/apps/sample-app/preview-embedding')
    def preview(ctx: AppContext = Depends(app_context)):
        return ctx.preview.ai_tools.embedding('公开样例', classification='public')

    requests = []
    fake_http(monkeypatch, lambda request: requests.append(request) or httpx.Response(
        200, json={'data': [{'embedding': [0.1]}]}))
    client.post('/api/auth/logout')
    assert client.post('/api/auth/login', json={'user_id': 'sampleoperator'}).status_code == 200
    body = {'appId': 'sample-app', 'text': '虚构合同原文'}
    for response in [client.get('/api/apps/sample-app/stable-embedding'),
                     client.post('/api/v1/ai/embedding', json=body)]:
        assert response.status_code == 403
        assert response.json()['error']['code'] == 'outbound_denied'
        assert '虚构合同原文' not in response.text and 'provider.test' not in response.text
    assert requests == []
    assert client.get('/api/apps/sample-app/preview-embedding').json()['result'] == [{'embedding': [0.1]}]
    assert client.post('/api/v1/ai/embedding', json={**body, 'classification': 'public'}).status_code == 200
    assert len(requests) == 2
    assert all('classification' not in json.loads(request.content) for request in requests)
    client.post('/api/auth/logout')
    assert client.post('/api/auth/login', json={'user_id': 'sampleadmin'}).status_code == 200
    audit = [item for item in client.get('/api/audit').json()['items'] if item['action'] == 'ai.outbound_denied']
    assert len(audit) == 2
    assert all(item['user'] == 'sampleoperator' and item['detail'] == {
        'capability': 'embedding', 'classification': 'internal'} for item in audit)
    # 未配置上限的旧服务商仍能承接稳定入口的 internal 缺省分类。
    provider.pop('allow_outbound')
    set_provider_credential(monkeypatch, 'plain', provider['base_url'])
    assert client.put('/api/v1/admin/ai/providers/plain', json=provider).status_code == 200
    assert client.put('/api/v1/admin/ai/routes/embedding', json={'provider': 'plain', 'model': 'm'}).status_code == 200
    assert client.get('/api/apps/sample-app/stable-embedding').status_code == 200
    assert len(requests) == 3


def test_fetch_authorized_hosts_reach_reader_from_http_and_python(tmp_path, monkeypatch):
    client = login(tmp_path, monkeypatch)
    assert client.put('/api/v1/admin/ai/providers/reader', json={
        'kind': 'builtin', 'models': ['v1']}).status_code == 200
    assert client.put('/api/v1/admin/ai/routes/fetch', json={'provider': 'reader', 'model': 'v1'}).status_code == 200

    @client.app.get('/api/apps/sample-app/limited-fetch')
    def preview(ctx: AppContext = Depends(app_context)):
        return ctx.preview.ai_tools.fetch_page('https://example.test/start', allowed_hosts=['example.test'])

    @client.app.get('/api/apps/sample-app/allowed-fetch')
    def allowed(ctx: AppContext = Depends(app_context)):
        return ctx.preview.ai_tools.fetch('https://example.test/start', allowed_hosts=['example.test', 'other.test'])

    public_dns(monkeypatch)
    hosts = []

    def respond(request):
        hosts.append(request.url.host)
        if request.url.host == 'example.test':
            return httpx.Response(302, headers={'location': 'https://other.test/private-path'})
        return httpx.Response(200, content=HTML)

    fake_http(monkeypatch, respond)
    body = {'appId': 'sample-app', 'url': 'https://example.test/start', 'allowed_hosts': ['example.test']}
    for response in [client.post('/api/v1/ai/fetch', json=body),
                     client.get('/api/apps/sample-app/limited-fetch')]:
        assert response.status_code == 403 and response.json()['error']['code'] == 'outbound_denied'
        assert 'other.test' not in response.text and 'private-path' not in response.text
    assert hosts == ['example.test', 'example.test']
    assert client.post('/api/v1/ai/fetch', json={**body, 'allowed_hosts': ['example.test', 'other.test']}).status_code == 200
    assert client.get('/api/apps/sample-app/allowed-fetch').status_code == 200
    assert hosts == ['example.test', 'example.test', 'example.test', 'other.test', 'example.test', 'other.test']


@pytest.mark.parametrize('allowed_hosts', [[], 'example.test', ['*.test'], ['https://example.test'], [1]])
def test_fetch_http_rejects_invalid_hosts_without_request(tmp_path, monkeypatch, allowed_hosts):
    client = login(tmp_path, monkeypatch)
    assert client.put('/api/v1/admin/ai/providers/reader', json={'kind': 'builtin', 'models': ['v1']}).status_code == 200
    assert client.put('/api/v1/admin/ai/routes/fetch', json={'provider': 'reader', 'model': 'v1'}).status_code == 200
    requests = []
    fake_http(monkeypatch, lambda request: requests.append(request) or httpx.Response(200, content=HTML))
    response = client.post('/api/v1/ai/fetch', json={
        'appId': 'sample-app', 'url': 'https://example.test/', 'allowed_hosts': allowed_hosts})
    assert response.status_code in (400, 422)
    assert response.json()['error']['code'] in ('bad_input', 'invalid_request')
    assert requests == []


def test_embedding_http_validates_identity_app_and_classification(tmp_path, monkeypatch):
    client = login(tmp_path, monkeypatch)
    body = {'appId': 'sample-app', 'text': '公开样例'}
    assert client.post('/api/v1/ai/embedding', json={**body, 'text': ''}).status_code == 422
    assert client.post('/api/v1/ai/embedding', json={**body, 'classification': 'unknown'}).status_code == 422
    assert client.post('/api/v1/ai/embedding', json={**body, 'appId': 'missing'}).status_code == 404
    client.post('/api/auth/logout')
    assert client.post('/api/v1/ai/embedding', json=body).status_code == 401

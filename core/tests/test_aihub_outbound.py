"""出站边界回归：断言实际 HTTP 请求，而不只检查策略集合。"""
import json

import httpx
import pytest

from conftest import set_provider_credential
from haiknow_core.aihub.errors import AIError
from haiknow_core.aihub.gateway import CAPABILITY_SUPPORT, OUTBOUND_CAPABILITIES, Gateway, TEST_SAMPLES
from haiknow_core.settings import AISettings
from test_aihub_adapters import HTML, builtin_gateway, fake_http, public_dns


@pytest.mark.parametrize('kind,capabilities', CAPABILITY_SUPPORT.items())
def test_every_registered_upstream_capability_has_outbound_policy(kind, capabilities):
    # 当前能力表中的能力都会把用户内容发往上游；新增能力不能漏登分级集合。
    assert capabilities <= OUTBOUND_CAPABILITIES, (kind, capabilities - OUTBOUND_CAPABILITIES)


@pytest.mark.parametrize('capability', ['embedding', 'image', 'speech'])
@pytest.mark.parametrize('primary,fallback,classification,fail_primary,expected,error', [
    (None, None, None, False, ['primary.test'], None),
    ('public', 'public', None, False, [], 'outbound_denied'),
    ('public', 'internal', None, False, ['fallback.test'], None),
    ('internal', 'public', None, True, ['primary.test'], 'provider_error'),
    ('internal', 'internal', None, True, ['primary.test', 'fallback.test'], None),
    ('public', 'public', 'public', False, ['primary.test'], None),
    ('confidential', 'internal', 'confidential', True, ['primary.test'], 'provider_error'),
    ('internal', 'internal', 'confidential', False, [], 'outbound_denied'),
])
def test_text_capabilities_filter_each_route_before_http(tmp_path, monkeypatch, capability,
                                                       primary, fallback, classification,
                                                       fail_primary, expected, error):
    store = AISettings(tmp_path)
    for ident, limit in [('primary', primary), ('fallback', fallback)]:
        set_provider_credential(monkeypatch, ident, f'https://{ident}.test/v1', 'dummy-key')
        store.put_provider(ident, 'openai', f'https://{ident}.test/v1', ['m'], True,
                           allow_outbound=limit)
    store.put_route(capability, 'primary', 'm', 'fallback', 'm')
    requests, audit = [], []

    def respond(request):
        requests.append(request)
        if fail_primary and request.url.host == 'primary.test':
            return httpx.Response(500)
        return httpx.Response(200, json={'data': [{'embedding': [0.1]}]})

    fake_http(monkeypatch, respond)
    payload = dict(TEST_SAMPLES[capability])
    if classification is not None:
        payload['classification'] = classification
    gateway = Gateway(store, audit=lambda *args: audit.append(args))
    if error:
        with pytest.raises(AIError) as caught:
            gateway.call('demo', capability, payload)
        assert caught.value.kind == error
    else:
        assert gateway.call('demo', capability, payload)['status'] == 'success'
    assert [request.url.host for request in requests] == expected
    assert all('classification' not in json.loads(request.content) for request in requests)
    if error == 'outbound_denied':
        assert store.usage() == []
        assert audit == [('demo', 'system', 'ai.outbound_denied', {
            'capability': capability, 'classification': classification or 'internal'})]
    else:
        assert audit == []


@pytest.mark.parametrize('capability', ['embedding', 'image', 'speech'])
def test_admin_samples_obey_outbound_limit(tmp_path, monkeypatch, capability):
    store = AISettings(tmp_path)
    set_provider_credential(monkeypatch, 'p', 'https://primary.test/v1', 'dummy-key')
    store.put_provider('p', 'openai', 'https://primary.test/v1', ['m'], True,
                       allow_outbound='public')
    store.put_route(capability, 'p', 'm')
    requests = []
    fake_http(monkeypatch, lambda request: requests.append(request) or httpx.Response(200, json={'data': []}))
    gateway = Gateway(store)
    assert gateway.test(capability)['reason'] == 'outbound_denied'
    assert gateway.test(capability, provider_id='p')['reason'] == 'outbound_denied'
    assert requests == []


@pytest.mark.parametrize('target,allowed_hosts,expected,error', [
    ('https://example.test/next', ['example.test'], ['example.test', 'example.test'], None),
    ('https://other.test/next', ['example.test'], ['example.test'], 'outbound_denied'),
    ('https://other.test/next', ['example.test', 'other.test'], ['example.test', 'other.test'], None),
    ('https://child.example.test/next', ['example.test'], ['example.test'], 'outbound_denied'),
    ('https://example.test.other.test/next', ['example.test'], ['example.test'], 'outbound_denied'),
    ('http://127.0.0.1/next', ['example.test', '127.0.0.1'], ['example.test'], 'bad_input'),
    ('https://other.test/next', None, ['example.test', 'other.test'], None),
])
def test_fetch_checks_every_redirect_before_request(tmp_path, monkeypatch, target, allowed_hosts, expected, error):
    _, gateway = builtin_gateway(tmp_path)
    public_dns(monkeypatch)
    hosts = []

    def respond(request):
        hosts.append(request.url.host)
        if request.url.path == '/start':
            return httpx.Response(302, headers={'location': target})
        return httpx.Response(200, content=HTML, headers={'content-type': 'text/html'})

    fake_http(monkeypatch, respond)
    payload = {'url': 'https://example.test/start'}
    if allowed_hosts is not None:
        payload['allowed_hosts'] = allowed_hosts
    if error:
        with pytest.raises(AIError) as caught:
            gateway.call('demo', 'fetch', payload)
        assert caught.value.kind == error
        assert target not in str(caught.value)
    else:
        assert gateway.call('demo', 'fetch', payload)['result']['status'] == 'complete'
    assert hosts == expected


@pytest.mark.parametrize('url,allowed_hosts,error', [
    ('https://other.test/private-query', ['example.test'], 'outbound_denied'),
    ('https://example.test/', [], 'bad_input'),
    ('https://example.test/', 'example.test', 'bad_input'),
    ('https://example.test/', ['*.test'], 'bad_input'),
    ('https://example.test/', ['https://example.test'], 'bad_input'),
    ('https://example.test/', ['example.test:443'], 'bad_input'),
    ('https://example.test/', ['example.test/path'], 'bad_input'),
    ('https://example.test/', [''], 'bad_input'),
    ('https://example.test/', [1], 'bad_input'),
    ('http://127.0.0.1/', ['127.0.0.1'], 'bad_input'),
])
def test_fetch_rejects_initial_host_or_invalid_list_without_http(tmp_path, monkeypatch, url, allowed_hosts, error):
    _, gateway = builtin_gateway(tmp_path)
    public_dns(monkeypatch)
    requests = []
    fake_http(monkeypatch, lambda request: requests.append(request) or httpx.Response(200, content=HTML))
    with pytest.raises(AIError) as caught:
        gateway.call('demo', 'fetch', {'url': url, 'allowed_hosts': allowed_hosts})
    assert caught.value.kind == error
    assert url not in str(caught.value)
    assert requests == []


def test_allowed_host_still_requires_public_dns(tmp_path, monkeypatch):
    _, gateway = builtin_gateway(tmp_path)
    public_dns(monkeypatch, '10.0.0.1')
    requests = []
    fake_http(monkeypatch, lambda request: requests.append(request) or httpx.Response(200, content=HTML))
    with pytest.raises(AIError) as caught:
        gateway.call('demo', 'fetch', {'url': 'https://example.test/', 'allowed_hosts': ['example.test']})
    assert caught.value.kind == 'bad_input'
    assert requests == []


def test_unlisted_private_ip_keeps_private_address_error(tmp_path, monkeypatch):
    _, gateway = builtin_gateway(tmp_path)
    requests = []
    fake_http(monkeypatch, lambda request: requests.append(request) or httpx.Response(200, content=HTML))
    with pytest.raises(AIError) as caught:
        gateway.call('demo', 'fetch', {'url': 'http://127.0.0.1/', 'allowed_hosts': ['example.test']})
    assert caught.value.kind == 'bad_input'
    assert requests == []


@pytest.mark.parametrize('url,host', [
    ('https://EXAMPLE.test./', 'example.TEST'),
    ('https://xn--fsqu00a.test/', '例子.test'),
])
def test_fetch_normalizes_case_terminal_dot_and_idna(tmp_path, monkeypatch, url, host):
    _, gateway = builtin_gateway(tmp_path)
    public_dns(monkeypatch)
    requests = []
    fake_http(monkeypatch, lambda request: requests.append(request) or httpx.Response(200, content=HTML))
    assert gateway.call('demo', 'fetch', {'url': url, 'allowed_hosts': [host]})['result']['status'] == 'complete'
    assert len(requests) == 1

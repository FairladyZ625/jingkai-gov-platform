"""平台内部工具流通道：出站、配额、失败结算与冻结文本返回。"""
import json
import threading

import httpx
import pytest

from conftest import set_provider_credential
from haiknow_core.aihub.gateway import Gateway
from haiknow_core.aihub.errors import AIError
from haiknow_core.settings import AISettings

PAYLOAD = {'messages': [{'role': 'user', 'content': '虚构需求'}], 'tools': [
    {'type': 'function', 'function': {'name': 'list_specs', 'parameters': {'type': 'object'}}}]}
TOOL_DELTA = {'tool_calls': [{'index': 0, 'id': 'spec-1', 'type': 'function',
                             'function': {'name': 'list_specs', 'arguments': '{}'}}]}


def sse(delta, finish=None):
    return 'data: ' + json.dumps({'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]},
                                 ensure_ascii=False) + '\n\n'


def gateway(tmp_path, monkeypatch, fallback=False):
    settings = AISettings(tmp_path)
    set_provider_credential(monkeypatch, 'p', 'https://example.test/v1', 'test-only-key')
    settings.put_provider('p', 'openai', 'https://example.test/v1', ['m'], True)
    if fallback:
        settings.put_provider('backup', 'mock', '', ['m'], True)
    settings.put_route('chat', 'p', 'm', 'backup' if fallback else None, 'm' if fallback else None)
    return Gateway(settings)


def fake_http(monkeypatch, respond):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))


def test_native_tools_stream_and_usage(tmp_path, monkeypatch):
    g = gateway(tmp_path, monkeypatch)
    requests, chunks = [], []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text=sse(TOOL_DELTA) + sse({}, 'tool_calls') + 'data: [DONE]\n\n',
                              headers={'content-type': 'text/event-stream'})

    fake_http(monkeypatch, respond)
    g.stream_chat('platform-builder', PAYLOAD, chunks.append, threading.Event())
    body = json.loads(requests[0].content)
    assert body['tools'] == PAYLOAD['tools']
    assert body['stream'] is True and body['model'] == 'm'
    assert 'test-only-key' not in ''.join(chunks)
    assert TOOL_DELTA == json.loads(chunks[0].removeprefix('data: '))['choices'][0]['delta']
    assert g.settings.usage()[0]['status'] == 'success'


def test_stream_obeys_outbound_and_quota_before_network(tmp_path, monkeypatch):
    g = gateway(tmp_path, monkeypatch)
    g.settings.put_provider('p', 'openai', 'https://example.test/v1', ['m'], True,
                            allow_outbound='public')
    fake_http(monkeypatch, lambda request: pytest.fail('出站被拒绝后仍请求网络'))
    with pytest.raises(AIError) as error:
        g.stream_chat('platform-builder', PAYLOAD, lambda _: None, threading.Event())
    assert error.value.kind == 'outbound_denied'
    assert g.settings.usage() == []
    g.settings.put_provider('p', 'openai', 'https://example.test/v1', ['m'], True,
                            allow_outbound='internal')
    g.settings.put_quota('platform-builder', 0)
    with pytest.raises(AIError) as error:
        g.stream_chat('platform-builder', PAYLOAD, lambda _: None, threading.Event())
    assert error.value.kind == 'quota_exceeded'


def test_partial_failure_is_not_replayed_to_backup(tmp_path, monkeypatch):
    g = gateway(tmp_path, monkeypatch, fallback=True)
    chunks = []
    fake_http(monkeypatch, lambda request: httpx.Response(200, text=sse({'content': '半句话'})))
    with pytest.raises(AIError) as error:
        g.stream_chat('platform-builder', PAYLOAD, chunks.append, threading.Event())
    assert error.value.kind == 'provider_error'
    assert '半句话' in ''.join(chunks)
    assert '[模拟模型]' not in ''.join(chunks)
    assert g.settings.usage()[0]['status'] == 'failure'
    assert g.settings.usage()[0]['provider'] == 'p'


def test_stream_http_error_is_sanitized_and_failure_is_settled(tmp_path, monkeypatch):
    g = gateway(tmp_path, monkeypatch)
    fake_http(monkeypatch, lambda request: httpx.Response(401, text='test-only-key-private-error'))
    with pytest.raises(AIError) as error:
        g.stream_chat('platform-builder', PAYLOAD, lambda _: pytest.fail('泄漏上游正文'), threading.Event())
    assert error.value.kind == 'provider_error'
    assert 'private' not in str(error.value) and 'test-only-key' not in str(error.value)
    assert g.settings.usage()[0]['status'] == 'failure'


def test_sdk_chat_result_stays_text(tmp_path, monkeypatch):
    g = gateway(tmp_path, monkeypatch)
    fake_http(monkeypatch, lambda request: httpx.Response(200, json={
        'choices': [{'message': {'content': '普通对话仍返回文本'}}]}))
    assert g.call('demo', 'chat', PAYLOAD)['result'] == '普通对话仍返回文本'


def test_stream_cancellation_closes_upstream_and_settles_failure(tmp_path, monkeypatch):
    import time
    from anyio import sleep

    g = gateway(tmp_path, monkeypatch)
    stop, closed = threading.Event(), threading.Event()
    timer = threading.Timer(0.2, stop.set)

    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            await sleep(10)
            yield b'data: [DONE]\n\n'

        async def aclose(self):
            closed.set()

    fake_http(monkeypatch, lambda request: httpx.Response(200, stream=SlowBody()))
    started = time.monotonic()
    timer.start()
    try:
        with pytest.raises(AIError):
            g.stream_chat('platform-builder', PAYLOAD, lambda _: None, stop)
    finally:
        timer.cancel()
    assert time.monotonic() - started < 3
    assert closed.is_set()
    assert g.settings.usage()[0]['status'] == 'failure'

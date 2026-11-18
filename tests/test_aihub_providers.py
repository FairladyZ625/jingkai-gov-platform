import httpx
import pytest

from haiknow_core.aihub.gateway import Gateway, TEST_SAMPLES
from haiknow_core.aihub.errors import AIError
from haiknow_core.settings import AISettings


@pytest.mark.parametrize('kind,capability,payload,path,response,expected', [
    ('ark', 'chat', {'messages': [{'role': 'user', 'content': '示例'}]}, '/chat/completions', {'choices': [{'message': {'content': '答复'}}]}, '答复'),
    ('deepseek', 'chat', {'messages': [{'role': 'user', 'content': '示例'}]}, '/chat/completions', {'choices': [{'message': {'content': '答复'}}]}, '答复'),
    ('ark', 'image', {'prompt': '绘图'}, '/images/generations', {'data': [{'url': 'https://example.test/img'}]}, [{'url': 'https://example.test/img'}]),
    ('openai', 'embedding', {'input': '文字'}, '/embeddings', {'data': [{'embedding': [0.1]}]}, [{'embedding': [0.1]}]),
    ('openai', 'transcribe', TEST_SAMPLES['transcribe'], '/audio/transcriptions', {'text': '语音'}, '语音'),
])
def test_provider_wire_format(tmp_path, monkeypatch, kind, capability, payload, path, response, expected):
    store = AISettings(tmp_path)
    store.put_provider('p', kind, 'https://example.test', 'dummy', ['m'], True)
    store.put_route(capability, 'p', 'm')
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=response)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    assert Gateway(store).call('demo', capability, payload)['result'] == expected
    assert requests[0].url.path == path
    assert requests[0].headers['authorization'] == 'Bearer dummy'
    if capability == 'transcribe':
        assert b'WAV' in requests[0].content


def test_fallback_on_provider_failure_and_record(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('first', 'openai', 'https://example.test', 'dummy', ['m'], True)
    store.put_provider('backup', 'mock', '', '', ['m'], True)
    store.put_route('image', 'first', 'm', 'backup', 'm')
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(lambda r: httpx.Response(503)), **kwargs))
    assert Gateway(store).call('demo', 'image', {'prompt': '示例'})['result'][0]['url'] == 'mock://backup'
    assert store.usage()[0]['provider'] == 'backup'
    store.put_route('image', 'first', 'm')
    with pytest.raises(AIError) as exc:
        Gateway(store).call('demo', 'image', {'prompt': '示例'})
    assert exc.value.kind == 'provider_error'


def test_timeout_and_bad_input_are_distinct(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('p', 'openai', 'https://example.test', 'dummy', ['m'], True)
    store.put_route('transcribe', 'p', 'm')
    gateway = Gateway(store)
    with pytest.raises(AIError) as error:
        gateway.call('demo', 'transcribe', {'audio_base64': '不合法'})
    assert error.value.kind == 'bad_input'
    assert store.usage() == []
    original = httpx.AsyncClient
    def timeout(request):
        raise httpx.ReadTimeout('provider private body', request=request)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(timeout), **kwargs))
    with pytest.raises(AIError) as error:
        gateway.call('demo', 'transcribe', TEST_SAMPLES['transcribe'])
    assert error.value.kind == 'timeout'
    assert 'private' not in str(error.value)
    assert store.usage()[0]['status'] == 'failure'


def test_speech_and_mock_transcription_shapes(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('p', 'openai', 'https://example.test', 'dummy', ['m'], True)
    store.put_provider('fake', 'mock', '', '', ['m'], True)
    store.put_route('speech', 'p', 'm')
    store.put_route('transcribe', 'fake', 'm')
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'WAV')), **kwargs))
    gateway = Gateway(store)
    assert gateway.call('demo', 'speech', {'input': '示例'})['result'] == {'audio_base64': 'V0FW'}
    assert isinstance(gateway.call('demo', 'transcribe', TEST_SAMPLES['transcribe'])['result'], str)

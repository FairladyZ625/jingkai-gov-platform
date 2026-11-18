"""四种新能力的真实适配器：假 HTTP 下核对请求构造、响应映射与失败状态。"""
import base64
import hashlib
import io
import json
import ssl
import zipfile

import httpx
import pytest

from haiknow_core.aihub import adapters, reader
from haiknow_core.aihub.errors import AIError
from haiknow_core.aihub.gateway import Gateway, TEST_SAMPLES
from haiknow_core.settings import AISettings

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
HTML = ('<html><head><title>示例页面</title><script>var leak = 1;</script></head>'
        '<body><h1>标题</h1><p>第一段正文。</p><p>第二段正文。</p></body></html>').encode()


class Files:
    def __init__(self, data=PNG, name='虚构样例.png', sha=None):
        self.data, self.name = data, name
        self.sha = sha or hashlib.sha256(data).hexdigest()

    def get_file(self, user, file_id):
        return {'fileId': file_id, 'name': self.name, 'sha256': self.sha}

    def read_file(self, user, file_id):
        return self.data


def fake_http(monkeypatch, respond):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))


def public_dns(monkeypatch, address='93.184.216.34'):
    def resolve(host, port, type=0, *args, **kwargs):
        return [(2, 1, 6, '', (address, 0))]
    monkeypatch.setattr(reader.socket, 'getaddrinfo', resolve)


def result_zip(items):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('样例_content_list.json', json.dumps(items, ensure_ascii=False))
    return buffer.getvalue()


def ssl_failure(monkeypatch):
    """让上游在 TLS 层直接抛原生 SSLError：httpx 不包装时就是 Issue #79 的漏出路径。"""
    def respond(request):
        raise ssl.SSLError(1, '[SSL: SSLV3_ALERT_BAD_RECORD_MAC] bad record mac')
    fake_http(monkeypatch, respond)


@pytest.mark.parametrize('capability,payload', [
    ('chat', {'messages': [{'role': 'user', 'content': '示例'}]}),
    ('parse', {'file_id': 'f1'}),
])
def test_transport_errors_become_retryable_provider_error(tmp_path, monkeypatch, capability, payload):
    store = AISettings(tmp_path)
    if capability == 'parse':
        store.put_provider('parse', 'mineru', 'https://mineru.example.test/api/v4', 'test-placeholder-key', ['vlm'], True)
    else:
        store.put_provider('chat', 'openai', 'https://chat.example.test/v1', 'test-placeholder-key', ['m'], True)
    store.put_route(capability, capability, 'vlm' if capability == 'parse' else 'm')
    ssl_failure(monkeypatch)
    with pytest.raises(AIError) as error:
        Gateway(store, files=Files()).call('demo', capability, payload, principal='sampleoperator')
    assert error.value.kind == 'provider_error'
    assert error.value.retryable is True
    assert getattr(error.value, 'legacy_retryable', False) is True
    assert '连接中断' in str(error.value)
    assert 'SSLError' not in str(error.value) and 'BAD_RECORD_MAC' not in str(error.value)
    assert 'test-placeholder-key' not in str(error.value)


def test_probe_transport_failure_returns_chinese_detail(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('chat', 'openai', 'https://chat.example.test/v1', 'test-placeholder-key', ['m'], True)
    ssl_failure(monkeypatch)
    assert Gateway(store).probe('chat') == {'ok': False, 'detail': '无法连接服务，请检查接入地址。'}


def test_mineru_parse_uploads_polls_and_maps_blocks(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('mineru', 'mineru', 'https://mineru.example.test/api/v4', 'dummy-key', ['vlm'], True)
    store.put_route('parse', 'mineru', 'vlm')
    archive = result_zip([
        {'type': 'text', 'text': '第一段', 'page_idx': 0, 'bbox': [10, 20, 30, 40]},
        {'type': 'table', 'table_body': '<table><tr><td>值</td></tr></table>', 'page_idx': 2},
    ])
    requests = []

    def respond(request):
        requests.append(request)
        path = request.url.path
        if path == '/api/v4/file-urls/batch':
            return httpx.Response(200, json={'code': 0, 'data': {'batch_id': 'batch-1', 'file_urls': ['https://upload.example.test/u1']}})
        if request.url.host == 'upload.example.test':
            return httpx.Response(200)
        if path == '/api/v4/extract-results/batch/batch-1':
            return httpx.Response(200, json={'code': 0, 'data': {'extract_result': [{
                'state': 'done', 'full_zip_url': 'https://cdn.example.test/r.zip',
                'extract_progress': {'total_pages': 4}}]}})
        return httpx.Response(200, content=archive)

    fake_http(monkeypatch, respond)
    files = Files()
    envelope = Gateway(store, files=files).call('sample-app', 'parse', {'file_id': 'f1'}, principal='sampleoperator')

    created = requests[0]
    assert created.method == 'POST' and created.url.path == '/api/v4/file-urls/batch'
    assert created.headers['authorization'] == 'Bearer dummy-key'
    assert json.loads(created.content) == {'files': [{'name': '虚构样例.png', 'data_id': 'f1'}], 'model_version': 'vlm'}
    upload = requests[1]
    assert upload.method == 'PUT' and upload.content == PNG
    assert requests[2].url.path == '/api/v4/extract-results/batch/batch-1'
    assert requests[3].url.host == 'cdn.example.test'

    result = envelope['result']
    assert result['mock'] is False
    assert [block['order'] for block in result['blocks']] == [0, 1]
    assert result['blocks'][0] == {'id': 'b0', 'type': 'text', 'order': 0, 'page': 1, 'text': '第一段', 'bbox': [10, 20, 30, 40]}
    assert result['blocks'][1]['table'].startswith('<table>') and result['blocks'][1]['page'] == 3
    assert result['processedPages'] == [1, 3]
    assert result['uncoveredPages'] == [2, 4]
    assert result['totalPages'] == 4
    assert result['parser'] == {'name': 'mineru', 'version': 'vlm'}
    assert result['source'] == {'fileId': 'f1', 'name': '虚构样例.png', 'sha256': hashlib.sha256(PNG).hexdigest()}
    assert envelope['input']['sha256'] == result['source']['sha256']
    assert store.usage()[0]['provider'] == 'mineru' and store.usage()[0]['status'] == 'success'


def test_mineru_failure_and_kind_guard(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('mineru', 'mineru', 'https://mineru.example.test/api/v4', 'dummy-key', ['vlm'], True)
    store.put_route('parse', 'mineru', 'vlm')
    fake_http(monkeypatch, lambda request: httpx.Response(200, json={'code': -60010, 'msg': '解析失败'}))
    with pytest.raises(AIError) as error:
        Gateway(store, files=Files()).call('demo', 'parse', {'file_id': 'f1'}, principal='sampleoperator')
    assert error.value.kind == 'provider_error'
    assert store.usage()[0]['status'] == 'failure'

    store.put_provider('chat', 'openai', 'https://chat.example.test/v1', 'dummy-key', ['m'], True)
    store.put_route('parse', 'chat', 'm')
    with pytest.raises(AIError) as error:
        Gateway(store, files=Files()).call('demo', 'parse', {'file_id': 'f1'}, principal='sampleoperator')
    assert error.value.kind == 'provider_error'


def test_deepseek_search_maps_fields_and_request(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('search', 'deepseek', 'https://api.deepseek.example.test/v1', 'dummy-key', ['deepseek-flash'], True)
    store.put_route('search', 'search', 'deepseek-flash')
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'results': [
            {'title': '结果一', 'url': 'https://example.test/a', 'snippet': '摘要一', 'date': '2026-06-01T00:00:00+00:00'},
            {'title': '结果二', 'url': 'https://news.example.test/b', 'snippet': '摘要二', 'date': None},
            '不是对象',
        ]})

    fake_http(monkeypatch, respond)
    envelope = Gateway(store).call('demo', 'search', {'query': '虚构查询', 'count': 2, 'classification': 'internal'})
    sent = json.loads(requests[0].content)
    assert requests[0].url.path == '/v1/tools/search'
    assert requests[0].headers['authorization'] == 'Bearer dummy-key'
    assert sent == {'query': '虚构查询', 'count': 2}
    result = envelope['result']
    assert result['mock'] is False and result['query'] == '虚构查询'
    assert result['service'] == {'provider': 'search', 'model': 'deepseek-flash'}
    assert [item['rank'] for item in result['results']] == [1, 2]
    assert result['results'][0]['domain'] == 'example.test'
    assert result['results'][0]['publishedAt'] == '2026-06-01T00:00:00+00:00'
    assert result['results'][1]['publishedAt'] is None


def test_search_rejects_bad_count_and_reports_provider_error(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('search', 'deepseek', 'https://api.deepseek.example.test/v1', 'dummy-key', ['m'], True)
    store.put_route('search', 'search', 'm')
    gateway = Gateway(store)
    with pytest.raises(AIError) as error:
        gateway.call('demo', 'search', {'query': '虚构查询', 'count': 51})
    assert error.value.kind == 'bad_input'
    assert [row['status'] for row in store.usage()] == ['failure']
    fake_http(monkeypatch, lambda request: httpx.Response(500))
    with pytest.raises(AIError) as error:
        gateway.call('demo', 'search', {'query': '虚构查询'})
    assert error.value.kind == 'provider_error' and error.value.status_code == 500


def test_vision_builds_openai_multimodal_request_and_parses_candidates(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('vision', 'openai', 'https://vision.example.test/v1', 'dummy-key', ['qwen-vl'], True)
    store.put_route('vision', 'vision', 'qwen-vl')
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content':
            '```json\n{"candidates":[{"label":"焊点","bbox":[1,2,3,4],"confidence":0.9},{"label":""}]}\n```'}}]})

    fake_http(monkeypatch, respond)
    envelope = Gateway(store, files=Files()).call(
        'demo', 'vision', {'file_id': 'f1', 'instruction': '找出焊点缺陷'}, principal='sampleoperator')
    body = json.loads(requests[0].content)
    assert requests[0].url.path == '/v1/chat/completions'
    assert body['model'] == 'qwen-vl'
    user = body['messages'][1]['content']
    assert user[0] == {'type': 'text', 'text': '找出焊点缺陷'}
    assert user[1]['image_url']['url'].startswith('data:image/png;base64,')
    result = envelope['result']
    assert result['mock'] is False
    assert result['candidates'] == [{'label': '焊点', 'bbox': [1, 2, 3, 4], 'confidence': 0.9}]
    assert '焊点' in result['rawText']
    assert result['source']['fileId'] == 'f1'


def test_vision_keeps_raw_text_when_model_is_not_json(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('vision', 'ark', 'https://vision.example.test/v1', 'dummy-key', ['m'], True)
    store.put_route('vision', 'vision', 'm')
    fake_http(monkeypatch, lambda request: httpx.Response(200, json={'choices': [{'message': {'content': '图上有一个标签'}}]}))
    result = Gateway(store, files=Files()).call('demo', 'vision', {'file_id': 'f1', 'instruction': '读图'}, principal='sampleoperator')['result']
    assert result['candidates'] == [] and result['rawText'] == '图上有一个标签'


def test_vision_rejects_unsupported_image_and_provider(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('vision', 'openai', 'https://vision.example.test/v1', 'dummy-key', ['m'], True)
    store.put_route('vision', 'vision', 'm')
    with pytest.raises(AIError) as error:
        Gateway(store, files=Files(b'not-an-image')).call(
            'demo', 'vision', {'file_id': 'f1', 'instruction': '读图'}, principal='sampleoperator')
    assert error.value.kind == 'bad_input'
    store.put_provider('mineru', 'mineru', 'https://mineru.example.test/api/v4', 'dummy-key', ['m'], True)
    store.put_route('vision', 'mineru', 'm')
    with pytest.raises(AIError) as error:
        Gateway(store, files=Files()).call('demo', 'vision', {'file_id': 'f1', 'instruction': '读图'}, principal='sampleoperator')
    assert error.value.kind == 'provider_error'


def builtin_gateway(tmp_path):
    store = AISettings(tmp_path)
    store.put_provider('reader', 'builtin', '', '', ['reader-v1'], True)
    store.put_route('fetch', 'reader', 'reader-v1')
    return store, Gateway(store)


def test_fetch_reader_extracts_title_blocks_and_digest(tmp_path, monkeypatch):
    store, gateway = builtin_gateway(tmp_path)
    public_dns(monkeypatch)
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, content=HTML, headers={'content-type': 'text/html; charset=utf-8'})

    fake_http(monkeypatch, respond)
    result = gateway.call('demo', 'fetch', {'url': 'https://example.test/page'})['result']
    assert seen[0].headers['user-agent'].startswith('HAiKnowBot')
    assert result['status'] == 'complete' and result['reason'] is None
    assert result['finalUrl'] == 'https://example.test/page'
    assert result['title'] == '示例页面'
    assert [block['text'] for block in result['blocks']] == ['标题', '第一段正文。', '第二段正文。']
    assert [block['offset'] for block in result['blocks']] == [0, 3, 10]
    assert 'var leak' not in result['text']
    assert result['sha256'] == hashlib.sha256(HTML).hexdigest()
    assert result['reader'] == {'name': 'builtin', 'version': 'reader-v1'}
    assert result['mock'] is False


@pytest.mark.parametrize('response,reason', [
    (httpx.Response(404), 'not_found'),
    (httpx.Response(403), 'blocked'),
    (httpx.Response(429), 'blocked'),
    (httpx.Response(500), 'http_error'),
    (httpx.Response(200, content=b'', headers={'content-type': 'text/html'}), 'no_content'),
    (httpx.Response(200, content='<html><body>请完成安全验证</body></html>'.encode(), headers={'content-type': 'text/html'}), 'blocked'),
    (httpx.Response(200, content=b'{}', headers={'content-type': 'application/json'}), 'unsupported_content_type'),
])
def test_fetch_failure_states_are_distinct(tmp_path, monkeypatch, response, reason):
    store, gateway = builtin_gateway(tmp_path)
    public_dns(monkeypatch)
    fake_http(monkeypatch, lambda request: response)
    result = gateway.call('demo', 'fetch', {'url': 'https://example.test/page'})['result']
    assert result['status'] == 'failed'
    assert result['reason'] == reason
    assert result['blocks'] == [] and result['text'] == ''


def test_fetch_partial_when_text_is_truncated(tmp_path, monkeypatch):
    store, gateway = builtin_gateway(tmp_path)
    public_dns(monkeypatch)
    page = ('<html><body><p>' + '字' * 25000 + '</p></body></html>').encode()
    fake_http(monkeypatch, lambda request: httpx.Response(200, content=page, headers={'content-type': 'text/html'}))
    result = gateway.call('demo', 'fetch', {'url': 'https://example.test/long'})['result']
    assert result['status'] == 'partial' and result['truncated'] is True
    assert result['reason'] == 'truncated' and len(result['text']) == reader.MAX_CHARS


@pytest.mark.parametrize('url', [
    'http://127.0.0.1/admin', 'http://10.0.0.8/', 'http://172.16.3.4/', 'http://192.168.1.1/',
    'http://169.254.169.254/latest/meta-data', 'http://localhost:8800/', 'http://[::1]/', 'file:///etc/passwd',
    'https://user:pass@example.test/', 'https://example.test:99999/', 'http://[::1', 'http://[',
])
def test_fetch_rejects_internal_or_invalid_targets(tmp_path, monkeypatch, url):
    store, gateway = builtin_gateway(tmp_path)
    public_dns(monkeypatch)
    with pytest.raises(AIError) as error:
        gateway.call('demo', 'fetch', {'url': url})
    assert error.value.kind == 'bad_input'
    assert [row['status'] for row in store.usage()] == ['failure']


def test_fetch_rejects_hostname_resolving_to_private_address(tmp_path, monkeypatch):
    store, gateway = builtin_gateway(tmp_path)
    public_dns(monkeypatch, '127.0.0.1')
    with pytest.raises(AIError) as error:
        gateway.call('demo', 'fetch', {'url': 'https://internal.example.test/'})
    assert error.value.kind == 'bad_input'


def test_fetch_rejects_redirect_to_internal_address(tmp_path, monkeypatch):
    store, gateway = builtin_gateway(tmp_path)
    public_dns(monkeypatch)
    fake_http(monkeypatch, lambda request: httpx.Response(302, headers={'location': 'http://127.0.0.1/secret'}))
    with pytest.raises(AIError) as error:
        gateway.call('demo', 'fetch', {'url': 'https://example.test/start'})
    assert error.value.kind == 'bad_input'


@pytest.mark.parametrize('kind,base,response,ok', [
    ('mock', '', None, True),
    ('builtin', '', None, True),
    ('openai', 'https://models.example.test/v1', httpx.Response(200, json={'data': []}), True),
    ('openai', 'https://models.example.test/v1', httpx.Response(401), False),
    ('openai', 'https://models.example.test/v1', httpx.Response(503), False),
    ('mineru', 'https://mineru.example.test/api/v4', httpx.Response(200, json={'code': -60012, 'msg': '找不到任务'}), True),
    ('mineru', 'https://mineru.example.test/api/v4', httpx.Response(200, json={'code': 'A0202', 'msg': 'Token 错误'}), False),
])
def test_provider_probe(tmp_path, monkeypatch, kind, base, response, ok):
    store = AISettings(tmp_path)
    store.put_provider('p', kind, base, 'dummy-key', ['m'], True)
    if response is not None:
        fake_http(monkeypatch, lambda request: response)
    assert Gateway(store).probe('p')['ok'] is ok


def test_probe_unknown_provider(tmp_path):
    with pytest.raises(AIError) as error:
        Gateway(AISettings(tmp_path)).probe('missing')
    assert error.value.kind == 'not_found'

def search_store(tmp_path, primary_limit, fallback_limit):
    store = AISettings(tmp_path)
    store.put_provider('primary', 'deepseek', 'https://primary.test/v1', 'dummy-key', ['m'], True, allow_outbound=primary_limit)
    store.put_provider('fallback', 'deepseek', 'https://fallback.test/v1', 'dummy-key', ['m'], True, allow_outbound=fallback_limit)
    store.put_route('search', 'primary', 'm', 'fallback', 'm')
    return store


def test_fallback_never_receives_data_above_its_outbound_limit(tmp_path, monkeypatch):
    """主服务商允许 confidential、兜底只允许 public：主服务商失败也不能把查询词转给兜底。"""
    store = search_store(tmp_path, 'confidential', 'public')
    hosts = []

    def respond(request):
        hosts.append(request.url.host)
        return httpx.Response(500)

    fake_http(monkeypatch, respond)
    with pytest.raises(AIError) as error:
        Gateway(store).call('demo', 'search', {'query': '受限查询词', 'classification': 'confidential'})
    assert error.value.kind == 'provider_error'
    assert hosts == ['primary.test'], '不得向出站上限不足的兜底服务商发请求'


def test_fallback_below_primary_is_used_when_it_allows_the_classification(tmp_path, monkeypatch):
    """主服务商上限不足时在尝试前剔除；允许的兜底可以承接。"""
    store = search_store(tmp_path, 'public', 'internal')
    hosts = []

    def respond(request):
        hosts.append(request.url.host)
        return httpx.Response(200, json={'results': []})

    fake_http(monkeypatch, respond)
    envelope = Gateway(store).call('demo', 'search', {'query': '内部查询', 'classification': 'internal'})
    assert hosts == ['fallback.test']
    assert envelope['provider'] == 'fallback'


def test_outbound_denied_when_no_provider_allows_the_classification(tmp_path, monkeypatch):
    store = search_store(tmp_path, 'public', 'public')
    hosts = []
    fake_http(monkeypatch, lambda request: hosts.append(request.url.host) or httpx.Response(200, json={'results': []}))
    with pytest.raises(AIError) as error:
        Gateway(store).call('demo', 'search', {'query': '内部查询', 'classification': 'internal'})
    assert error.value.kind == 'outbound_denied'
    assert hosts == []


def test_chat_blocks_confidential_outbound_to_public_provider(tmp_path, monkeypatch):
    """修前负例：受限对话内容不能送到只允许 public 的服务商。"""
    store = AISettings(tmp_path)
    store.put_provider('public-chat', 'openai', 'https://chat.example.test/v1', 'dummy-key', ['m'], True,
                       allow_outbound='public')
    store.put_route('chat', 'public-chat', 'm')
    requests = []
    fake_http(monkeypatch, lambda request: requests.append(request) or httpx.Response(200, json={
        'choices': [{'message': {'content': '收到'}}]}))

    with pytest.raises(AIError) as error:
        Gateway(store).call('demo', 'chat', {
            'messages': [{'role': 'user', 'content': '受限会议纪要'}],
            'classification': 'confidential',
        })

    assert error.value.kind == 'outbound_denied'
    assert requests == []


def test_chat_classification_is_not_sent_to_provider(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('internal-chat', 'openai', 'https://chat.example.test/v1', 'dummy-key', ['m'], True)
    store.put_route('chat', 'internal-chat', 'm')
    requests = []
    fake_http(monkeypatch, lambda request: requests.append(request) or httpx.Response(200, json={
        'choices': [{'message': {'content': '收到'}}]}))

    result = Gateway(store).call('demo', 'chat', {
        'messages': [{'role': 'user', 'content': '内部材料'}], 'classification': 'internal',
    })['result']

    assert result == '收到'
    assert json.loads(requests[0].content) == {
        'messages': [{'role': 'user', 'content': '内部材料'}], 'model': 'm',
    }


def test_transcribe_blocks_confidential_outbound_to_public_provider(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('public-transcribe', 'openai', 'https://audio.example.test/v1', 'dummy-key', ['m'], True,
                       allow_outbound='public')
    store.put_route('transcribe', 'public-transcribe', 'm')
    requests = []
    fake_http(monkeypatch, lambda request: requests.append(request) or httpx.Response(200, json={'text': '不应到达'}))

    with pytest.raises(AIError) as error:
        Gateway(store).call('demo', 'transcribe', {
            **TEST_SAMPLES['transcribe'], 'classification': 'confidential',
        })

    assert error.value.kind == 'outbound_denied'
    assert requests == []


@pytest.mark.parametrize('capability,payload,path,response', [
    ('chat', {'messages': [{'role': 'user', 'content': '受限对话'}]}, '/chat/completions',
     {'choices': [{'message': {'content': '不应到达'}}]}),
    ('transcribe', TEST_SAMPLES['transcribe'], '/audio/transcriptions', {'text': '不应到达'}),
])
def test_chat_and_transcribe_do_not_fallback_below_outbound_limit(tmp_path, monkeypatch,
                                                                   capability, payload, path, response):
    store = AISettings(tmp_path)
    store.put_provider('primary', 'openai', 'https://primary.example.test/v1', 'dummy-key', ['m'], True,
                       allow_outbound='confidential')
    store.put_provider('fallback', 'openai', 'https://fallback.example.test/v1', 'dummy-key', ['m'], True,
                       allow_outbound='public')
    store.put_route(capability, 'primary', 'm', 'fallback', 'm')
    hosts = []

    def respond(request):
        hosts.append(request.url.host)
        if request.url.host == 'primary.example.test':
            return httpx.Response(500)
        return httpx.Response(200, json=response)

    fake_http(monkeypatch, respond)
    with pytest.raises(AIError) as error:
        Gateway(store).call('demo', capability, {**payload, 'classification': 'confidential'})
    assert error.value.kind == 'provider_error'
    assert hosts == ['primary.example.test']


def test_transcribe_input_modes_are_mutually_exclusive_and_size_limited(tmp_path):
    store = AISettings(tmp_path)
    store.put_provider('p', 'mock', '', '', ['m'], True)
    store.put_route('transcribe', 'p', 'm')
    gateway = Gateway(store)

    with pytest.raises(AIError, match='只能提供一种') as error:
        gateway.call('demo', 'transcribe', {'audio_base64': '', 'file_id': 'audio-1'})
    assert error.value.kind == 'bad_input'

    oversized = 'A' * (((20 * 1024 * 1024) + 1) * 4 // 3 + 4)
    with pytest.raises(AIError, match='20 MB') as error:
        gateway.call('demo', 'transcribe', {'audio_base64': oversized})
    assert error.value.kind == 'bad_input'


def test_transcribe_base64_rejects_non_wav_content(tmp_path):
    store = AISettings(tmp_path)
    store.put_provider('p', 'mock', '', '', ['m'], True)
    store.put_route('transcribe', 'p', 'm')
    audio = base64.b64encode(b'not a wav container').decode()

    with pytest.raises(AIError, match='只接受 WAV') as error:
        Gateway(store).call('demo', 'transcribe', {'audio_base64': audio})

    assert error.value.kind == 'bad_input'
    assert store.usage() == []


@pytest.mark.parametrize('name,data,mime', [
    ('morning.wav', b'RIFF' + b'\x00' * 4 + b'WAVE' + b'payload', 'audio/wav'),
    ('morning.webm', b'\x1a\x45\xdf\xa3' + b'\x42\x82\x84webm' + b'payload', 'audio/webm'),
    ('morning.mp4', b'\x00\x00\x00\x18ftyp' + b'payload', 'audio/mp4'),
    ('morning.ogg', b'OggS' + b'payload', 'audio/ogg'),
])
def test_transcribe_file_reference_preserves_actual_media_type(tmp_path, monkeypatch, name, data, mime):
    store = AISettings(tmp_path)
    store.put_provider('p', 'openai', 'https://audio.example.test/v1', 'dummy', ['m'], True)
    store.put_route('transcribe', 'p', 'm')
    requests = []

    class AudioFiles(Files):
        def __init__(self):
            super().__init__(data=data, name=name)

        def get_file(self, user, file_id):
            return {'fileId': file_id, 'name': self.name, 'sha256': self.sha, 'size': len(self.data)}

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'text': '晨会转写'})

    fake_http(monkeypatch, respond)
    result = Gateway(store, files=AudioFiles()).call(
        'demo', 'transcribe', {'file_id': 'audio-1'}, principal='sampleoperator')['result']
    assert result == '晨会转写'
    assert f'filename="{name}"'.encode() in requests[0].content
    assert mime.encode() in requests[0].content


def test_transcribe_file_reference_rejects_unknown_format_and_oversize(tmp_path):
    store = AISettings(tmp_path)
    store.put_provider('p', 'mock', '', '', ['m'], True)
    store.put_route('transcribe', 'p', 'm')

    class FilesWithData(Files):
        def __init__(self, data):
            super().__init__(data=data, name='recording.bin')
            self.reads = 0

        def get_file(self, user, file_id):
            return {'fileId': file_id, 'name': self.name, 'sha256': self.sha, 'size': len(self.data)}

        def read_file(self, user, file_id):
            self.reads += 1
            return super().read_file(user, file_id)

    with pytest.raises(AIError, match='格式') as error:
        Gateway(store, files=FilesWithData(b'not-audio')).call(
            'demo', 'transcribe', {'file_id': 'bad'}, principal='sampleoperator')
    assert error.value.kind == 'bad_input'

    metadata_huge = FilesWithData(b'RIFF' + b'\x00' * 4 + b'WAVE')
    metadata_huge.get_file = lambda user, file_id: {
        'fileId': file_id, 'name': metadata_huge.name, 'sha256': metadata_huge.sha,
        'size': 20 * 1024 * 1024 + 1,
    }
    with pytest.raises(AIError, match='20 MB') as error:
        Gateway(store, files=metadata_huge).call(
            'demo', 'transcribe', {'file_id': 'metadata-huge'}, principal='sampleoperator')
    assert error.value.kind == 'bad_input' and metadata_huge.reads == 0

    huge = b'RIFF' + b'\x00' * 4 + b'WAVE' + b'\x00' * (20 * 1024 * 1024)
    with pytest.raises(AIError, match='20 MB') as error:
        Gateway(store, files=FilesWithData(huge)).call(
            'demo', 'transcribe', {'file_id': 'huge'}, principal='sampleoperator')
    assert error.value.kind == 'bad_input'


# ---------------------------------------------------------------- 一键测试
def test_gateway_test_returns_success_preview_and_elapsed_without_usage(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('ark', 'ark', 'https://ark.example.test/api/v3', 'dummy-key', ['image-model'], True)
    store.put_route('image', 'ark', 'image-model')
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'data': [{'url': 'https://img.example.test/a.png'}]})

    fake_http(monkeypatch, respond)
    outcome = Gateway(store).test('image')
    assert outcome['ok'] is True
    assert outcome['capability'] == 'image' and outcome['provider'] == 'ark' and outcome['model'] == 'image-model'
    assert isinstance(outcome['elapsed_ms'], int) and outcome['elapsed_ms'] >= 0
    assert outcome['summary'] == '生成图片成功，返回 1 张图。'
    assert outcome['preview'] == {'kind': 'image', 'url': 'https://img.example.test/a.png'}
    assert requests[0].headers['authorization'] == 'Bearer dummy-key'
    # 测试不占应用配额，也不写 ai_usage。
    assert store.usage() == []


def test_gateway_test_provider_scope_works_without_route(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('ark', 'ark', 'https://ark.example.test/api/v3', 'dummy-key', ['image-model'], True)
    fake_http(monkeypatch, lambda request: httpx.Response(200, json={'data': [{'url': 'data:image/png;base64,AAAA'}]}))
    outcome = Gateway(store).test('image', provider_id='ark', model='image-model')
    assert outcome['ok'] is True and outcome['provider'] == 'ark'
    assert outcome['preview']['url'] == 'data:image/png;base64,AAAA'
    assert store.usage() == []


@pytest.mark.parametrize('response,reason,message', [
    (httpx.Response(401, json={'error': {'message': 'invalid api key'}}), 'auth', '密钥'),
    (httpx.Response(404, json={'error': {'message': 'The model `m` does not exist'}}), 'model', '模型'),
    (httpx.Response(404, text='not found'), 'endpoint', '接入地址'),
    (httpx.Response(500), 'provider', '服务商'),
])
def test_gateway_test_classifies_provider_failures_in_chinese(tmp_path, monkeypatch, response, reason, message):
    store = AISettings(tmp_path)
    store.put_provider('p', 'openai', 'https://example.test/v1', 'test-placeholder-key', ['m'], True)
    store.put_route('image', 'p', 'm')
    fake_http(monkeypatch, lambda request: response)
    outcome = Gateway(store).test('image')
    assert outcome['ok'] is False and outcome['reason'] == reason
    assert message in outcome['message']
    assert 'test-placeholder-key' not in str(outcome)
    assert store.usage() == []


def test_gateway_test_classifies_connection_failure_as_address(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('p', 'openai', 'https://example.test/v1', 'test-placeholder-key', ['m'], True)
    store.put_route('chat', 'p', 'm')

    def unreachable(request):
        raise httpx.ConnectError('connection refused', request=request)

    fake_http(monkeypatch, unreachable)
    outcome = Gateway(store).test('chat')
    assert outcome['ok'] is False and outcome['reason'] == 'network'
    assert '接入地址' in outcome['message']


def test_gateway_test_reports_unsupported_capability(tmp_path):
    store = AISettings(tmp_path)
    store.put_provider('ds', 'deepseek', 'https://api.deepseek.example.test/v1', 'test-placeholder-key', ['deepseek-chat'], True)
    outcome = Gateway(store).test('image', provider_id='ds', model='deepseek-chat')
    assert outcome['ok'] is False and outcome['reason'] == 'unsupported'
    assert '不支持此能力' in outcome['message']


def test_gateway_test_parse_uses_builtin_valid_pdf_sample(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('mineru', 'mineru', 'https://mineru.example.test/api/v4', 'test-placeholder-key', ['vlm'], True)
    store.put_route('parse', 'mineru', 'vlm')
    archive = result_zip([{'type': 'text', 'text': '测试页', 'page_idx': 0}])
    uploads = []

    def respond(request):
        path = request.url.path
        if path == '/api/v4/file-urls/batch':
            return httpx.Response(200, json={'code': 0, 'data': {'batch_id': 'batch-1', 'file_urls': ['https://upload.example.test/u1']}})
        if request.url.host == 'upload.example.test':
            uploads.append(request.content)
            return httpx.Response(200)
        if path == '/api/v4/extract-results/batch/batch-1':
            return httpx.Response(200, json={'code': 0, 'data': {'extract_result': [{
                'state': 'done', 'full_zip_url': 'https://cdn.example.test/r.zip',
                'extract_progress': {'total_pages': 1}}]}})
        return httpx.Response(200, content=archive)

    fake_http(monkeypatch, respond)
    outcome = Gateway(store).test('parse')
    assert outcome['ok'] is True
    assert outcome['summary'] == '文档解析成功，共 1 页、1 个区块。'
    assert uploads and uploads[0].startswith(b'%PDF-1.4')
    assert store.usage() == []


def test_gateway_test_vision_uses_builtin_png_sample(tmp_path, monkeypatch):
    store = AISettings(tmp_path)
    store.put_provider('vision', 'openai', 'https://vision.example.test/v1', 'test-placeholder-key', ['qwen-vl'], True)
    store.put_route('vision', 'vision', 'qwen-vl')
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"candidates":[{"label":"测试"}]}'}}]})

    fake_http(monkeypatch, respond)
    outcome = Gateway(store).test('vision')
    assert outcome['ok'] is True and outcome['summary'] == '读图识别成功，返回 1 个候选。'
    image = bodies[0]['messages'][1]['content'][1]['image_url']['url']
    assert image.startswith('data:image/png;base64,')
    assert store.usage() == []

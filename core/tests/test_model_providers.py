"""应用实际入口、管理员显示与审计共享同一份模型配置。"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from conftest import set_provider_credential
from haiknow_core.aihub import codex
from haiknow_core.aihub.config import ENVIRONMENT_PROVIDER
from haiknow_sdk import ModelError
from test_aihub_api import _admin_client, _fake_http
from test_model import ark_server

MESSAGES = [{'role': 'user', 'content': '只回复 JKQ_CODEX_OK'}]


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_configured_model_is_used_and_audited(tmp_path, monkeypatch, mode):
    old_client = _admin_client(tmp_path, monkeypatch)
    assert old_client.put('/api/v1/admin/ai/providers/offline',
                          json={'kind': 'mock', 'models': ['offline-model']}).status_code == 200
    assert old_client.put('/api/v1/admin/ai/routes/chat',
                          json={'provider': 'offline', 'model': 'offline-model'}).status_code == 200

    def run(base, requests):
        monkeypatch.setenv('HAIKNOW_MODEL_PROVIDER', mode)
        monkeypatch.setenv('HAIKNOW_MODEL_BASE_URL', base)
        monkeypatch.setenv('HAIKNOW_MODEL_NAME', 'operator-selected-model')
        client = _admin_client(tmp_path, monkeypatch)
        model = client.app.state.platform.model.for_app('sample-app')
        assert model.available
        assert model.chat(MESSAGES) == ('云端桩结果' if mode == 'cloud' else '桩服务真实往返')
        name = requests[0]['body']['model']
        assert name == 'operator-selected-model'
        assert client.get('/api/model/usage').json()['model_name'] == name
        env_route = client.get('/api/v1/admin/ai/routes').json()['items'][0]
        assert env_route['model'] == name and env_route['provider'] == ENVIRONMENT_PROVIDER
        assert client.app.state.platform.model.aihub.settings.stored_routes()[0]['model'] == 'offline-model'
        audit = client.get('/api/audit?app_id=sample-app').json()['items']
        assert next(a['detail'] for a in audit if a['action'] == 'ai.chat') == {
            'provider': ENVIRONMENT_PROVIDER, 'model': name}
        refused = client.put('/api/v1/admin/ai/providers/@environment', json={'kind': 'mock', 'models': ['other']})
        assert refused.status_code == 409
        assert client.delete('/api/v1/admin/ai/routes/chat').status_code == 409
        assert not list(tmp_path.glob('*.key'))

    if mode == 'local':
        with ark_server() as (base, requests):
            monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
            monkeypatch.setenv('http_proxy', 'http://127.0.0.1:1')
            monkeypatch.setenv('NO_PROXY', '')
            monkeypatch.setenv('no_proxy', '')
            run(base, requests)
    else:
        key = 'sample-cloud-credential'
        monkeypatch.setenv('HAIKNOW_MODEL_API_KEY', key)
        requests = []

        def respond(request):
            assert request.url == 'https://cloud.example.test/v1/chat/completions'
            assert request.headers['Authorization'] == f'Bearer {key}'
            requests.append({'body': json.loads(request.content)})
            return httpx.Response(200, json={'choices': [{'message': {'content': '云端桩结果'}}]})

        _fake_http(monkeypatch, respond)
        run('https://cloud.example.test/v1', requests)


def test_managed_provider_needs_pinned_credential_before_network(tmp_path, monkeypatch):
    client = _admin_client(tmp_path, monkeypatch)
    root = '/api/v1/admin/ai'
    base = 'https://managed.example.test/v1'
    payload = {'kind': 'openai', 'base_url': base, 'models': ['managed-model']}
    assert client.put(f'{root}/providers/managed', json=payload).status_code == 200
    assert client.put(f'{root}/routes/chat', json={'provider': 'managed', 'model': 'managed-model'}).status_code == 200
    model = client.app.state.platform.model.for_app('sample-app')
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': '已连接'}}]})

    _fake_http(monkeypatch, respond)
    with pytest.raises(ModelError) as missing:
        model.chat(MESSAGES)
    assert missing.value.kind == 'not_configured'
    assert requests == []
    assert client.get(f'{root}/providers').json()['items'][0]['has_key'] is False
    key = 'sample-managed-credential'
    set_provider_credential(monkeypatch, 'managed', base, key)
    assert model.chat(MESSAGES) == '已连接'
    assert requests[0].headers['Authorization'] == f'Bearer {key}'
    response = client.get(f'{root}/providers')
    assert key not in response.text
    assert response.json()['items'][0]['api_key'] == '********'
    assert client.put(f'{root}/providers/managed', json={**payload, 'base_url': 'https://other.example.test/v1'}).status_code == 200
    assert not model.available
    with pytest.raises(ModelError) as moved:
        model.chat(MESSAGES)
    assert moved.value.kind == 'not_configured' and len(requests) == 1


def test_codex_process_is_text_only_and_receives_no_provider_key(tmp_path, monkeypatch):
    monkeypatch.setenv('HAIKNOW_MODEL_PROVIDER', 'codex-cli')
    monkeypatch.setenv('HAIKNOW_MODEL_NAME', 'configured-cli-model')
    monkeypatch.setenv('HAIKNOW_MODEL_API_KEY', 'sample-provider-credential')
    monkeypatch.setenv('OPENAI_API_KEY', 'sample-unrelated-credential')
    calls = []

    async def run(command, *, input, env, cwd, stderr, check):
        calls.append(command)
        assert command[command.index('--model') + 1] == 'configured-cli-model'
        assert '--ephemeral' in command and '--ignore-user-config' in command
        assert ('--disable', 'shell_tool') in list(zip(command, command[1:]))
        assert command[-1] == '-' and b'JKQ_CODEX_OK' in input
        assert 'HAIKNOW_MODEL_API_KEY' not in env and 'OPENAI_API_KEY' not in env
        assert stderr == subprocess.DEVNULL and not check
        assert list(Path(cwd).iterdir()) == []
        return subprocess.CompletedProcess(command, 0, stdout=b'JKQ_CODEX_OK\n')

    monkeypatch.setattr(codex.shutil, 'which', lambda name: '/test-only/codex')
    monkeypatch.setattr(codex, 'run_process', run)
    client = _admin_client(tmp_path, monkeypatch)
    model = client.app.state.platform.model.for_app('sample-app')
    with pytest.raises(ModelError) as denied:
        model.chat(MESSAGES, classification='internal')
    assert denied.value.kind == 'outbound_denied'
    assert calls == []
    assert model.chat(MESSAGES, classification='public') == 'JKQ_CODEX_OK'
    monkeypatch.setattr(codex.shutil, 'which', lambda name: None)
    with pytest.raises(ModelError) as missing:
        model.chat(MESSAGES, classification='public')
    assert missing.value.kind == 'not_configured'
    assert len(calls) == 1


def test_real_codex_cli_smoke(tmp_path, monkeypatch):
    if not shutil.which('codex'):
        pytest.skip('未安装 Codex CLI')
    name = os.environ.get('JKQ_CODEX_SMOKE_MODEL')
    if not name:
        pytest.skip('设置 JKQ_CODEX_SMOKE_MODEL 后才运行本机实际调用')
    monkeypatch.setenv('HAIKNOW_MODEL_PROVIDER', 'codex-cli')
    monkeypatch.setenv('HAIKNOW_MODEL_NAME', name)
    client = _admin_client(tmp_path, monkeypatch)
    model = client.app.state.platform.model.for_app('sample-app')
    result = model.chat(MESSAGES, classification='public')
    assert result == 'JKQ_CODEX_OK', '应收到预期的合成回执'
    assert client.get('/api/model/usage').json()['model_name'] == name
    version = subprocess.check_output(['codex', '--version'], text=True).strip()
    print(f'{version} | provider=codex-cli | model={name} | result={result}')

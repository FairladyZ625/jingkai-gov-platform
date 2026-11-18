"""转写回归，CI 只使用本地 HTTP 桩和合成音频。"""

import asyncio
import io
import json
import os
import secrets
import shutil
import sys
import wave
from email import policy
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip('fastapi', reason='转写集成测试需要 requirements-dev.txt')

import httpx
from fastapi.testclient import TestClient

from haiknow_core.aihub import transcribe_funasr
from haiknow_core.aihub.transcribe import RETRIES, Sentence, transcribe_chunk
from haiknow_core.aihub.transcribe_audio import (
    SAMPLE_RATE, TRANSCRIBE_MAX_BYTES, WAV_HEADER_BYTES, TranscribeError, split_audio,
)
from jkq import routers, transcribe
from jkq.app import create_app

DEMO = Path(__file__).resolve().parents[4] / 'tests/fixtures/audio/demo-meeting.webm'
PATH = '/api/v1/ai/transcribe'
TEST_KEY = 'asr-test-placeholder'


def wav_audio(frames, sample=b'\x00\x00', *, channels=1):
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setparams((channels, 2, SAMPLE_RATE, 0, 'NONE', 'not compressed'))
        wav.writeframes(sample * (frames * channels))
    return output.getvalue()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith('JKQ_TRANSCRIBE_'):
            monkeypatch.delenv(name)


@pytest.fixture
def local_config(monkeypatch):
    monkeypatch.setenv('JKQ_TRANSCRIBE_LOCAL_URL', 'https://speech.example.test/recognition')
    monkeypatch.setenv('JKQ_TRANSCRIBE_LOCAL_MODEL', 'configured-model')


def multipart(request):
    data = f'MIME-Version: 1.0\r\nContent-Type: {request.headers["content-type"]}\r\n\r\n'.encode()
    parts = BytesParser(policy=policy.default).parsebytes(data + request.content)
    return {part.get_param('name', header='content-disposition'): part.get_payload(decode=True) for part in parts.iter_parts()}


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='WebM 演示录音需 FFmpeg 解码')
def test_demo_audio_via_mock_service_keeps_speakers_timestamps_and_hotwords(monkeypatch, local_config):
    monkeypatch.setenv('JKQ_TRANSCRIBE_LOCAL_API_KEY', TEST_KEY)
    monkeypatch.setenv('JKQ_TRANSCRIBE_HOTWORDS', '配置信息中心\n北京经济技术开发区行政审批局')
    names = ['北京经济技术开发区管理委员会', '北京经济技术开发区行政审批局']

    def asr(request):
        assert str(request.url) == 'https://speech.example.test/recognition'
        assert request.headers['authorization'] == f'Bearer {TEST_KEY}'
        fields = multipart(request)
        assert fields['model'] == b'configured-model'
        assert fields['audio'].startswith(b'RIFF')
        with wave.open(io.BytesIO(fields['audio'])) as wav:
            duration = wav.getnframes() / wav.getframerate()
            assert 180 <= duration <= 300
        hotwords = fields['hotword'].decode().split()
        assert hotwords.count(names[1]) == 1
        assert '配置信息中心' in hotwords
        return httpx.Response(200, json={'code': 0, 'sentences': [
            {'text': name if name in hotwords else '机构名识别错误', 'start': 1000 + i * 900,
             'end': 1700 + i * 900, 'spk': spk}
            for i, (name, spk) in enumerate(zip(names, (2, 7)))
        ]})

    adapter = transcribe.transcriber_from_environment(transport=httpx.MockTransport(asr))
    result = asyncio.run(adapter.transcribe(DEMO.read_bytes()))
    assert result['source'] == 'local' and result['mock'] is False and result['chunkCount'] == 1
    assert result['sentences'] == [
        {'text': names[0], 'startMs': 1000, 'endMs': 1700, 'speaker': 'S1'},
        {'text': names[1], 'startMs': 1900, 'endMs': 2600, 'speaker': 'S2'},
    ]


def test_over_20_mib_chunks_use_same_timeline_and_deduplicate_only_the_overlap():
    capacity = (TRANSCRIBE_MAX_BYTES - WAV_HEADER_BYTES) // 2
    assert len(split_audio(wav_audio(capacity))) == 1
    audio = wav_audio(capacity + 1, b'\x12\x34')
    chunks = split_audio(audio)
    assert len(audio) == TRANSCRIBE_MAX_BYTES + 2
    assert len(chunks) == 2 and all(len(chunk.data) <= TRANSCRIBE_MAX_BYTES for chunk in chunks)
    first, second = chunks
    assert first.frames > second.offset_frames and second.offset_frames + second.frames == capacity + 1
    seam = second.offset_ms

    class Provider:
        def __init__(self):
            self.calls = 0

        async def transcribe(self, audio, hotwords):
            self.calls += 1
            if self.calls == 1:
                assert audio == first.data
                return [
                    Sentence('前段发言', seam - 500, seam - 100, 'x'),
                    Sentence('边界样本。', seam + 100, seam + 800, 'x'),
                ]
            assert audio == second.data
            return [
                Sentence('边界样本', 110, 805, 'z'),
                Sentence('后段发言', 900, 1500, 'z'),
                Sentence('边界样本', 2300, 2900, 'q'),
            ]

    provider = Provider()
    result = asyncio.run(transcribe.Transcriber('local', provider).transcribe(audio))
    assert provider.calls == result['chunkCount'] == 2
    assert [(s['text'], s['startMs'], s['endMs'], s['speaker']) for s in result['sentences']] == [
        ('前段发言', seam - 500, seam - 100, 'S1'),
        ('边界样本。', seam + 100, seam + 800, 'S1'),
        ('后段发言', seam + 900, seam + 1500, 'S1'),
        ('边界样本', seam + 2300, seam + 2900, 'S2'),
    ]


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='立体声 WAV 需 FFmpeg 标准化')
def test_input_above_limit_still_splits_after_downmix():
    resampled = split_audio(wav_audio(18000, channels=2), max_bytes=64044)
    assert len(resampled) == 2
    assert resampled[-1].offset_frames + resampled[-1].frames == 18000
    assert all(len(chunk.data) <= 64044 for chunk in resampled)


def test_missing_key_returns_preset_even_with_local_endpoint(local_config):
    def forbidden(request):
        pytest.fail('预置模式向转写服务发起了请求')

    adapter = transcribe.transcriber_from_environment(transport=httpx.MockTransport(forbidden))
    result = asyncio.run(adapter.transcribe(wav_audio(SAMPLE_RATE)))
    assert result['mock'] is True and result['source'] == 'preset' and result['sentences']
    assert result['sentences'][-1]['endMs'] <= result['durationMs']


@pytest.mark.parametrize(('failure', 'status', 'code'), [
    ('timeout', 504, 'TRANSCRIBE_TIMEOUT'),
    ('upstream', 502, 'TRANSCRIBE_PROVIDER_ERROR'),
    ('bad-speaker', 502, 'TRANSCRIBE_PROVIDER_ERROR'),
    ('bad-time', 502, 'TRANSCRIBE_PROVIDER_ERROR'),
    ('redirect', 502, 'TRANSCRIBE_PROVIDER_ERROR'),
])
def test_provider_failure_retries_three_times_and_sanitizes_error(monkeypatch, local_config, failure, status, code):
    monkeypatch.setenv('JKQ_TRANSCRIBE_LOCAL_API_KEY', TEST_KEY)
    requests = []

    def asr(request):
        requests.append(request)
        if failure == 'timeout':
            raise httpx.ReadTimeout(f'上游详情含凭据 {TEST_KEY}', request=request)
        if failure == 'upstream':
            return httpx.Response(503, text=f'上游详情含凭据 {TEST_KEY}')
        if failure == 'redirect':
            return httpx.Response(307, headers={'Location': 'https://other.example.test/'})
        if failure == 'bad-speaker':
            return httpx.Response(200, json={'code': 0, 'sentences': [{'text': '缺少说话人', 'start': 0, 'end': 500}]})
        return httpx.Response(200, json={'code': 0, 'sentences': [
            {'text': '时间超出分片', 'start': 0, 'end': 1001, 'spk': 0},
        ]})

    adapter = transcribe.transcriber_from_environment(transport=httpx.MockTransport(asr))
    with pytest.raises(TranscribeError) as raised:
        asyncio.run(adapter.transcribe(wav_audio(SAMPLE_RATE)))
    assert len(requests) == 4 == RETRIES + 1
    assert all(request.url.host == 'speech.example.test' for request in requests)
    error = raised.value
    assert error.status == status and error.code == code and str(error)
    assert error.error['details'] == {'attempts': 4}
    assert TEST_KEY not in str(error) and 'example.test' not in str(error)


def test_late_provider_attempt_succeeds(monkeypatch, local_config):
    monkeypatch.setenv('JKQ_TRANSCRIBE_LOCAL_API_KEY', TEST_KEY)
    statuses = iter([500, 502, 503, 200])
    adapter = transcribe.transcriber_from_environment(transport=httpx.MockTransport(
        lambda req: httpx.Response(next(statuses), json={'code': 0, 'sentences': []}),
    ))
    assert asyncio.run(adapter.transcribe(wav_audio(SAMPLE_RATE)))['sentences'] == []


def test_attempt_has_a_wall_clock_deadline():
    class HangingProvider:
        async def transcribe(self, audio, hotwords):
            await asyncio.sleep(60)

    chunk, = split_audio(wav_audio(SAMPLE_RATE))
    with pytest.raises(TranscribeError, match='超时') as raised:
        asyncio.run(asyncio.wait_for(transcribe_chunk(HangingProvider(), chunk, timeout=0.001), timeout=1))
    assert raised.value.status == 504 and raised.value.error['details']['attempts'] == 4


def test_cloud_slot_has_no_default_transport_and_rejects_confidential(monkeypatch):
    for key, value in {
        'MODE': 'cloud',
        'CLOUD_PROVIDER': 'pending',
        'CLOUD_URL': 'https://cloud.example.test/asr',
        'CLOUD_MODEL': 'future-model',
    }.items():
        monkeypatch.setenv('JKQ_TRANSCRIBE_' + key, value)
    assert transcribe.transcriber_from_environment().source == 'preset'
    monkeypatch.setenv('JKQ_TRANSCRIBE_CLOUD_API_KEY', TEST_KEY)
    with pytest.raises(TranscribeError, match='暂未接入') as raised:
        transcribe.transcriber_from_environment()
    assert raised.value.status == 503

    marker = object()

    def factory(url, model, key):
        assert (url, model, key) == ('https://cloud.example.test/asr', 'future-model', TEST_KEY)
        return marker

    registry = {'pending': factory}
    with pytest.raises(TranscribeError, match='机密') as denied:
        transcribe.transcriber_from_environment(classification='confidential', cloud_providers=registry)
    assert denied.value.status == 403 and denied.value.code == 'OUTBOUND_DENIED'
    assert transcribe.transcriber_from_environment(cloud_providers=registry).provider is marker


def test_mock_model_serves_native_funasr_http_contract(monkeypatch, local_config):
    for key, value in {'VAD_MODEL': 'vad', 'PUNC_MODEL': 'punc', 'SPK_MODEL': 'spk', 'API_KEY': TEST_KEY}.items():
        monkeypatch.setenv('JKQ_TRANSCRIBE_LOCAL_' + key, value)

    def model_factory(**settings):
        assert settings['model'] == 'configured-model' and settings['spk_model'] == 'spk'
        return object()

    monkeypatch.setitem(sys.modules, 'funasr', SimpleNamespace(AutoModel=model_factory))

    def fake_speech(engine, audio, hotword):
        assert '北京经济技术开发区行政审批局' in hotword
        return {'code': 0, 'sentences': [{'text': '样例', 'start': 0, 'end': 550, 'spk': 42}]}

    monkeypatch.setattr(transcribe_funasr, '_speech', fake_speech)
    app = transcribe_funasr.create_app()
    with TestClient(app) as client:
        response = client.post('/recognition', files={'audio': ('a.wav', wav_audio(SAMPLE_RATE))}, data={'model': 'configured-model'})
    assert response.status_code == 401
    adapter = transcribe.transcriber_from_environment(transport=httpx.ASGITransport(app=app))
    result = asyncio.run(adapter.transcribe(wav_audio(SAMPLE_RATE)))
    assert result['sentences'] == [{'text': '样例', 'startMs': 0, 'endMs': 550, 'speaker': 'S1'}]


def seed_password_users(app, password, users):
    from haiknow_core.passwords import hash_password

    digest = hash_password(password)
    store = app.state.platform.store
    with store._lock, store._db as db:
        store.begin_write()
        for uid, role in users.items():
            db.execute(
                "insert or ignore into users (id,username,name,password_hash,status,last_login,failed_logins,"
                "locked_until,demo,all_projects,session_gen) values (?,?,?,?,'active',null,0,0,0,0,0)",
                (uid, uid, uid, digest),
            )
            db.execute("update users set username=?, password_hash=?, status='active' where id=?", (uid, digest, uid))
            db.execute("insert or ignore into roles values (?,?,1)", (role, role))
            db.execute("insert or ignore into user_roles values (?,?)", (uid, role))
            db.execute("insert or ignore into project_members values (?,?)", ('jkq', uid))


def test_instance_route_uses_core_file_permissions_and_v1_error_envelope(monkeypatch, isolated_platform):
    config, _ = isolated_platform
    (config / 'projects.yaml').write_text(
        '{"companies":[{"id":"test","name":"演示机构","projects":[{"id":"jkq","name":"演示项目"}]}]}',
        encoding='utf-8',
    )
    monkeypatch.setenv('HAIKNOW_SECRET', 'jkq-test-session-signing')
    monkeypatch.delenv('HAIKNOW_DEMO_LOGIN', raising=False)  # 经开区实例走真实口令登录（#78）
    monkeypatch.delenv('JKQ_DEMO_MODE', raising=False)
    (config / 'roles.yaml').write_text(json.dumps({'apps': ['sample-app'], 'roles': {
        'admin': {'name': '管理员', 'desc': '测试', 'mask': False,
                  'grants': {'*': ['view', 'operate', 'approve', 'admin']}},
        'sampleextra': {'name': '样例协审员', 'desc': '测试', 'mask': False,
                        'grants': {'sample-app': ['view', 'approve']}},
    }}, ensure_ascii=False), encoding='utf-8')
    assert transcribe.router in routers.ROUTERS
    app = create_app()
    password = secrets.token_urlsafe(12)
    seed_password_users(app, password, {'sampleadmin': 'admin', 'sampleextra': 'sampleextra'})

    def login(uid):
        return client.post('/api/v1/auth/login', json={'username': uid, 'password': password})

    with TestClient(app) as client:
        body = {'appId': 'sample-app', 'fileId': 'not-found'}
        assert client.post(PATH, json=body).status_code == 401
        assert login('sampleadmin').status_code == 200
        assert client.post(PATH, json=body).status_code == 404

        def upload(audio):
            response = client.post('/api/v1/files', files={'file': ('演示', audio)}, data={
                'app': 'sample-app', 'project': 'jkq', 'purpose': 'transcribe',
            })
            assert response.status_code == 201, response.text
            return {**body, 'fileId': response.json()['fileId']}

        unsupported = client.post(PATH, json=upload(b'%PDF-1.4\n'))
        assert unsupported.status_code == 415
        assert unsupported.json() == {'error': {
            'code': 'UNSUPPORTED_TYPE',
            'message': '无法读取音频，请上传有效的 WAV、WebM、M4A、OGG、MP3 或 FLAC 文件。',
            'details': {},
        }}
        valid = upload(wav_audio(SAMPLE_RATE))
        preset = client.post(PATH, json=valid)
        assert preset.status_code == 200, preset.text
        assert preset.json()['mock'] and preset.json()['source'] == 'preset'
        assert login('sampleextra').status_code == 200
        assert client.post(PATH, json=valid).status_code == 403
        items = client.app.state.platform.store.audit_list('sample-app')
        attempts = [item['detail'] for item in items if item['action'] == 'ai.transcribe']
        assert [a['status'] for a in attempts] == ['forbidden', 'success', 'UNSUPPORTED_TYPE', 'not_found']
        assert attempts[1]['source'] == 'preset'

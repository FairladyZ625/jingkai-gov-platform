"""会议上传、轮询、重试、重启和权限的真实 HTTP 回归。"""
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from apps.meeting.tests.isolated_instance import (
    JOBS, MEETING, MEETINGS, ROOT, create_instance, fixture_environment, job_snapshot,
    login, submit_demo, transcription_module, wait_job,
)
from haiknow_sdk import DataError


@pytest.fixture
def client(tmp_path, monkeypatch):
    for name, value in fixture_environment(tmp_path).items():
        monkeypatch.setenv(name, value)
    with TestClient(create_instance()) as instance:
        login(instance)
        yield instance


def upload(client, **kwargs):
    return client.post(MEETINGS, data={'title': '测试会议', 'participants': '["张三"]', **kwargs},
                       files={'file': ('公开演示.webm', sample_audio(), 'audio/webm')})


def sample_audio():
    return (MEETING / 'samples/demo.webm').read_bytes()


def test_upload_creates_record_and_polls_monotonic_progress(client, monkeypatch):
    module = transcription_module()
    original = module.transcribe_part
    release = Event()
    entered = Event()

    def pause_second(part, **options):
        if part['number'] == 2:
            entered.set()
            assert release.wait(6)
        return original(part, **options)

    monkeypatch.setattr(module, 'transcribe_part', pause_second)
    create = upload(client)
    assert create.status_code == 201, create.text
    item = create.json()['item']
    assert item['status'] == 'new' and item['participants'] == ['张三']
    assert item['size'] == len(sample_audio())
    assert client.get(f"/api/v1/files/{item['fileId']}/content").content == sample_audio()
    url = f"{MEETINGS}/{item['id']}/transcribe"
    try:
        accepted = client.post(url, json={'title': '已上传会议', 'type': '局务会', 'hotwords': ['园区']})
        assert accepted.status_code == 202, accepted.text
        job = accepted.json()['job']
        assert (job['ref'], job['kind'], job['status'], job['progress']) == (item['id'], 'transcribe', 'running', 0)
        assert entered.wait(6)
        running = job_snapshot(client, job['id'])
        assert running['status'] == 'running' and running['stepName'] == '转写第 2 片'
        assert 0 < running['progress'] < 100
    finally:
        release.set()
    samples = [job, running, *wait_job(client, job['id'], lambda job: job['status'] == 'done')]
    progress = [sample['progress'] for sample in samples]
    assert progress == sorted(progress) and progress[-1] == 100
    assert samples[-1]['steps'] == ['分片', '转写第 1 片', '转写第 2 片', '合并逐字稿']
    detail = client.get(f"{MEETINGS}/{item['id']}").json()
    assert detail['minutes'] is None
    finished = detail['item']
    assert finished['title'] == '已上传会议' and finished['type'] == '局务会'
    assert finished['jobId'] == job['id'] and finished['status'] == 'done'
    assert finished['transcriptMode'] == 'demo'
    first, second = finished['transcript']
    assert first == ['00:00', '发言人 1', '我们先核对园区服务清单。请把本周收集的问题按主题归类。']
    assert second[:2] == ['00:05.716', '发言人 2']
    assert client.get(finished['transcriptAudio']).content == sample_audio()
    result = client.get(MEETINGS, params={'limit': 1}).json()
    assert result['total'] == 1 and result['items'][0]['status'] == 'done'
    assert 'transcript' not in result['items'][0]
    assert client.get(MEETINGS, params={'offset': 1}).json()['items'] == []


def test_retry_reuses_first_shard_and_preserves_step_key(client, monkeypatch):
    module = transcription_module()
    original = module.transcribe_part
    calls = []

    def fail_once(part, **options):
        calls.append((part['number'], options['step_key']))
        if len(calls) == 2:
            raise DataError('internal_error', '测试分片故障')
        return original(part, **options)

    monkeypatch.setattr(module, 'transcribe_part', fail_once)
    meeting_id, job_id = submit_demo(client)
    failed = wait_job(client, job_id, lambda job: job['status'] == 'failed')[-1]
    assert failed['step'] == 2 and failed['stepName'] == '转写第 2 片'
    assert client.get(f'{MEETINGS}/{meeting_id}').json()['item']['transcript'] == []
    before = job_snapshot(client, job_id, raw=True)
    retry = client.post(f'{JOBS}/{job_id}/retry?app=meeting')
    assert retry.status_code == 202 and retry.json()['id'] == job_id
    samples = [failed, *wait_job(client, job_id, lambda job: job['status'] == 'done')]
    progress = [sample['progress'] for sample in samples]
    assert progress == sorted(progress) and progress[-1] == 100
    after = job_snapshot(client, job_id, raw=True)
    assert after['attempt'] == 2 and before['steps'][:2] == after['steps'][:2]
    assert [number for number, _ in calls] == [1, 2, 2]
    assert calls[-1] == calls[-2]
    assert client.post(f'{JOBS}/{job_id}/retry?app=meeting').status_code == 409


def test_concurrent_idempotency_and_key_conflicts(client):
    def submit(meeting_id, **kwargs):
        return client.post(f'{MEETINGS}/{meeting_id}/transcribe',
                           headers={'Idempotency-Key': 'same-key'}, **kwargs)

    first = upload(client).json()['item']['id']
    second = upload(client).json()['item']['id']
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(submit, [first] * 6))
    assert all(response.status_code == 202 for response in responses)
    ids = {response.json()['job']['id'] for response in responses}
    assert len(ids) == 1
    assert len(client.get(JOBS).json()['items']) == 1
    for response in (submit(second), submit(first, json={'title': '其他参数'})):
        assert response.status_code == 409 and response.json()['error']['code'] == 'INVALID_STATE'
    assert submit(first).json()['job']['id'] == ids.pop()


def test_demo_uses_file_and_preset_result(client):
    meeting_id, job_id = submit_demo(client)
    assert wait_job(client, job_id, lambda job: job['status'] == 'done')[-1]['progress'] == 100
    item = client.get(f'{MEETINGS}/{meeting_id}').json()['item']
    assert item['file'] == 'demo.webm' and item['source'] == 'demo'
    assert item['transcriptMode'] == 'demo' and len(item['transcript']) == 2
    assert client.get(f"/api/v1/files/{item['fileId']}/content").content == sample_audio()
    audio = client.get(item['transcriptAudio'], headers={'Range': 'bytes=0-63'})
    assert audio.status_code == 206 and audio.content == sample_audio()[:64]


def test_invalid_values_and_limits(client, monkeypatch):
    module = sys.modules['haiknow_apps.meeting.meetings']
    assert upload(client, participants='[24]').status_code == 422
    assert upload(client, type='无效类型').status_code == 422
    assert client.post(MEETINGS, data={'title': '无文件'}).status_code == 422
    for name, content in [('音频.exe', sample_audio()), ('音频.webm', b'bad'), ('空录音.webm', b'')]:
        response = client.post(MEETINGS, data={'title': '错误录音'},
                               files={'file': (name, content, 'audio/webm')})
        assert response.status_code == 422 and response.json()['error']['code'] == 'INVALID_REQUEST'

    monkeypatch.setattr(module, 'MAX_AUDIO_BYTES', len(sample_audio()) - 1)
    oversized = upload(client)
    assert oversized.status_code == 413 and oversized.json()['error']['code'] == 'INVALID_REQUEST'
    assert client.get(MEETINGS).json()['total'] == 0
    missing = client.post(f'{MEETINGS}/absent/transcribe')
    assert missing.status_code == 404 and missing.json()['error']['code'] == 'NOT_FOUND'
    monkeypatch.setattr(module, 'MAX_AUDIO_BYTES', len(sample_audio()))
    item = upload(client).json()['item']
    url = f"{MEETINGS}/{item['id']}/transcribe"
    assert client.post(url, headers={'Idempotency-Key': ' '}).status_code == 422
    assert client.post(url, headers={'Idempotency-Key': 'a' * 201}).status_code == 422
    assert client.post(url, json={'hotwords': [' ']}).status_code == 422


def test_views_and_writes_require_session_and_authorization(client):
    meeting_id, job_id = submit_demo(client)
    url = f'{MEETINGS}/{meeting_id}'
    assert client.get('/api/apps/meeting/transcription').status_code == 200
    client.cookies.clear()
    assert client.get(url).json()['error']['code'] == 'UNAUTHENTICATED'
    login(client, 'meeting-reader')
    response = client.post(f'{url}/transcribe')
    assert response.status_code == 403 and response.json()['error']['code'] == 'FORBIDDEN'
    assert upload(client).status_code == 403
    assert 'jobId' not in client.get(url).json()['item']
    assert client.get(f'{JOBS}/{job_id}').status_code == 404
    login(client, 'meeting-outsider')
    assert client.get(url).status_code == 404
    assert upload(client).status_code == 403


CHILD = """
import json, sys, time
from pathlib import Path
from fastapi.testclient import TestClient
from apps.meeting.tests.isolated_instance import (
    MEETINGS, create_instance, login, submit_demo, transcription_module, wait_job,
)

mode, statefile = sys.argv[1:]
statefile = Path(statefile)
app = create_instance()
module = transcription_module()
original = module.transcribe_part
observed = []

def observe(part, **options):
    observed.append(part['number'])
    if mode == 'first' and part['number'] == 2:
        time.sleep(60)
    return original(part, **options)

module.transcribe_part = observe
with TestClient(app) as client:
    login(client)
    if mode == 'first':
        meeting, job = submit_demo(client)
        before = wait_job(client, job, lambda job: len(job['steps']) == 3 and
                          job['steps'][2]['status'] == 'running' and observed == [1, 2],
                          raw=True)[-1]
        pending = statefile.with_suffix('.tmp')
        pending.write_text(json.dumps({'meeting': meeting, 'before': before}))
        pending.replace(statefile)
        time.sleep(60)
    else:
        state = json.loads(statefile.read_text())
        meeting, job = state['meeting'], state['before']['id']
        after = wait_job(client, job, lambda job: job['status'] == 'done', raw=True)[-1]
        assert after['steps'][:2] == state['before']['steps'][:2]
        assert after['steps'][2]['key'] == state['before']['steps'][2]['key']
        assert after['attempt'] == 1
        assert observed == [2], observed
        assert len(client.get(f'{MEETINGS}/{meeting}').json()['item']['transcript']) == 2
        assert client.get(f'/api/v1/jobs/{job}').json()['job']['progress'] == 100
"""


def test_process_restart_skips_the_completed_shard(tmp_path):
    env = {**os.environ, **fixture_environment(tmp_path),
           'PYTHONPATH': os.pathsep.join(map(str, (ROOT, ROOT / 'core/server', ROOT / 'core/sdk')))}
    statefile = tmp_path / 'job.json'
    cmd = [sys.executable, '-c', CHILD]
    output = tmp_path / 'first-process.log'
    with output.open('w') as log:
        child = subprocess.Popen([*cmd, 'first', str(statefile)], env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline and child.poll() is None and not statefile.is_file():
                time.sleep(.02)
            assert statefile.is_file(), output.read_text()
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
    assert child.returncode < 0
    state = json.loads(statefile.read_text())
    assert state['before']['steps'][1]['status'] == 'done'
    result = subprocess.run([*cmd, 'resume', str(statefile)], env=env, capture_output=True, text=True, timeout=16)
    assert result.returncode == 0, result.stdout + result.stderr

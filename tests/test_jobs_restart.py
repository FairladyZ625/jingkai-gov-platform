"""在独立进程中强制终止，再重启真实 FastAPI 生命周期验证 SQLite 恢复。"""
import json
import os
import subprocess
import sys
import time

import pytest

from conftest import ROOT
from test_jobs import ROUTER


RESTART_OPERATION = '''
@operation('restart', version='1')
def restart(job, body):
    def save(key):
        job.context.kv.put('saved', job.context.kv.get('saved', 0) + 1)
        return {'key': key, 'value': 19}
    saved = job.step('saved', save)
    def finish(key):
        while not job.context.kv.get('release', False):
            job.check_cancelled()
            time.sleep(.02)
        return saved
    return job.step('finish', finish)
'''

CHILD = '''
import json, sys, time
from pathlib import Path
from fastapi.testclient import TestClient
from haiknow_core.main import create_app

mode, marker = sys.argv[1:]
app = create_app()
with TestClient(app) as c:
    c.post('/api/auth/login', json={'user_id': 'sampleoperator'})
    if mode == 'first':
        r = c.post('/api/v1/jobs', json={'appId': 'restart-app', 'project': 'sample-project',
                   'operation': 'restart', 'input': {}, 'idempotencyKey': 'persisted'})
        assert r.status_code == 202, r.text
        jid = r.json()['id']
    else:
        jid = next(d['id'] for d in c.get('/api/v1/jobs').json()['items'] if d['idempotencyKey'] == 'persisted')
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        doc = c.get('/api/v1/jobs/' + jid).json()
        ready = (mode == 'first' and len(doc['steps']) == 2 and doc['steps'][0]['status'] == 'done'
                 and doc['steps'][1]['status'] == 'running') or (mode == 'resume' and doc['status'] in ('done', 'cancelled', 'failed'))
        if ready:
            if mode == 'first':
                # 额外提交的任务用于核对重启后结果与防重复状态。
                queued = c.post('/api/v1/jobs', json={'appId': 'restart-app', 'project': 'sample-project',
                            'operation': 'demo', 'input': {'value': 23}, 'idempotencyKey': 'queued'})
                assert queued.status_code == 202
                doc['queuedId'] = queued.json()['id']
            Path(marker).write_text(json.dumps(doc))
            break
        time.sleep(.01)
    else:
        raise AssertionError(doc)
    if mode == 'first':
        time.sleep(20)
'''


def start_child(tmp_path, monkeypatch):
    apps = tmp_path / 'apps'
    p = apps / 'restart-app'
    (p / 'api').mkdir(parents=True)
    manifest = json.loads((ROOT / 'tests/fixtures/platform-app/app.json').read_text())
    (p / 'app.json').write_text(json.dumps({**manifest, 'id': 'restart-app'}))
    (p / 'api/router.py').write_text(ROUTER + RESTART_OPERATION)
    monkeypatch.setenv('HAIKNOW_APPS_DIR', str(apps))
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path / 'data'))
    env = {**os.environ, 'HAIKNOW_ROOT': str(ROOT), 'HAIKNOW_NO_AUTOAPP': '1',
           'PYTHONPATH': os.pathsep.join([str(ROOT / 'core/server'), str(ROOT / 'core/sdk')])}
    marker = tmp_path / 'first.json'
    process = subprocess.Popen([sys.executable, '-c', CHILD, 'first', str(marker)], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 10
    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(.01)
    if not marker.exists():
        process.kill()
        out, err = process.communicate(timeout=5)
        pytest.fail('子进程未写检查点：' + out + err)
    return process, json.loads(marker.read_text()), env


@pytest.mark.parametrize('cancel', [False, True], ids=['resume-running', 'finish-cancelling'])
def test_force_kill_then_restart_preserves_steps_and_identity(tmp_path, monkeypatch, cancel):
    process, before, env = start_child(tmp_path, monkeypatch)
    try:
        from fastapi.testclient import TestClient
        from haiknow_core.main import create_app
        # 不进入 lifespan，仅操作同一数据库，不启动第二个执行器。
        c = TestClient(create_app())
        c.post('/api/auth/login', json={'user_id': 'sampleoperator'})
        if cancel:
            assert c.post('/api/v1/jobs/' + before['id'] + '/cancel').json()['status'] == 'cancelling'
        # 只终止测试创建的子进程，不涉及任何宿主服务。
        process.kill()
        process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    store = c.app.state.platform.store
    assert store.kv_get('restart-app', 'saved') == 1
    store.kv_put('restart-app', 'release', True)
    marker = tmp_path / 'resumed.json'
    resumed = subprocess.run([sys.executable, '-c', CHILD, 'resume', str(marker)],
                             env=env, capture_output=True, text=True, timeout=12)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    after = c.get('/api/v1/jobs/' + before['id']).json()
    assert after['status'] == ('cancelled' if cancel else 'done')
    assert after['id'] == before['id'] and after['attempt'] == 1
    assert after['steps'][0] == before['steps'][0]
    assert store.kv_get('restart-app', 'saved') == 1
    if not cancel:
        assert after['result'] == before['steps'][0]['result']
    assert c.get('/api/v1/jobs/' + before['queuedId']).json()['result']['value'] == 23
    notes = c.get('/api/v1/jobs/notifications').json()['items']
    assert len([n for n in notes if n['jobId'] == before['id']]) == 1
    # 防重复与已读状态跨进程持久化。
    duplicate = c.post('/api/v1/jobs', json={'appId': 'restart-app', 'project': 'sample-project',
                       'operation': 'restart', 'input': {}, 'idempotencyKey': 'persisted'})
    assert duplicate.status_code == 202 and duplicate.json()['id'] == before['id']
    note = next(n for n in notes if n['jobId'] == before['id'])
    assert c.post('/api/v1/jobs/notifications/' + note['id'] + '/read').json()['read']
    next_client = TestClient(create_app())
    next_client.post('/api/auth/login', json={'user_id': 'sampleoperator'})
    assert before['id'] not in {n['jobId'] for n in next_client.get('/api/v1/jobs/notifications').json()['items']}


def test_accepted_queue_survives_new_process_before_worker_start(make_client, tmp_path, monkeypatch):
    apps = tmp_path / 'apps'
    p = apps / 'restart-app'
    (p / 'api').mkdir(parents=True)
    manifest = json.loads((ROOT / 'tests/fixtures/platform-app/app.json').read_text())
    (p / 'app.json').write_text(json.dumps({**manifest, 'id': 'restart-app'}))
    (p / 'api/router.py').write_text(ROUTER)
    monkeypatch.setenv('HAIKNOW_APPS_DIR', str(apps))
    c = make_client(apps)
    c.post('/api/auth/login', json={'user_id': 'sampleoperator'})
    job = c.post('/api/v1/jobs', json={'appId': 'restart-app', 'project': 'sample-project',
                 'operation': 'demo', 'input': {'value': 29}, 'idempotencyKey': 'persisted'}).json()
    assert job['status'] == 'queued'
    env = {**os.environ, 'HAIKNOW_ROOT': str(ROOT), 'HAIKNOW_NO_AUTOAPP': '1',
           'PYTHONPATH': os.pathsep.join([str(ROOT / 'core/server'), str(ROOT / 'core/sdk')])}
    completed = subprocess.run([sys.executable, '-c', CHILD, 'resume', str(tmp_path / 'done.json')],
                               env=env, capture_output=True, text=True, timeout=12)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    done = c.get('/api/v1/jobs/' + job['id']).json()
    assert done['status'] == 'done' and done['result']['value'] == 29

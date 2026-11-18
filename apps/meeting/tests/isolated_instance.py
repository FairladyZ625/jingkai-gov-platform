"""测试专用组装，使用临时清单和真实的经开区轮询适配器。"""
import argparse
import json
import os
import secrets
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MEETING = ROOT / 'apps/meeting'
MEETINGS = '/api/apps/meeting/meetings'
JOBS = '/api/v1/jobs'


PASSWORD_ENV = 'JKQ_MEETING_TEST_PASSWORD'
OUTSIDER = 'meeting-outsider'


def fixture_environment(base):
    """使用经开区真实口令登录（#78）：临时角色表 + 演示账号，口令每次随机生成。"""
    apps = base / 'apps'
    config = base / 'config'
    config.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'config/projects.yaml', config / 'projects.yaml')
    roles = {'operator': ['view', 'operate'], 'reader': ['view']}
    role_specs = {
        role: {'name': role, 'desc': '会议测试', 'mask': False, 'grants': {'meeting': actions}}
        for role, actions in roles.items()
    }
    (config / 'roles.yaml').write_text(json.dumps({'apps': ['meeting'], 'roles': role_specs},
                                                  ensure_ascii=False), encoding='utf-8')
    users = [
        dict(id='meeting-writer', name='会议办理员', role='operator'),
        dict(id='meeting-reader', name='会议观察员', role='reader'),
        dict(id=OUTSIDER, name='项目外人员', role='reader'),
    ]
    demo_users = [dict(user, username=user['id'], passwordEnv=PASSWORD_ENV) for user in users]
    (config / 'users.yaml').write_text(json.dumps({'demoUsers': demo_users}, ensure_ascii=False),
                                       encoding='utf-8')
    app = apps / 'meeting'
    for directory in ('api', 'samples', 'web'):
        shutil.copytree(MEETING / directory, app / directory, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copyfile(MEETING / 'app.json', app / 'app.json')  # 用正式清单与 router.py，覆盖实际挂载
    return {
        'HAIKNOW_ROOT': str(ROOT), 'HAIKNOW_APPS_DIR': str(apps), 'HAIKNOW_CONFIG_DIR': str(config),
        'HAIKNOW_DATA_DIR': str(base / 'data'), 'HAIKNOW_DEMO_LOGIN': '0', 'JKQ_DEMO_MODE': '1',
        'HAIKNOW_KB_SEED': '0', 'HAIKNOW_NO_AUTOAPP': '1', 'HAIKNOW_SECRET': 'local-meeting-test-only',
        PASSWORD_ENV: os.environ.get(PASSWORD_ENV) or secrets.token_urlsafe(12),
    }


def create_instance():
    from haiknow_core.main import current_user
    from jkq.app import create_app
    from jkq.jobs_api import install

    app = create_app()
    install(app, current_user)
    store = app.state.platform.store
    with store._lock, store._db as db:  # 演示账号默认可见全部项目，这里收回项目外人员的范围
        store.begin_write()
        db.execute('update users set all_projects=0 where id=?', (OUTSIDER,))
        db.execute('delete from project_members where user_id=?', (OUTSIDER,))
    return app


def transcription_module():
    return sys.modules['haiknow_apps.meeting.transcription']


def login(client, user='meeting-writer'):
    result = client.post('/api/v1/auth/login',
                         json={'username': user, 'password': os.environ[PASSWORD_ENV]})
    assert result.status_code == 200, result.text


def job_snapshot(client, job_id, *, raw=False):
    suffix = '?app=meeting' if raw else ''
    response = client.get(f'{JOBS}/{job_id}{suffix}')
    assert response.status_code == 200, response.text
    return response.json() if raw else response.json()['job']


def wait_job(client, job_id, condition, *, raw=False):
    deadline = time.monotonic() + 8
    samples = []
    while time.monotonic() < deadline:
        job = job_snapshot(client, job_id, raw=raw)
        samples.append(job)
        if condition(job):
            return samples
        time.sleep(.015)
    raise AssertionError(f'未到达预期任务状态 {samples[-1]}')


def submit_demo(client):
    created = client.post(MEETINGS, data={'title': '公开演示例会', 'source': 'demo'})
    assert created.status_code == 201, created.text
    item = created.json()['item']
    accepted = client.post(f"{MEETINGS}/{item['id']}/transcribe")
    assert accepted.status_code == 202, accepted.text
    return item['id'], accepted.json()['job']['id']


def serve(base, port, fail_once):
    import uvicorn
    from haiknow_sdk import DataError

    os.environ.update(fixture_environment(base))
    app = create_instance()
    if fail_once:
        module = transcription_module()
        transcribe = module.transcribe_part
        failed = False

        def flaky(part, **options):
            nonlocal failed
            if part['number'] == 2 and not failed:
                failed = True
                raise DataError('internal_error', '测试分片故障')
            return transcribe(part, **options)

        module.transcribe_part = flaky
    uvicorn.run(app, host='127.0.0.1', port=port)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--fail-once', action='store_true')
    args = parser.parse_args()
    serve(args.directory, args.port, args.fail_once)

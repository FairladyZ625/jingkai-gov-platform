"""从仓库根目录运行。只使用临时数据库、公开种子编号和随机测试凭据。"""
import argparse
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import httpx


def create_app():
    from jkq.app import create_app as default_app
    app = default_app()
    if os.environ.get('T41_TEST_MOUNT_POLICY') == '1' and not any(
        getattr(route, 'path', '').startswith('/api/apps/policy') for route in app.routes
    ):
        from apps.policy.api.policy_routes import router
        app.include_router(router, prefix='/api/apps/policy')
    return app


def seed_company(client):
    response = client.get('/api/apps/enterprise/companies')
    response.raise_for_status()
    if not any(item.get('id') == 'E001' for item in response.json().get('items', [])):
        raise RuntimeError('隔离实例未初始化企业台账 E001')


def verify(temp, args):
    root = Path.cwd()
    dbdir = temp / 'data'
    # 隔离验证只保留系统和浏览器依赖所需的环境，避免启用外部模型服务。
    names = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'SYSTEMROOT', 'PLAYWRIGHT_BROWSERS_PATH', 'PLAYWRIGHT_CHROME_PATH', 'T41_SCREENSHOT_DIR')
    env = {name: os.environ[name] for name in names if name in os.environ}
    for role in ('ADMIN', 'LEADER', 'MEMBER', 'PARTNER'):
        env[f'JKQ_DEMO_{role}_PASSWORD'] = secrets.token_urlsafe()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        host = f'127.0.0.1:{listener.getsockname()[1]}'
        base = f'http://{host}'
        env.update(
            HAIKNOW_ROOT=str(root), HAIKNOW_DATA_DIR=str(dbdir),
            HAIKNOW_CONFIG_DIR=str(root / 'config'), HAIKNOW_APPS_DIR=str(root / 'apps'),
            HAIKNOW_NO_AUTOAPP='1', HAIKNOW_SECRET=secrets.token_urlsafe(),
            HAIKNOW_DEMO_LOGIN='0', JKQ_DEMO_MODE='1', JKQ_WEB_DIR=str(root / 'web'),
            JKQ_ENTERPRISE_PRIVATE_DB=str(temp / 'enterprise.sqlite'),
            PYTHONPATH=os.pathsep.join(map(str, (root, root/'core/server', root/'core/sdk', Path(__file__).resolve().parent))),
            T41_BASE_URL=base, T41_USERNAME='admin', T41_PASSWORD=env['JKQ_DEMO_ADMIN_PASSWORD'],
            CONTRACT_ENTERPRISE_ID='E001', CONTRACT_USERNAME='admin', CONTRACT_PASSWORD=env['JKQ_DEMO_ADMIN_PASSWORD'],
            CONTRACT_RESETTABLE_TARGET=host, T41_TEST_MOUNT_POLICY='1' if args.mount_policy_fixture else '0',
        )
        fd = listener.fileno()
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', f'{Path(__file__).stem}:create_app',
                                   '--factory', '--fd', str(fd), '--no-access-log'], env=env, pass_fds=(fd,))
        try:
            with httpx.Client(base_url=base, trust_env=False) as client:
                for _ in range(200):
                    if server.poll() is not None:
                        raise RuntimeError('隔离实例启动失败')
                    try:
                        if client.get('/', timeout=.5).is_success:
                            break
                    except (httpx.ConnectError, httpx.TimeoutException):
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError('隔离实例未在限定时间内就绪')
                res = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': env['T41_PASSWORD']})
                res.raise_for_status()
                seed_company(client)
                if args.check == 'contract':
                    meeting = client.post('/api/apps/meeting/meetings', data={
                        'title': '公开契约测试会议', 'source': 'demo',
                    })
                    meeting.raise_for_status()
                    env['CONTRACT_MEETING_ID'] = meeting.json()['item']['id']
            if args.check == 'contract':
                results = []
                for module in ('policy', 'enterprise', 'meeting', 'document'):
                    command = ['node', 'web/tests/contract/run.cjs', '--base', base, '--module', module]
                    # 录音上传和公文附件由 Playwright 用真实表单与二进制验证。
                    if module in ('policy', 'enterprise'):
                        command.append('--allow-writes')
                    results.append(subprocess.run(command, env=env).returncode)
                return max(results)
            return subprocess.run(['node', 'web/node_modules/@playwright/test/cli.js', 'test', '-c',
                                   'web/tests/e2e/links/playwright.config.cjs',
                                   *args.spec], env=env).returncode
        finally:
            server.terminate()
            server.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('check', choices=['contract', 'browser'])
    parser.add_argument('--mount-policy-fixture', action='store_true', help='在 #127 合入前测试现有政策读接口')
    parser.add_argument('--spec', action='append', default=[], help='仅运行指定的 Playwright 测试文件')
    with tempfile.TemporaryDirectory(prefix='t41-policy-ent-') as temp:
        sys.exit(verify(Path(temp), parser.parse_args()))

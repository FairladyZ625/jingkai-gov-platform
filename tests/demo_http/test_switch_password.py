"""HTTP 切号必须现场输入口令；错误/取消不能注销当前会话。口令均为夹具假口令。"""
import pytest
pytest.importorskip('playwright.sync_api')
from playwright.sync_api import sync_playwright
from tests.demo_http.password_ui import login


@pytest.mark.parametrize('server', [()], indirect=True)
def test_http_switch_password_success_error_and_cancel(server):
    with sync_playwright() as engine, engine.chromium.launch() as browser:
        page = browser.new_page()
        calls, console = [], []
        page.on('request', lambda r: calls.append(r.url))
        page.on('console', lambda m: console.append(m.text))
        page.goto(server.url)
        static = page.request.get(server.url + '/config/app.config.js').text()
        assert server.password not in static
        assert page.evaluate("JK_CONFIG.demoAccounts.every(a => ['jk123456','admin123'].includes(a.password))")
        login(page, 'wangmin', server.password)
        initial_storage = page.evaluate("JSON.stringify({...localStorage})")
        for cancel in (False, True):
            page.evaluate("void JKShell.switchUser('liyang')")
            field = page.locator('[data-op="switch.password"]')
            field.wait_for()
            assert field.get_attribute('type') == 'password'
            if not cancel:
                field.fill('synthetic-wrong-password')
                page.locator('[role="dialog"] [data-ok]').click()
                page.locator('[data-op="switch.error"]').get_by_text('口令不正确或登录失败，当前会话已保留').wait_for()
                assert field.input_value() == ''
                assert page.request.get(server.url + '/api/v1/me').json()['user']['username'] == 'wangmin'
            page.locator('[role="dialog"] [data-cancel]').click()
            page.locator('[data-op="switch.password"]').wait_for(state='detached')
            assert page.evaluate('JKShell.S.me.username') == 'wangmin'
            assert page.request.get(server.url + '/api/v1/me').json()['user']['username'] == 'wangmin'
            assert page.evaluate("JSON.stringify({...localStorage})") == initial_storage

        for username in ('liyang', 'hejun', 'admin', 'wangmin'):
            page.evaluate('u => { void JKShell.switchUser(u); }', username)
            field = page.locator('[data-op="switch.password"]')
            field.wait_for(); field.fill(server.password)
            page.locator('[role="dialog"] [data-ok]').click()
            page.wait_for_function('u => JKShell.S.me?.username === u', arg=username)
            assert page.request.get(server.url + '/api/v1/me').json()['user']['username'] == username
            assert page.locator('[data-op="switch.password"]').count() == 0
        assert not any(url.endswith('/auth/logout') for url in calls)
        assert server.password not in page.content()
        assert server.password not in page.evaluate("JSON.stringify({...localStorage,...sessionStorage})")
        assert not any(server.password in text for text in console)

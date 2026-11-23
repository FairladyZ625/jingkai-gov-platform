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

        for username in ('liyang', 'admin', 'wangmin', 'hejun'):
            page.evaluate('u => { void JKShell.switchUser(u); }', username)
            field = page.locator('[data-op="switch.password"]')
            field.wait_for(); field.fill(server.password)
            page.locator('[role="dialog"] [data-ok]').click()
            page.wait_for_function('u => JKShell.S.me?.username === u', arg=username)
            assert page.request.get(server.url + '/api/v1/me').json()['user']['username'] == username
            assert page.locator('[data-op="switch.password"]').count() == 0
        assert not any(url.endswith('/auth/logout') for url in calls)
        assert page.locator('#btn-demo,[data-op="rail.demo"]').count() == 0
        assert page.evaluate("JKShell.switchUser('admin')") is False
        assert page.locator('[data-op="switch.password"]').count() == 0
        assert page.request.get(server.url + '/api/v1/me').json()['user']['username'] == 'hejun'
        assert server.password not in page.content()
        assert server.password not in page.evaluate("JSON.stringify({...localStorage,...sessionStorage})")
        assert not any(server.password in text for text in console)


@pytest.mark.parametrize('server', [()], indirect=True)
def test_new_identity_can_switch_while_its_inbox_is_refreshing(server):
    """阻塞真实收件箱回执的消费，不伪造身份、口令、业务回执或授权。"""
    with sync_playwright() as engine, engine.chromium.launch() as browser:
        page = browser.new_page()
        page.goto(server.url)
        login(page, 'wangmin', server.password)
        page.evaluate("""() => {
            const list = JKApi.reviews.list;
            const gate = new Promise(resolve => { window.releaseTestInbox = resolve; });
            JKApi.reviews.list = async (...args) => {
                const owner = JKShell.S.me.username;
                const result = await list(...args);
                if (owner === 'liyang') { window.testInboxHeld = true; await gate; }
                return result;
            };
            window.firstTestSwitch = JKShell.switchUser('liyang');
        }""")
        password = page.locator('[data-op="switch.password"]')
        password.fill(server.password)
        page.locator('[role="dialog"] [data-ok]').click()
        page.wait_for_function("window.testInboxHeld && JKShell.S.me.username === 'liyang'")
        page.evaluate("() => { window.nextTestSwitch = JKShell.switchUser('admin'); }")
        password.wait_for()
        assert page.evaluate("() => { releaseTestInbox(); return firstTestSwitch; }") is True
        assert page.evaluate("JKShell.switchUser('hejun')") is False
        assert page.request.get(server.url + '/api/v1/me').json()['user']['username'] == 'liyang'
        password.fill(server.password)
        page.locator('[role="dialog"] [data-ok]').click()
        assert page.evaluate("window.nextTestSwitch") is True
        assert page.request.get(server.url + '/api/v1/me').json()['user']['username'] == 'admin'


@pytest.mark.parametrize('server', [()], indirect=True)
def test_cancel_demo_start_preserves_http_session(server):
    """用临时 HTTP 账号走原始开场，不依赖 JS 伪造登录成功。"""
    with sync_playwright() as engine, engine.chromium.launch() as browser:
        page = browser.new_page()
        page.goto(server.url)
        login(page, 'liyang', server.password)
        calls = []
        page.on('request', lambda r: calls.append(r.url) if r.method == 'POST' else None)
        await_dialog = page.locator('[role="dialog"]').filter(has=page.locator('[data-op="switch.password"]'))
        page.locator('#btn-demo').click()
        await_dialog.wait_for()
        await_dialog.locator('[data-x]').click()
        page.wait_for_function('!JKDemo.state.on && !document.querySelector("[role=dialog]")')
        assert page.evaluate('[JKDemo.state.i, JKShell.S.me.username, JKShell.S.convs.length]') == [0, 'liyang', 0]
        assert page.request.get(server.url + '/api/v1/me').json()['user']['username'] == 'liyang'
        assert not calls

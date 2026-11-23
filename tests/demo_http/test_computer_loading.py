"""只打开本地面板，验证电脑操作未配置和暂时故障的页面表现。"""

import pytest

from tests.demo_http.password_ui import login

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402


@pytest.fixture(scope="module")
def computer_enabled(request):
    from jkq import routers

    register = routers.register_routes

    def register_without_computer(app):
        with pytest.MonkeyPatch.context() as env:
            env.delenv("JKQ_MOCK_GOV_URL", raising=False)
            register(app)

    with pytest.MonkeyPatch.context() as patch:
        if not request.param:
            patch.setattr(routers, "register_routes", register_without_computer)
        yield


@pytest.fixture
def page_with_errors(server):
    with sync_playwright() as engine, engine.chromium.launch() as browser:
        page = browser.new_page(base_url=server.url, viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("/")
        assert page.evaluate("JK_CONFIG.api.mode") == "http"
        login(page, "admin", server.password)
        yield page, errors


@pytest.mark.parametrize("computer_enabled,server", [(False, ())], indirect=True)
def test_missing_computer_routes_show_disabled_panel(computer_enabled, page_with_errors):
    page, errors = page_with_errors
    writes = []
    page.on("request", lambda req: writes.append(req.url)
            if req.method != "GET" and "/api/apps/computer/" in req.url else None)
    for resource in ("tasks", "runs"):
        assert page.request.get(f"/api/apps/computer/{resource}").status == 404
    page.locator('[data-op="rail.computer"]').click()
    panel = page.locator('.app-computer')
    expect(panel.get_by_text("当前环境未启用电脑操作", exact=True)).to_be_visible(timeout=3000)
    expect(panel.get_by_text("请联系管理员确认服务是否已配置。", exact=True)).to_be_visible()
    expect(panel.get_by_role("button", name="开始", exact=True)).to_have_count(0)
    expect(panel.get_by_role("button", name="重试", exact=True)).to_have_count(0)
    page.evaluate("JKShell.openApp('computer', 'runs')")
    expect(panel.get_by_text("当前环境未启用电脑操作", exact=True)).to_be_visible()
    assert not errors and not writes


@pytest.mark.parametrize("computer_enabled,server", [(True, ("meeting",))], indirect=True)
def test_transient_computer_error_can_retry_without_starting_task(computer_enabled, page_with_errors):
    page, errors = page_with_errors
    assert page.request.get("/api/apps/computer/tasks").ok
    writes = []
    page.on("request", lambda req: writes.append(req.url)
            if req.method != "GET" and "/api/apps/computer/" in req.url else None)
    page.route("**/api/apps/computer/tasks", lambda route: route.fulfill(status=503, json={}), times=1)
    page.locator('[data-op="rail.computer"]').click()
    panel = page.locator('.app-computer')
    expect(panel.get_by_text("电脑操作暂时无法加载", exact=True)).to_be_visible(timeout=3000)
    expect(panel.get_by_role("button", name="开始", exact=True)).to_have_count(0)
    panel.get_by_role("button", name="重试", exact=True).click()
    expect(panel.get_by_text("常用任务", exact=True)).to_be_visible()
    expect(panel.locator(".cu-task").first).to_be_visible()
    panel.get_by_role("button", name="操作记录", exact=True).click()
    expect(panel.get_by_text("还没有操作记录", exact=True)).to_be_visible()
    assert not errors and not writes

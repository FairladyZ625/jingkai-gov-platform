"""在本地真 HTTP 实例验证窄屏外壳、导航和会话退出。"""

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402


@pytest.fixture
def page(server):
    with sync_playwright() as engine, engine.chromium.launch() as browser:
        page = browser.new_page(base_url=server.url, viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
        page.goto(server.url)
        assert page.evaluate("JK_CONFIG.api.mode") == "http"
        page.locator('[data-op="login.user"]').fill("wangmin")
        page.locator('[data-op="login.pass"]').fill(server.password)
        page.locator('[data-op="login.go"]').click()
        expect(page.locator(".rail-logo")).to_be_visible()
        yield page


@pytest.mark.parametrize("server", [()], indirect=True)
def test_mobile_panel_switches_without_closing_app(page):
    chat, panel = page.locator("#chatcol"), page.locator("#panel")
    page.locator('[data-op="rail.kb"]').click()
    expect(panel.locator('[data-view="kb"]')).to_be_visible()
    assert panel.bounding_box()["width"] >= 300
    expect(chat).to_be_hidden()
    page.get_by_role("button", name="返回对话").click()
    expect(chat).to_be_visible()
    expect(panel).to_be_hidden()
    page.get_by_role("button", name="返回应用").click()
    expect(panel.locator('[data-view="kb"]')).to_be_visible()
    page.set_viewport_size({"width": 1440, "height": 900})
    expect(chat).to_be_visible()
    assert chat.bounding_box()["x"] < panel.bounding_box()["x"]


@pytest.mark.parametrize("server", [()], indirect=True)
@pytest.mark.parametrize("width", [390, 768])
def test_mobile_side_opens_and_logs_out_http_session(page, width):
    page.set_viewport_size({"width": width, "height": 844})
    logo = page.locator(".rail-logo")
    logo.click()
    expect(page.get_by_text("最近对话", exact=True)).to_be_visible(timeout=3000)
    expect(page.get_by_role("button", name="一键演示", exact=False)).to_be_visible()
    page.keyboard.press("Escape")
    expect(logo).to_be_focused()
    expect(page.locator("#btn-me")).to_be_hidden()
    logo.click()
    page.locator("#btn-me").click()
    expect(page.get_by_text("个人设置", exact=True)).to_be_visible()
    with page.expect_response(lambda response: "/auth/logout" in response.url) as result:
        page.get_by_text("退出登录", exact=True).click()
    assert result.value.ok
    expect(page.locator('[data-op="login.go"]')).to_be_visible()
    session = page.request.get("/api/v1/auth/session")
    assert session.ok and session.json()["user"] is None


@pytest.mark.parametrize("server", [()], indirect=True)
def test_phone_home_cards_have_room_for_titles_and_descriptions(page):
    cards = page.locator(".quick-apps .qa")
    expect(cards).to_have_count(4)
    boxes = [card.bounding_box() for card in cards.all()]
    assert len({box["y"] for box in boxes}) >= 2
    assert min(box["width"] for box in boxes) >= 120
    assert cards.evaluate_all("cards => cards.every(card => { const title = card.querySelector('.n'); const range = document.createRange(); range.selectNodeContents(title); return range.getClientRects().length === 1 && card.querySelector('.d').scrollHeight === card.querySelector('.d').clientHeight; })")
    assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
    cards.last.scroll_into_view_if_needed()
    assert cards.last.evaluate("card => card.getBoundingClientRect().bottom <= innerHeight")
    page.locator('.quick-apps [data-app="enterprise"]').click()
    expect(page.locator('#panel [data-view="enterprise"]')).to_be_visible()
    assert page.locator("#panel").bounding_box()["width"] >= 300

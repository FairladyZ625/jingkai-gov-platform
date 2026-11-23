"""#203/#202：受控延迟首屏脚本，检查加载提示、主题与按模式加载数据。"""
from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright


@pytest.mark.parametrize("server", [()], indirect=True)
@pytest.mark.parametrize(("theme", "width"), [("light", 390), ("dark", 1440)])
def test_startup_is_visible_while_large_script_is_in_flight(server, theme, width):
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page(viewport={"width": width, "height": 850})
        if theme == "dark":
            page.add_init_script("localStorage.setItem('jk4-theme2', 'dark')")
        held, requested = [], []
        page.route("**/config/mock-data.js", lambda route: held.append(route))
        page.on("request", lambda request: requested.append(urlsplit(request.url).path))
        with page.expect_request(lambda request: request.url.endswith("/config/mock-data.js")):
            page.goto(server.url, wait_until="commit")
        status = page.locator('[data-op="startup.loading"]')
        expect(status).to_be_visible(timeout=1800)
        page.wait_for_function("performance.getEntriesByName('first-contentful-paint').length > 0", timeout=1800)
        expect(status).to_contain_text("正在加载工作站")
        expect(page.locator("html")).to_have_attribute("data-theme", theme)
        expect(page.locator('[data-op="login.go"]')).to_have_count(0)
        assert len(held) == 1
        held[0].continue_()
        expect(page.locator('[data-op="login.go"]')).to_be_visible()
        expect(status).to_have_count(0)
        expect(page.locator("html")).to_have_attribute("data-theme", theme)
        mock_snapshots = {"/data/real-supplement.js", "/data/real-policies.js", "/data/real-kb.js", "/data/kb-examples.js"}
        assert mock_snapshots.isdisjoint(requested)


def test_file_mock_keeps_local_public_snapshots():
    entry = Path(__file__).resolve().parents[2] / "web/index.html"
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page(offline=True)
        page.goto(entry.as_uri())
        assert page.evaluate("Boolean(window.JK_REAL && window.JK_REAL_KB && window.JK_REAL_SUPPLEMENT)")
        page.locator('[data-u="wangmin"]').click()
        expect(page.locator('[data-op="nav.document"]')).to_be_visible()

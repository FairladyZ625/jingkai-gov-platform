"""#208：手动描述企业在真实 HTTP 页面核对事项并生成告知单。"""
import re

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright

from tests.demo_http.password_ui import login


@pytest.mark.parametrize("server", [()], indirect=True)
def test_manual_enterprise_checks_scope_and_generates_notice(server):
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page()
        page.goto(server.url)
        assert page.evaluate("JK_CONFIG.api.mode") == "http"
        login(page, "wangmin", server.password)
        page.locator('[data-op="nav.policy"]').click()
        page.locator('[data-op="policy.mode-manual"]').click()
        for tag in ("智能网联汽车", "人工智能"):
            page.locator(f'[data-mtag="{tag}"]').click()
        page.locator('[data-mlic="高新技术企业"]').click()
        page.locator('[data-op="policy.m-years"]').fill("3")
        base = server.url + "/api/apps/policy"
        with page.expect_response(lambda response: response.url == base + "/match") as match:
            page.locator('[data-op="policy.go"]').click()
        assert match.value.ok, match.value.text()
        expect(page.locator(".pol-kpis")).to_be_visible()
        all_results = page.locator('[data-op="policy.show-all"]')
        if all_results.is_visible():
            all_results.click()
        for item_id in ("RP-028", "RP-038", "RP-050", "RP-062"):
            row = page.locator(f'[data-res="{item_id}"]')
            expect(row).to_have_class(re.compile(r"\blv-check\b"))
            expect(row.get_by_text("需人工确认", exact=False)).to_be_visible()
            expect(row.locator("[data-pick]")).not_to_be_checked()

        selected = page.locator("[data-pick]:checked").evaluate_all("xs => xs.map(x => x.dataset.pick)")
        ended = {r["id"] for r in match.value.json()["results"] if r["ended"]}
        assert selected and ended and set(selected).isdisjoint(ended)
        page.locator('[data-op="policy.next"]').click()
        with page.expect_response(lambda response: response.url == base + "/notice") as notice:
            page.locator('[data-op="policy.to-notice"]').click()
        assert notice.value.ok, notice.value.text()
        sent = notice.value.request.post_data_json
        assert sent["profile"] == {"subjectType": "企业"}
        assert "entId" not in sent and set(sent["itemIds"]) == set(selected)
        expect(page.locator("#pn")).to_have_value(re.compile("政策兑现一次性告知单"))

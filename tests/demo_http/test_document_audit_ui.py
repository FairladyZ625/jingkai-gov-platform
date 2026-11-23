"""#191：实际浏览器起草和保存，审计证据由真实后端提供。"""
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright

from tests.demo_http.password_ui import login


def test_offline_demo_keeps_its_simulated_audit():
    entry = Path(__file__).resolve().parents[2] / "prototype/v4/index.html"
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page(offline=True)
        page.goto(entry.as_uri())
        page.locator('[data-u="admin"]').click()
        page.locator('[data-op="nav.document"]').click()
        count = """async () => (await JKApi.audit.list()).items.filter(
            row => String(row.action || row[3] || '').includes('生成公文初稿')
        ).length"""
        before = page.evaluate(count)
        page.locator('[data-op="document.tpl-T03"]').click()
        page.locator('[data-op="document.sample"]').click()
        page.locator('[data-op="document.gen"]').click()
        expect(page.locator('[data-op="document.paper"]')).to_be_visible()
        page.wait_for_function(f"async before => await ({count})() > before", arg=before)


@pytest.mark.parametrize("server", [()], indirect=True)
def test_document_audit_is_visible_without_browser_write(server):
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page()
        page.goto(server.url)
        assert page.evaluate("JK_CONFIG.api.mode") == "http"
        login(page, "admin", server.password)
        actor = page.request.get(server.url + "/api/v1/me").json()["user"]["id"]
        audit_url = server.url + "/api/v1/audit"
        posts = []
        page.on("request", lambda request: posts.append(request.url)
                if request.url == audit_url and request.method == "POST" else None)
        page.locator('[data-op="nav.document"]').click()
        page.locator('[data-op="document.tpl-T03"]').click()
        page.locator('[data-op="document.sample"]').click()
        drafts = server.url + "/api/apps/document/drafts"
        with page.expect_response(lambda r: r.url == drafts and r.request.method == "POST") as created:
            page.locator('[data-op="document.gen"]').click()
        assert created.value.ok, created.value.text()
        did = created.value.json()["item"]["id"]
        page.locator('.dc-paper [data-pe="title"]').click()
        editor = page.locator('[data-ed="title"]')
        editor.fill("隔离审计测试公文")
        editor.press("Tab")
        with page.expect_response(lambda r: r.url == f"{drafts}/{did}" and r.request.method == "PUT") as saved:
            page.locator('[data-op="document.save"]').click()
        assert saved.value.ok, saved.value.text()
        expect(page.locator('[data-op="document.save"]')).to_have_count(0)
        result = page.request.get(audit_url, params={"app": "document"})
        assert result.ok, result.text()
        rows = [row for row in result.json()["items"] if row["detail"].get("recordId") == did]
        assert any(row["action"] == "document.draft.mock" and row["userId"] == actor for row in rows)
        assert sorted(row["detail"]["version"] for row in rows
                      if row["action"] == "v1.record.save" and row["userId"] == actor) == [1, 2]
        assert not posts, "真实后端审计不应调用浏览器 POST /api/v1/audit"

        page.locator('[data-op="nav.admin"]').click()
        page.locator('[data-op="admin.tab-audit"]').click()
        audit = page.locator('.audit-row').filter(has_text="公文协作")
        expect(audit.filter(has_text="起草公文初稿（模拟）").first).to_be_visible()
        expect(audit.filter(has_text="保存公文记录").first).to_be_visible()

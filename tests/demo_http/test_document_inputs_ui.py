"""#210：真实 HTTP 下返回要素页、重新生成及在同一会话重开原稿。"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright

from tests.demo_http.password_ui import login


@pytest.mark.parametrize("server", [()], indirect=True)
def test_back_and_reopen_keep_each_drafts_own_form_values(server):
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page()
        page.goto(server.url)
        assert page.evaluate("JK_CONFIG.api.mode") == "http"
        login(page, "wangmin", server.password)
        page.locator('[data-op="nav.document"]').click()
        page.locator('[data-op="document.tpl-T03"]').click()
        page.locator('[data-op="document.sample"]').click()
        fields = {key: page.locator(f'[data-op="document.in-{key}"]') for key in ("policy", "start", "end", "contact")}
        old_phone, new_phone = "010-00000001", "010-00000002"
        fields["contact"].fill(old_phone)
        original_values = {key: field.input_value() for key, field in fields.items()}
        assert all(original_values.values())
        endpoint = server.url + "/api/apps/document/drafts"

        def generate():
            with page.expect_response(lambda r: r.url == endpoint and r.request.method == "POST") as created:
                page.locator('[data-op="document.gen"]').click()
            assert created.value.ok, created.value.text()
            expect(page.locator('.dc-paper')).to_be_visible()
            return created.value.json()["item"]

        first = generate()
        original = page.request.get(f'{endpoint}/{first["id"]}').json()["item"]
        page.locator("#df [data-step='1']").click()
        for key, field in fields.items():
            expect(field).to_have_value(original_values[key])
        fields["contact"].fill(new_phone)
        second = generate()
        assert first["id"] != second["id"]
        assert page.request.get(f'{endpoint}/{first["id"]}').json()["item"] == original

        page.locator('[data-op="document.tab-list"]').click()
        page.locator(f'[data-op="document.row-{first["id"]}"]').click()
        page.locator("#df [data-step='1']").click()
        for key, field in fields.items():
            expect(field).to_have_value(original_values[key])
        expect(page.get_by_text("重新生成会新建草稿，当前文稿和历史版本保留。", exact=True)).to_be_visible()

        # 页面重载后不串用另一份草稿或推断原始表单；已公开给文稿界面的政策编号可保留。
        page.reload()
        page.locator('[data-op="nav.document"]').click()
        page.locator('[data-op="document.tab-list"]').click()
        page.locator(f'[data-op="document.row-{first["id"]}"]').click()
        page.locator("#df [data-step='1']").click()
        expect(fields["policy"]).to_have_value(original_values["policy"])
        expect(fields["contact"]).to_have_value("")
        expect(page.get_by_text("当前会话没有这份草稿的完整起草要素，缺失字段需重新填写。", exact=True)).to_be_visible()

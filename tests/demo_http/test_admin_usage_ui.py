"""在临时实例验证后台真正读取审计与用量，不调用外部模型。"""

import re

import pytest

from tests.demo_http.password_ui import login

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def usage_audit():
    from jkq import app

    create = app.create_app

    def create_with_audit():
        instance = create()
        store = instance.state.platform.store
        for _ in range(53):
            store.audit("platform", "u-wangmin", "fixture.old_event", {})
        store.audit("skills", "u-wangmin", "job.failed", {})
        store.audit("skills", "u-wangmin", "ai.chat", {"model": "测试用模型", "providerKind": "local"})
        store.audit("skills", "u-wangmin", "ai.outbound_denied", {"capability": "chat"})
        return instance

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(app, "create_app", create_with_audit)
        yield


@pytest.mark.parametrize("server", [()], indirect=True)
def test_audit_labels_paging_and_usage_match_the_gateway(server):
    with sync_playwright() as engine, engine.chromium.launch() as browser:
        admin, member = [browser.new_page(base_url=server.url, viewport={"width": 1440, "height": 900}) for _ in range(2)]
        for page, user in ((admin, "admin"), (member, "wangmin")):
            page.goto("/")
            login(page, user, server.password)
        assert member.request.get("/api/v1/admin/usage/summary").status == 403
        admin.locator('[data-op="rail.admin"]').click()
        admin.get_by_role("button", name="审计日志").click()
        row = admin.locator(".audit-row").filter(has_text="外发被拦截")
        expect(row.get_by_text("技能中心", exact=True)).to_be_visible()
        expect(row.locator("td").first).to_have_text(re.compile(r"^\d{1,2}月\d{1,2}日 \d{2}:\d{2}$"))
        controls = admin.locator(".adm-body")
        expect(controls.get_by_text(re.compile("第 1–50 条"))).to_be_visible()
        admin.get_by_role("button", name="下一页").click()
        expect(controls.get_by_text(re.compile("第 51–"))).to_be_visible()
        expect(controls.locator(".audit-row").first).to_contain_text("fixture.old_event")
        admin.get_by_role("button", name="上一页").click()
        search = admin.get_by_placeholder("筛选本页人员、应用或动作")
        search.fill("任务失败")
        expect(admin.locator(".audit-row")).to_have_count(1)
        with admin.expect_download() as result:
            admin.get_by_role("button", name="导出本页 CSV").click()
        assert result.value.path().read_bytes().startswith(b"\xef\xbb\xbf")
        admin.get_by_role("button", name="用量", exact=True).click()
        expect(controls.get_by_text("外发拦截 1 次", exact=False)).to_be_visible()
        model = controls.locator(".bar-row").filter(has_text="测试用模型")
        expect(model).to_contain_text("1 次")
        expect(controls.get_by_text("100%", exact=True)).to_be_visible()

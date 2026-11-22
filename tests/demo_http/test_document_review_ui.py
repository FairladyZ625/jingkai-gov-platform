"""浏览器点击真实同源页面；只有 pytest 临时服务可以作为目标。"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright
from tests.demo_http.password_ui import login


@pytest.mark.parametrize("server", [()], indirect=True)
@pytest.mark.parametrize("width", [1440, 1280])
def test_document_submission_dialog(server, width, tmp_path):
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        # 独立会话：先登录领导，验证别人送审后再打开收件箱能读到新件。
        member, leader = [browser.new_page(viewport={"width": width, "height": 900}) for _ in range(2)]
        for page, name in ((leader, "liyang"), (member, "wangmin")):
            page.goto(server.url)
            assert page.evaluate("JK_CONFIG.api.mode") == "http"
            login(page, name, server.password)
        orig = f"【隔离演示 {width}】材料核验"
        created = member.request.post(server.url + "/api/apps/document/drafts", data={
            "templateId": "T06", "inputs": {"orig": orig, "oldEnd": "2026-11-20",
            "newEnd": "2026-11-25", "reason": "演练延期"}})
        assert created.ok
        draft = created.json()["item"]
        path = server.url + "/api/apps/document/drafts/" + draft["id"]
        calls = []
        member.on("request", lambda r: calls.append(r.method) if r.url == path + "/submit" else None)
        member.locator('[data-op="nav.document"]').click()
        member.locator('[data-op="document.tab-list"]').click()
        member.locator(f'[data-open="{draft["id"]}"]').click()
        member.locator('[data-op="document.to-review"]').click()
        submit = member.locator('[data-op="document.submit"]')
        submit.click()
        dialog = member.get_by_role("dialog")
        expect(dialog).to_be_visible()
        expect(dialog.get_by_label("审签人")).to_have_value("李阳")
        expect(dialog).to_contain_text(orig)
        expect(dialog).to_contain_text(f'第 {draft["versions"][-1]["v"]} 版')
        box = dialog.bounding_box()
        assert 0 <= box["x"] and box["x"] + box["width"] <= width
        assert 0 <= box["y"] and box["y"] + box["height"] <= 900
        # trial=True 同时验证按钮在视口内且不被遮挡，但不真正提交。
        confirm = dialog.get_by_role("button", name="确认送审")
        confirm.click(trial=True)
        member.screenshot(path=tmp_path / f"确认送审-{width}.png")
        dialog.get_by_role("button", name="取消").click()
        expect(dialog).to_have_count(0)
        assert not calls and member.request.get(path).json()["item"]["status"] == "草稿"

        submit.click()
        with member.expect_response(lambda r: r.url == path + "/submit") as blocked:
            confirm.click()
        assert blocked.value.status == 422
        message = blocked.value.json()["error"]["message"]
        assert message
        expect(member.locator(".toast.err").last).to_contain_text(message)
        expect(member.get_by_role("alert")).to_contain_text(message)
        for key, value in (("docNo", "演示〔2026〕2号"), ("to", "演示材料组："),
                           ("sign", "虚拟演示组"), ("date", "2026年11月18日")):
            member.locator(f'.dc-paper [data-pe="{key}"]').first.click()
            editor = member.locator(f'[data-ed="{key}"]')
            editor.fill(value)
            editor.press("Tab")
        member.locator('[data-op="document.save"]').click()
        expect(member.locator('[data-op="document.save"]')).to_have_count(0)
        member.locator('[data-op="document.to-review"]').click()
        submit.click()
        with member.expect_response(lambda r: r.url == path + "/submit") as accepted:
            confirm.click()
        assert accepted.value.ok and accepted.value.json()["review"]["assignee"] == "u-liyang"
        expect(member.locator(".dc-status .tag").first).to_have_text("审签中")
        assert calls == ["POST", "POST"]
        leader.locator('[data-op="nav.inbox"]').click()
        row = leader.locator(".inb-i").filter(has_text=orig)
        expect(row).to_be_visible()
        row.get_by_role("button", name="查看").click()
        expect(leader.locator(".dc-title")).to_contain_text(orig)
        expect(leader.get_by_text("这份文稿未附引用资料")).to_be_visible()
        expect(leader.locator('[data-op="document.approve"]')).to_be_visible()

        note, reason = "首段缺少核验范围。", "请注明仅受理虚拟材料。"
        leader.locator("#dcn").fill(note)
        leader.locator('[data-act="addCm"]').click()
        expect(leader.locator(".dc-ct").last).to_have_text(note)
        leader.locator('[data-act="reject"]').click()
        leader.get_by_label("退回意见").fill(reason)
        leader.get_by_role("dialog").locator("[data-ok]").click()
        expect(leader.locator(".dc-status .tag").first).to_have_text("已退回")

        member.locator('[data-op="document.tab-list"]').click()
        member.locator(f'[data-open="{draft["id"]}"]').click()
        expect(member.locator(".callout.h-red")).to_contain_text(reason)
        expect(member.locator(".dc-ct").last).to_have_text(note)
        member.locator('#df [data-step="2"]').click()
        member.locator('.dc-paper [data-pe="0"]').click()
        para = member.locator('[data-ed="0"]')
        para.fill(para.input_value() + "本次仅受理虚拟材料。")
        para.press("Tab")
        member.locator('[data-op="document.save"]').click()
        expect(member.locator('[data-op="document.save"]')).to_have_count(0)
        member.locator('[data-op="document.to-review"]').click()
        submit.click()
        confirm.click()
        expect(member.locator(".dc-status .tag").first).to_have_text("审签中")
        leader.locator('[data-op="nav.inbox"]').click()
        row.get_by_role("button", name="查看").click()
        expect(leader.locator('.dc-paper [data-op="document.p-0"]')).to_contain_text("本次仅受理虚拟材料。")
        leader.locator('[data-act="approve"]').click()
        leader.get_by_role("button", name="通过并定稿").click()
        expect(leader.locator(".dc-status .tag").first).to_have_text("已定稿")
        assert member.request.get(path).json()["item"]["status"] == "已定稿"

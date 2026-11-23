"""收件箱退回技能：真实浏览器、同源 HTTP 和隔离存储。"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright

from tests.demo_http.password_ui import login


@pytest.mark.parametrize("server", [()], indirect=True)
def test_leader_can_return_skill_from_inbox_with_reason(server):
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        member, leader = browser.new_page(), browser.new_page()
        for page, name in ((member, "wangmin"), (leader, "liyang")):
            page.goto(server.url)
            assert page.evaluate("JK_CONFIG.api.mode") == "http"
            login(page, name, server.password)
        title = "隔离夹具：收件箱退回技能"
        skills = server.url + "/api/v1/skills"
        created = member.request.post(skills, data={"name": title})
        assert created.ok, created.text()
        item_url = skills + "/" + created.json()["item"]["id"]
        published = member.request.post(item_url + "/publish", data={"share": {"scope": "zone"}})
        assert published.ok, published.text()
        review = published.json()["review"]

        reason = "请补充测试材料要求"
        leader.locator('[data-op="nav.inbox"]').click()
        row = leader.locator(".inb-i").filter(has_text=title)
        expect(row).to_be_visible()
        leader.once("dialog", lambda dialog: dialog.accept(reason))
        decision_url = f'{server.url}/api/v1/reviews/{review["id"]}/decisions'
        with leader.expect_response(lambda r: r.url == decision_url) as decided:
            row.locator('[data-dec="reject"]').click()
        assert decided.value.ok, decided.value.text()
        assert decided.value.request.post_data_json == {
            "decision": "reject", "reason": reason, "version": review["version"],
        }
        expect(row).to_have_count(0)
        state = member.request.get(item_url).json()["item"]
        assert state["status"] == "rejected" and state["reviewNote"] == reason

"""#206：浏览器审核入口必须提交当前待审标识、版本与退回意见。"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright

from tests.demo_http.password_ui import login


@pytest.mark.parametrize("server", [()], indirect=True)
@pytest.mark.parametrize("decision", ["reject", "approve"])
def test_review_skill_from_browser(server, decision):
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        member = browser.new_page()
        member.goto(server.url)
        login(member, "wangmin", server.password)
        name = f"技能审核夹具 {decision}"
        api = server.url + "/api/v1/skills"
        created = member.request.post(api, data={"name": name})
        assert created.ok, created.text()
        sid = created.json()["item"]["id"]
        published = member.request.post(f"{api}/{sid}/publish", data={"share": {"scope": "zone"}})
        assert published.ok, published.text()
        review = published.json()["review"]

        leader = browser.new_page()
        leader.goto(server.url)
        login(leader, "liyang", server.password)
        leader.locator('#side-sc [data-app="skills"]').click()
        leader.locator('[data-op="skills.tab.review"]').click()
        row = leader.locator(".sk-rv").filter(has_text=name)
        expect(row).to_be_visible()
        button = row.locator(f'[data-op="skills.{decision}.{sid}"]')
        path = f"{api}/{sid}/review"
        def matching(req):
            return req.method == "POST" and req.url == path

        reason = "请补充适用范围" if decision == "reject" else ""
        if decision == "reject":
            requests = []
            leader.on("request", lambda req: requests.append(req) if matching(req) else None)
            button.click()
            modal = leader.get_by_role("dialog").filter(has_text="退回原因")
            modal.locator("[data-cancel]").click()
            expect(modal).to_have_count(0)
            assert not requests
            button.click()
            modal.locator("[data-ok]").click()
            expect(leader.get_by_text("请填写退回原因", exact=True)).to_be_visible()
            expect(modal).to_be_visible()
            assert not requests
            modal.locator("[data-rs]").fill(reason)
            button = modal.locator("[data-ok]")
        with leader.expect_response(lambda response: matching(response.request)) as result:
            button.click()
        response = result.value
        assert response.ok, response.text()
        assert response.request.post_data_json == {
            "decision": decision, "reason": reason, "reviewId": review["id"], "version": review["version"],
        }
        expect(row).to_have_count(0)
        state = member.request.get(f"{api}/{sid}").json()["item"]
        assert state["status"] == ("rejected" if decision == "reject" else "published")
        if decision == "reject":
            assert state["reviewNote"] == reason

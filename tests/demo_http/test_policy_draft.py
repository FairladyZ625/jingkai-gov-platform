"""验证真实 HTTP 起草不把目录编号或未确认申报窗口当成公文事实。"""

import pytest

from tests.demo_http.password_ui import login

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402


@pytest.mark.parametrize("server", [()], indirect=True)
def test_member_drafts_reward_notice_from_policy_snapshot(server):
    with sync_playwright() as engine, engine.chromium.launch() as browser:
        page = browser.new_page(base_url=server.url, viewport={"width": 1440, "height": 900})
        page.goto("/")
        assert page.evaluate("JK_CONFIG.api.mode") == "http"
        login(page, "wangmin", server.password)
        page.locator('.quick-apps [data-app="document"]').click()
        page.locator('[data-op="document.tpl-T03"]').click()
        page.locator('[data-op="document.sample"]').click()
        policy_id = page.locator('[data-op="document.in-policy"]').input_value()
        policy_reply = page.request.get(f"/api/apps/policy/items/{policy_id}")
        assert policy_reply.ok
        policy = policy_reply.json()["item"]
        assert not policy.get("historical")
        with page.expect_response(lambda res: res.request.method == "POST" and res.url.endswith("/document/drafts")) as result:
            page.get_by_role("button", name="生成初稿", exact=False).click()
        assert result.value.ok
        item = result.value.json()["item"]
        content = item["versions"][0]["content"]
        assert item["policyId"] == policy_id
        assert item["versions"][0]["by"].endswith("（政策模板初稿）")
        assert policy["title"] in content["title"]
        assert content["to"] == "【待补：主送机关】"
        body = "\n".join(content["paragraphs"])
        assert policy_id not in body and "PI-03" not in body
        assert policy["docNo"] in body and policy["docTitle"] in body
        assert policy["rule"]["text"].rstrip("。") in body
        assert all(condition["label"].rstrip("。；") in body for condition in policy["conditions"])
        assert all(section in body for section in ("申报对象", "支持标准", "申报时间", "申报材料", "申报方式"))
        assert "2026年11月11日至2026年11月30日" in body
        assert "【待补：申报渠道及提交方式】" in body
        expect(page.locator(".dc-title")).to_have_text(content["title"])

        # 文档接口仍收口：不能通过直接提交旧 ID，或用没有核对的日期冒充已发布通知。
        url = "/api/apps/document/drafts"
        inputs = {"policy": policy_id, "start": "2026-12-01", "end": "2026-12-31"}
        historic = page.request.post(url, data={"templateId": "T03", "inputs": {**inputs, "policy": "PI-03"}})
        assert historic.status == 400 and "历史" in historic.json()["error"]["message"]
        contradictory = page.request.post(url, data={"templateId": "T03", "inputs": {**inputs, "end": "2026-11-30"}})
        assert contradictory.status == 400
        unknown = page.request.post(url, data={"templateId": "T03", "inputs": {**inputs, "policy": "unknown-policy"}})
        assert unknown.status == 404
        tentative = page.request.post(url, data={"templateId": "T03", "inputs": inputs})
        assert tentative.ok
        paragraphs = tentative.json()["item"]["versions"][0]["content"]["paragraphs"]
        assert any("拟于2026年12月1日至2026年12月31日" in line and "【待补：经确认的申报期限】" in line for line in paragraphs)


@pytest.mark.parametrize("server", [()], indirect=True)
def test_extension_example_agrees_with_offline_attachment(server):
    with sync_playwright() as engine, engine.chromium.launch() as browser:
        page = browser.new_page(base_url=server.url, viewport={"width": 1440, "height": 900})
        page.goto("/")
        login(page, "wangmin", server.password)
        catalog = page.request.get("/api/apps/document/templates").json()["items"]
        template = next(item for item in catalog if item["id"] == "T06")
        inputs = {key: example for key, _, example in template["inputs"]}
        attachment = page.evaluate("JK_SAMPLE_FILES.find(file => file.text.includes('延长至2026-12-15')).text")
        assert "后续批次" in inputs["orig"]
        assert inputs["oldEnd"] == "2026-11-30" and f"延长至{inputs['newEnd']}" in attachment
        assert page.evaluate("JK_APPCFG.document.demoInputs.oldEnd") == inputs["oldEnd"]

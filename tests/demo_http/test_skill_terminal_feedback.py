"""#207：后端拒绝出站时，真实浏览器不显示永久运行中。"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright

from tests.demo_http.password_ui import login


@pytest.mark.parametrize("server", [()], indirect=True)
@pytest.mark.parametrize("trial", [True, False], ids=["trial", "run"])
def test_skill_outbound_denied_is_a_persistent_failure(server, trial):
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page()
        page.goto(server.url)
        assert page.evaluate("JK_CONFIG.api.mode") == "http"
        login(page, "wangmin", server.password)
        api = server.url + "/api/v1/skills"
        generated = page.request.post(api + "/draft", data={"text": "核对数据券申报材料齐不齐"})
        assert generated.ok, generated.text()
        created = page.request.post(api, data=generated.json()["draft"])
        assert created.ok, created.text()
        sid = created.json()["item"]["id"]
        page.locator('#side-sc [data-app="skills"]').click()
        page.locator('[data-op="skills.tab.mine"]').click()
        if trial:
            page.locator(f'[data-edit="{sid}"]').click()
            page.locator("[data-next]").click()
            action = page.locator("[data-trial]")
        else:
            page.locator(f'[data-open="{sid}"]').click()
            action = page.locator("[data-run]")
        page.locator("[data-sample]").click()

        def failed(response):
            return response.url.startswith(api + "/jobs/") and response.ok and (
                response.json()["job"]["status"] == "failed"
            )

        with page.expect_response(failed, timeout=8000) as terminal:
            action.click()
        job = terminal.value.json()["job"]
        assert job["errorCode"] == "OUTBOUND_DENIED"
        assert job["result"] is None
        feedback = page.locator('[data-op="skills.failed"]')
        expect(feedback).to_contain_text("运行失败")
        expect(feedback).to_contain_text("暂无可处理该密级的模型")
        expect(feedback).to_contain_text("请联系管理员")
        expect(page.locator("[data-out]").get_by_text("正在运行", exact=True)).to_have_count(0)
        expect(page.locator('[data-op="skills.result"]')).to_have_count(0)
        expect(action).to_be_enabled()
        # 输入区重绘后保留已知的终态，不恢复旧的「正在运行」卡。
        page.locator("[data-sample]").click()
        expect(feedback).to_be_visible()

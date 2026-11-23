from tests.demo_http.password_ui import login, wait_segment
"""外部协作者段：何军在真后端打开企业档案，前端按后端打码投影渲染（不要求后端多返回联系人或营收）。"""

import re

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402


@pytest.mark.parametrize("server", [()], indirect=True)
def test_partner_opens_masked_profile_over_http(server):
    errors, profiles = [], []
    with sync_playwright() as engine, engine.chromium.launch() as browser:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("response", lambda r: profiles.append((r.status, r.json()))
                if re.search(r"/api/apps/enterprise/companies/E020$", r.url) else None)
        page.goto(server.url)
        assert page.evaluate("JK_CONFIG.api.mode") == "http"
        login(page, "hejun", server.password)
        page.locator('[data-op="chat.input"]').fill("查一下知行应用")
        page.locator('[data-op="chat.send"]').click()
        page.locator("#chatcol .msg.ai .txt", has_text=re.compile("知行应用：|没能完成")).first.wait_for(timeout=30000)
        reply = page.locator("#chatcol .msg.ai .txt").last.inner_text()
        assert "没能完成" not in reply and reply.startswith("知行应用：")

        # 档案请求 200，且后端投影本身不含联系人与营收（暴露面不变）。
        assert profiles and profiles[0][0] == 200
        item = profiles[0][1]["item"]
        assert "contacts" not in item and "revenue" not in item
        profile = page.locator('[data-op="enterprise.profile"]')
        assert "北京知行大模型应用有限公司" in profile.inner_text()
        base = page.locator("#eptab").inner_text()
        assert "已打码 · 无权查看" in base and "undefined" not in base
        page.locator('[data-op="enterprise.ptab-biz"]').click()
        assert "受限字段" in page.locator("#eptab").inner_text()
        # 页面上不出现任何未打码的 11 位手机号。
        assert not re.search(r"(?<!\d)1\d{10}(?!\d)", page.locator("#es").inner_text())
    assert not errors

"""真浏览器 / 真实 HTTP / 仓库公开快照；模型仅用 demo-http 夹具的模拟服务。"""
import os
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright
from tests.demo_http.password_ui import login

FIRST = "数据券补贴最高能拿多少？"
FOLLOW = "请列出这项数据券政策的申报期限、适用对象和需要审签的材料；如果原文没有写，请明确说明"


@pytest.mark.parametrize("server", [()], indirect=True)
def test_panel_and_chat_citation_scopes(server):
    with sync_playwright() as engine, engine.chromium.launch() as browser:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(15000)
        page.goto(server.url)
        login(page, "liyang", server.password)
        op = lambda key: page.locator(f'[data-op="{key}"]').first
        with page.expect_response(lambda r: r.url.endswith("/kb/ask")) as first:
            page.locator(f'[data-say="{FIRST}"]').click()
        initial = first.value.json()
        assert initial["source"] == "preset" and "100万元" in initial["answer"]
        scope = initial["citations"][0]["citationId"]
        expect(page.locator("#chatcol .pstate").last).to_have_text("已完成", timeout=15000)
        expect(page.locator("#kb-scope")).to_contain_text(initial["citations"][0]["title"])

        def send(locator, q):
            locator.fill(q)
            with page.expect_response(lambda r: r.url.endswith("/kb/ask")) as response:
                locator.press("Enter")
            assert response.value.ok
            return response.value.request.post_data_json, response.value.json()

        for entry in ("kb.q", "chat.input"):
            body, result = send(op(entry), FOLLOW)
            assert body["scope"] == scope
            assert {c["citationId"] for c in result["citations"]} == {scope}
            bubble = op("kb.answer") if entry == "kb.q" else page.locator("#chatcol .msg.ai").last
            expect(bubble).to_contain_text("申报期限：原文未明确")
            expect(bubble).to_contain_text("适用于")
            expect(bubble).to_contain_text("审签材料：原文未明确")
        if folder := os.environ.get("KB_SCREENSHOTS"):
            for width in (1440, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                page.screenshot(path=Path(folder) / f"kb-follow-{width}.png")

        body, book = send(op("kb.q"), "实体书店有哪些奖励？")
        assert not body.get("scope") and book["citations"][0]["citationId"] != scope
        expect(page.locator("#kb-scope")).to_contain_text("实体书店")
        op("kb.scope-clear").click()
        expect(page.locator("#kb-scope")).to_be_empty()
        body, _ = send(op("kb.q"), FOLLOW)
        assert not body.get("scope")
        send(op("kb.q"), FIRST)
        op("chat.new").click()
        op("nav.kb").click()
        expect(page.locator("#kb-scope")).to_be_empty()
        send(op("kb.q"), FIRST)
        page.evaluate("void JKShell.switchUser('hejun')")
        op("switch.password").fill(server.password)
        page.locator('[role="dialog"] [data-ok]').click()
        page.wait_for_function("JKShell.S.me?.username === 'hejun'")
        op("nav.kb").click()
        expect(page.locator("#kb-scope")).to_be_empty()

from tests.demo_http.password_ui import login, wait_segment
"""原型 HTTP 适配层对真后端的请求格式：用真实 Chromium 调用 JKApi，模拟后端不参与。"""

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402


def _page(engine, server):
    browser = engine.chromium.launch()
    page = browser.new_page()
    page.goto(server.url)
    response = page.request.post(server.url + "/api/v1/auth/login",
                                 data={"username": "wangmin", "password": server.password})
    assert response.ok
    assert page.evaluate("JK_CONFIG.api.mode") == "http"
    return browser, page


@pytest.mark.parametrize("server", [()], indirect=True)
def test_meeting_sample_upload_uses_multipart_demo_audio(server):
    with sync_playwright() as engine:
        browser, page = _page(engine, server)
        try:
            item = page.evaluate("""() => JKApi.meeting.create({title: '演示例会', type: '企业座谈会',
                participants: ['王敏'], file: '【示例】座谈会录音.m4a', size: '1 MB', source: '对话拖入'})
                .then(r => r.item)""")
            assert item["source"] == "demo" and item["participants"] == ["王敏"]
            uploaded = page.evaluate("""() => JKApi.meeting.create({title: '上传例会', type: '局务会',
                participants: [], file: 'a.webm', blob: new Blob([new Uint8Array([26, 69, 223, 163])], {type: 'audio/webm'})})
                .then(r => ({ok: true, item: r.item}), e => ({ok: false, status: e.status}))""")
            assert uploaded["ok"] and uploaded["item"]["source"] == "upload"
            assert uploaded["item"]["file"] == "a.webm" and uploaded["item"]["size"] == 4
        finally:
            browser.close()


def test_computer_summary_guards_missing_enterprise():
    # 真后端 apply 任务可带 ent=None；收尾文案不得直接读 r.ent.short。
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "web/apps/computer/app.js").read_text(encoding="utf-8")
    assert "${r.ent.short}" not in source
    assert "(r && r.ent && r.ent.short) || '示例企业'" in source


@pytest.mark.parametrize("server", [()], indirect=True)
def test_review_inbox_marks_assignee_and_decides_with_version(server):
    import httpx

    with httpx.Client(base_url=server.url, trust_env=False) as c:
        c.post("/api/v1/auth/login", json={"username": "wangmin", "password": server.password}).raise_for_status()
        draft = c.post("/api/apps/document/drafts", json={"templateId": "T06", "inputs": {
            "orig": "公开演示通知", "oldEnd": "2026-11-20", "newEnd": "2026-12-15", "reason": "系统维护",
            "to": "各有关企业：", "sign": "公文演示工作组", "date": "2026年11月18日"}}).json()["item"]
        submitted = c.post(f"/api/apps/document/drafts/{draft['id']}/submit", json={"assignee": "u-liyang"})
        assert submitted.status_code == 200, submitted.text
        review_id = submitted.json()["review"]["id"]
    with sync_playwright() as engine:
        browser = engine.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(server.url)
            login(page, "liyang", server.password)
            page.wait_for_function("JKShell.S.me && JKShell.S.me.username === 'liyang'")
            item = page.evaluate("id => JKApi.reviews.list().then(r => r.items.find(x => x.id === id))", review_id)
            assert item["approver"] is True and item["type"] == "review"
            decided = page.evaluate("id => JKApi.reviews.decide(id, {decision: 'approve', comment: ''})", review_id)
            assert decided["item"]["decision"]["decision"] == "approve"
        finally:
            browser.close()

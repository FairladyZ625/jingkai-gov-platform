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

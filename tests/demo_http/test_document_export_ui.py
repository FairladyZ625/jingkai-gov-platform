"""#209：从真实浏览器下载公文，并验证 Word 文件与正文。"""
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from docx import Document
from playwright.sync_api import expect, sync_playwright

from tests.demo_http.password_ui import login


def test_offline_document_export_still_downloads_html_word():
    entry = Path(__file__).resolve().parents[2] / "prototype/v4/index.html"
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page(offline=True, accept_downloads=True)
        page.goto(entry.as_uri())
        page.locator('[data-u="wangmin"]').click()
        page.locator('[data-op="nav.document"]').click()
        draft = page.evaluate("""async () => (await JKApi.document.draft({
            templateId: 'T06',
            inputs: {orig: '离线虚拟申请', oldEnd: '2026-11-20', newEnd: '2026-11-25', reason: '离线验收'},
        })).item""")
        page.evaluate("async id => JKShell.openApp('document', 'detail', {id})", draft["id"])
        with page.expect_download() as downloaded:
            page.locator('[data-op="document.word"]').click()
        artifact = downloaded.value
        assert artifact.suggested_filename == draft["title"] + ".doc"
        assert "离线验收" in Path(artifact.path()).read_text(encoding="utf-8")


@pytest.mark.parametrize("server", [()], indirect=True)
def test_document_word_export_downloads_valid_docx(server):
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page(accept_downloads=True)
        page.goto(server.url)
        assert page.evaluate("JK_CONFIG.api.mode") == "http"
        login(page, "wangmin", server.password)
        draft_url = server.url + "/api/apps/document/drafts"
        created = page.request.post(draft_url, data={
            "templateId": "T06", "inputs": {
                "orig": "导出验收虚拟申请", "oldEnd": "2026-11-20", "newEnd": "2026-11-25",
                "reason": "隔离验收",
            },
        })
        assert created.ok, created.text()
        item = created.json()["item"]
        page.locator('[data-op="nav.document"]').click()
        page.locator('[data-op="document.tab-list"]').click()
        page.locator(f'[data-open="{item["id"]}"]').click()
        export = page.locator('[data-op="document.word"]')
        with page.expect_download() as downloaded:
            export.click()
        file = downloaded.value
        assert file.suggested_filename == item["title"] + "（草稿）.docx"
        path = Path(file.path())
        assert path.read_bytes()[:4] == b"PK\x03\x04"
        paragraphs = [p.text for p in Document(str(path)).paragraphs]
        assert paragraphs[0] == item["title"] + "（草稿）"
        assert any("隔离验收" in p for p in paragraphs[1:])

        # 代理误回 200 HTML 时，界面必须报错而不是再下载一个坏文档。
        unexpected = []
        page.on("download", lambda item: unexpected.append(item))
        page.route(f'{draft_url}/{item["id"]}/export',
                   lambda route: route.fulfill(status=200, content_type="text/html", body="<p>维护中</p>"))
        export.click()
        expect(page.get_by_text("未收到可用的 Word 文件", exact=True)).to_be_visible()
        assert not unexpected

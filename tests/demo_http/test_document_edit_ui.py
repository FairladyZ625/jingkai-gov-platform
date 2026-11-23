"""#196：隔离浏览器回归公文首击保存、版本回显及离开确认。"""
import re

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright

from tests.demo_http.password_ui import login


def open_draft(page, server):
    page.goto(server.url)
    assert page.evaluate("JK_CONFIG.api.mode") == "http"
    login(page, "wangmin", server.password)
    root = server.url + "/api/apps/document/drafts"
    created = page.request.post(root, data={
        "templateId": "T06", "inputs": {
            "orig": "虚构申请编辑验收", "oldEnd": "2026-11-20",
            "newEnd": "2026-11-25", "reason": "隔离测试",
        },
    })
    assert created.ok, created.text()
    draft = created.json()["item"]
    page.locator('[data-op="nav.document"]').click()
    page.locator('[data-op="document.tab-list"]').click()
    page.locator(f'[data-op="document.row-{draft["id"]}"]').click()
    return draft, f'{root}/{draft["id"]}'


def edit_title(page, title):
    page.locator('.dc-paper [data-pe="title"]').click()
    editor = page.locator('.dc-paper [data-ed="title"]')
    editor.fill(title)
    expect(editor).to_be_focused()


@pytest.mark.parametrize("server", [()], indirect=True)
def test_click_save_once_while_editing_and_list_reads_new_version(server):
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page()
        draft, url = open_draft(page, server)
        old_version = draft["versions"][-1]["v"]
        title = "一次保存验收标题"
        edit_title(page, title)
        button = page.locator('[data-op="document.save"]')
        with page.expect_response(lambda r: r.url == url and r.request.method == "PUT", timeout=4000) as saved:
            button.click()
        assert saved.value.ok, saved.value.text()
        version = saved.value.json()["item"]["versions"][-1]["v"]
        assert version == old_version + 1
        expect(page.locator(".dc-paper .dc-title")).to_have_text(title)
        expect(page.locator("#ds .q .meta")).to_have_text(f"第 {version} 版")
        page.locator('[data-op="document.tab-list"]').click()
        row = page.locator(f'[data-op="document.row-{draft["id"]}"]')
        expect(row.locator("td").nth(0)).to_contain_text(title)
        expect(row.locator("td").nth(2)).to_have_text(str(version))
        expect(row.locator("td").nth(3)).to_have_text(re.compile(r"年\d+月\d+日 \d{2}:\d{2}"))


@pytest.mark.parametrize("server", [()], indirect=True)
def test_leaving_for_list_requires_confirmation_and_cancel_keeps_edits(server):
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page()
        draft, url = open_draft(page, server)
        title = "不能静默丢掉的未保存标题"
        tab = page.locator('[data-op="document.tab-list"]')
        edit_title(page, title)
        tab.click()
        dialog = page.get_by_role("dialog").filter(has_text="未保存的修改")
        expect(dialog).to_be_visible(timeout=3500)
        dialog.get_by_role("button", name="取消").click()
        expect(page.locator(".dc-paper .dc-title")).to_have_text(title)
        expect(page.locator('[data-op="document.save"]')).to_be_visible()

        tab.click()
        dialog.get_by_role("button", name="放弃修改").click()
        row = page.locator(f'[data-op="document.row-{draft["id"]}"]')
        expect(row).to_contain_text(draft["title"])
        assert page.request.get(url).json()["item"]["title"] == draft["title"]


@pytest.mark.parametrize("server", [()], indirect=True)
def test_list_label_and_metadata_match_the_actual_visible_scope(server):
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        admin, member = browser.new_page(), browser.new_page()
        for page, account in ((admin, "admin"), (member, "wangmin")):
            page.goto(server.url)
            assert page.evaluate("JK_CONFIG.api.mode") == "http"
            login(page, account, server.password)
        response = admin.request.post(server.url + "/api/apps/document/drafts", data={
            "templateId": "T06", "inputs": {"orig": "合成文稿可见范围", "oldEnd": "2026-11-20",
            "newEnd": "2026-11-25", "reason": "隔离演示"},
        })
        assert response.ok, response.text()
        draft = response.json()["item"]
        member.locator('[data-op="nav.document"]').click()
        tab = member.locator('[data-op="document.tab-list"]')
        expect(tab).to_contain_text("可见文稿")
        tab.click()
        expect(member.get_by_text("当前账号有权查看的文稿，不限本人创建。", exact=True)).to_be_visible()
        row = member.locator(f'[data-op="document.row-{draft["id"]}"]')
        expect(row).to_contain_text(draft["author"])
        expect(row.locator("td").nth(2)).to_have_text("0")
        expect(row.locator("td").nth(3)).to_have_text(re.compile(r"年\d+月\d+日 \d{2}:\d{2}"))
        row.click()
        expect(member.locator(".dc-paper .dc-title")).to_have_text(draft["title"])
        expect(member.locator("#ds .q .meta")).to_have_text("第 0 版")

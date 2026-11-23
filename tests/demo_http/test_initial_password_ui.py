"""在隔离 HTTP 实例和离线演示里验证初始口令发放，不接触线上账号。"""

from pathlib import Path

import pytest

from tests.demo_http.password_ui import login

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402


def issued_password(page, *, real_http=True):
    issued = page.get_by_role("dialog").filter(has_text="仅在本次弹窗查看")
    expect(issued).to_be_visible()
    field = issued.locator("[data-issued-password]")
    expect(field).to_have_count(0)
    reveal = issued.get_by_role("button", name="查看口令")
    reveal.click()
    expect(reveal).to_be_disabled()
    value = field.input_value()
    assert len(value) >= 24
    issued.get_by_role("button", name="关闭", exact=True).first.click()
    expect(issued).to_have_count(0)
    if real_http:
        assert not page.evaluate("secret => JSON.stringify(localStorage).includes(secret)", value)
    return value


@pytest.mark.parametrize("server", [()], indirect=True)
def test_create_and_reset_issue_distinct_credentials_without_echo(server):
    with sync_playwright() as engine, engine.chromium.launch() as browser:
        admin = browser.new_page(base_url=server.url, viewport={"width": 1440, "height": 900})
        member = browser.new_page(base_url=server.url)
        admin.goto("/")
        assert admin.evaluate("JK_CONFIG.api.mode") == "http"
        login(admin, "admin", server.password)
        admin.locator('[data-op="rail.admin"]').click()
        created = []
        for username in ("fixture-account-a", "fixture-account-b"):
            admin.get_by_role("button", name="新增账号").click()
            create = admin.get_by_role("dialog").filter(has_text="新增账号")
            expect(create.get_by_text("系统为新账号生成独立口令", exact=False)).to_be_visible(timeout=3000)
            create.locator('[data-op="admin.u-name"]').fill(username)
            create.locator('[data-op="admin.u-username"]').fill(username)
            with admin.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/admin/users")) as response:
                create.get_by_role("button", name="创建", exact=True).click()
            assert response.value.ok
            item = response.value.json()["item"]
            assert item["status"] == "active"
            secret = issued_password(admin)
            assert secret not in response.value.text()
            created.append((item["id"], username, secret))
        uid, username, previous = created[0]
        assert previous != created[1][2]
        session = "/api/v1/auth/session"
        entry = "/api/v1/auth/login"
        assert member.request.post(entry, data={"username": username, "password": previous}).ok
        assert member.request.get(session).json()["user"]["username"] == username

        admin.locator(f'[data-more="{uid}"]').click()
        admin.get_by_text("重置密码", exact=True).click()
        with admin.expect_response(lambda r: r.request.method == "PATCH" and r.url.endswith(f"/admin/users/{uid}")) as response:
            admin.get_by_role("dialog").get_by_role("button", name="重置", exact=True).click()
        assert response.value.ok
        rotated = issued_password(admin)
        assert rotated not in (previous, created[1][2]) and rotated not in response.value.text()
        assert member.request.get(session).json()["user"] is None
        assert member.request.post(entry, data={"username": username, "password": previous}).status == 401
        assert member.request.post(entry, data={"username": username, "password": rotated}).ok
        audit = admin.request.get("/api/v1/audit", params={"limit": 100}).text()
        users = admin.request.get("/api/v1/admin/users").text()
        assert all(secret not in audit + users for secret in (previous, created[1][2], rotated))


def test_offline_mock_can_use_issued_password_but_has_no_default():
    root = Path(__file__).resolve().parents[2]
    with sync_playwright() as engine, engine.chromium.launch(args=["--allow-file-access-from-files"]) as browser:
        page = browser.new_page(offline=True, viewport={"width": 1440, "height": 900})
        page.goto((root / "prototype/v4/index.html").as_uri())
        assert page.evaluate("JK_CONFIG.api.mode") == "mock"
        page.locator('[data-u="admin"]').click()
        page.locator('[data-op="rail.admin"]').click()
        pending = page.evaluate("JKApi.admin.createUser({username: 'fixture-pending', name: '模拟预留账号'})")
        assert pending["item"]["status"] == "disabled" and "password" not in pending["item"]

        page.get_by_role("button", name="新增账号").click()
        create = page.get_by_role("dialog").filter(has_text="新增账号")
        create.locator('[data-op="admin.u-name"]').fill("模拟验收账号")
        create.locator('[data-op="admin.u-username"]').fill("fixture-mock-account")
        create.get_by_role("button", name="创建", exact=True).click()
        generated = issued_password(page, real_http=False)
        logged_in = page.evaluate("password => JKApi.auth.login({username: 'fixture-mock-account', password})", generated)
        assert logged_in["user"]["username"] == "fixture-mock-account" and "password" not in logged_in["user"]

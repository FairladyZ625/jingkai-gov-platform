"""会议录音派发只投影给真实负责人，不另造一份任务。"""
from contextlib import ExitStack
import time

import httpx
import pytest

from tests.demo_http.password_ui import login


def payload(response):
    assert response.is_success, response.text
    return response.json()


def prepare_assignment(sender):
    base = "/api/apps/meeting/meetings"
    meeting = payload(sender.post(base, data={"title": "隔离会议待办验收", "source": "demo"}))["item"]
    path = f"{base}/{meeting['id']}"
    job = payload(sender.post(path + "/transcribe", json={}))["job"]
    deadline = time.monotonic() + 20
    while job["status"] != "done":
        assert job["status"] not in {"cancelled", "failed"} and time.monotonic() < deadline
        time.sleep(0.1)
        job = payload(sender.get(f"/api/v1/jobs/{job['id']}"))["job"]
    todo = payload(sender.get(path))["item"]["todos"][0]
    payload(sender.patch(path, json={"todo": {"id": todo["id"], "owner": "u-liyang", "due": "2026-11-28"}}))
    commit = path + "/todos/commit"
    assert payload(sender.post(commit, json={"ids": [todo["id"]]}))["committed"] == [todo["id"]]
    assert payload(sender.post(commit, json={"ids": [todo["id"]]}))["committed"] == []
    return meeting, todo


@pytest.mark.parametrize("server", [()], indirect=True)
def test_meeting_todo_is_visible_only_to_recipient_and_can_be_completed(server):
    with ExitStack() as stack:
        sender, recipient, other = [stack.enter_context(httpx.Client(base_url=server.url, timeout=10)) for _ in range(3)]
        for client, user in ((sender, "wangmin"), (recipient, "liyang"), (other, "hejun")):
            payload(client.post("/api/v1/auth/login", json={"username": user, "password": server.password}))
        meeting, _ = prepare_assignment(sender)
        meeting_todos = payload(recipient.get("/api/apps/meeting/my-todos"))["items"]
        [key] = [item["id"] for item in meeting_todos if item["ref"]["meetingId"] == meeting["id"]]
        todos = "/api/v1/todos"
        inbox = "/api/v1/inbox"
        change = f"{todos}/{key}"
        assert payload(other.get(todos))["items"] == []
        for client in (sender, other):
            assert client.patch(change, json={"done": True}).status_code == 404
            assert not any(item["id"] == key for item in payload(client.get(inbox, params={"box": "todo"}))["items"])
        for url in (todos, inbox + "?box=todo"):
            [item] = [row for row in payload(recipient.get(url))["items"] if row["id"] == key]
            assert not item["done"] and item["ref"]["meetingId"] == meeting["id"]
        assert payload(recipient.patch(change, json={"done": True}))["item"]["done"] is True
        assert not any(item["id"] == key for item in payload(recipient.get(inbox + "?box=todo"))["items"])
        assert any(item["id"] == key for item in payload(recipient.get(inbox + "?box=done"))["items"])
        assert payload(recipient.patch(change, json={"done": False}))["item"]["done"] is False


@pytest.mark.parametrize("server", [()], indirect=True)
def test_recipient_can_complete_from_inbox_and_read_full_minute_timestamps(server):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as engine, engine.chromium.launch() as browser:
        page = browser.new_page(base_url=server.url, viewport={"width": 1440, "height": 900})
        page.goto("/")
        login(page, "liyang", server.password)
        with httpx.Client(base_url=server.url) as sender:
            payload(sender.post("/api/v1/auth/login", json={"username": "wangmin", "password": server.password}))
            meeting, todo = prepare_assignment(sender)
        inbox = page.request.get("/api/v1/todos")
        assert inbox.ok
        [key] = [item["id"] for item in inbox.json()["items"]
                 if item["ref"]["meetingId"] == meeting["id"]]
        page.locator('[data-op="rail.inbox"]').click()
        page.get_by_role("button", name="我的待办").click()
        row = page.locator(".inb-i").filter(has=page.locator(f'[data-todo="{key}"]'))
        playwright.expect(row).to_be_visible()
        playwright.expect(row).to_contain_text(todo["task"])
        with page.expect_response(lambda res: res.request.method == "PATCH" and "/api/v1/todos/" in res.url) as changed:
            row.locator('[data-todo]').check()
        assert changed.value.ok and changed.value.json()["item"]["done"]
        playwright.expect(row).to_have_count(0)

        page.evaluate("id => JKShell.openApp('meeting', 'detail', {meetingId:id})", meeting["id"])
        paper = page.locator('[data-op="meeting.minutes"]')
        playwright.expect(paper.locator("h4")).to_have_text(["发言片段 1 · 发言人 1", "发言片段 2 · 发言人 2"])
        playwright.expect(paper.locator('.mt-meta').first).to_contain_text("年")
        playwright.expect(paper.locator('.mt-meta').last).to_have_text("参会：未登记")
        playwright.expect(paper.locator('[data-ref="00:05.716"]')).to_have_text("00:05")

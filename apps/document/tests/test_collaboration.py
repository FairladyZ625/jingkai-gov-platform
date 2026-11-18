from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from haiknow_sdk.resources import Records

from .test_drafting import APP, ROOT, assert_error, content, create, document_client, item, login


def mount_collaboration(client):
    from haiknow_apps.document.collaboration_router import router

    # 生产注册由应用入口负责，本任务在真实平台上单独挂载协作路由。
    client.app.include_router(router, prefix=APP)
    return client


@pytest.fixture
def collaboration_client(document_client):
    return mount_collaboration(document_client)


def drafts_url(client):
    draft = item(create(client))
    return draft, f"{APP}/drafts/{draft['id']}"


def assert_parts(parts, before, after):
    assert all(part["t"] and part["op"] in {"eq", "del", "add"} for part in parts)
    assert "".join(p["t"] for p in parts if p["op"] != "add") == before
    assert "".join(p["t"] for p in parts if p["op"] != "del") == after


def assert_stats(result):
    assert set(result) == {"parts", "stats"}
    for op in ("add", "del"):
        assert result["stats"][op] == sum(len(p["t"].encode("utf-16-le")) // 2
                                           for p in result["parts"] if p["op"] == op)


def assert_beijing_time(value):
    assert datetime.fromisoformat(value).utcoffset() == timedelta(hours=8)


def test_polish_previews_only_then_put_creates_a_version(collaboration_client):
    client = collaboration_client
    draft, url = drafts_url(client)
    original = {**content(draft), "paragraphs": ["请帮忙提交申报。", "经认真研究，请赶紧完成申报。"]}
    saved = item(client.put(url, json={"content": original}))
    form = client.post(f"{url}/polish", json={"style": "formal", "para": 0})
    assert form.status_code == 200, form.text
    result = form.json()
    assert set(result) == {"preview", "parts", "changed"}
    assert result["changed"] is True
    assert result["preview"] == {**original, "paragraphs": ["请协助提交申报。", original["paragraphs"][1]]}
    assert_parts(result["parts"], "\n".join(original["paragraphs"]), "\n".join(result["preview"]["paragraphs"]))
    assert item(client.get(url)) == saved
    concise = client.post(f"{url}/polish", json={"style": "concise"}).json()
    assert concise["preview"]["paragraphs"] == [original["paragraphs"][0], "请赶紧完成申报。"]
    assert item(client.get(url)) == saved

    audit = client.app.state.platform.store.audit_list("document")
    mock_calls = [r for r in audit if r["action"] == "document.polish.mock"]
    assert [(r["user"], r["detail"]) for r in mock_calls] == [
        ("sampleoperator", {"recordId": draft["id"], "provider": "mock", "style": style})
        for style in ("concise", "formal")
    ]
    adopted = item(client.put(url, json={"content": result["preview"], "note": "采用润色"}))
    assert len(adopted["versions"]) == len(saved["versions"]) + 1
    assert content(adopted) == result["preview"]
    unchanged = client.post(f"{url}/polish", json={"style": "formal", "para": 0}).json()
    assert unchanged["changed"] is False
    assert all(part["op"] == "eq" for part in unchanged["parts"])


def test_compare_exact_versions_including_first_draft(collaboration_client):
    client = collaboration_client
    draft, url = drafts_url(client)
    saved = item(client.put(url, json={"content": {**content(draft), "title": "新标题"}}))
    a, b = {"id": draft["id"], "v": 0}, {"id": draft["id"], "v": 1}
    payload = client.post(f"{APP}/compare", json={"a": a, "b": b}).json()
    assert_stats(payload)
    assert payload["stats"]["add"] > 0 and payload["stats"]["del"] > 0
    assert ["".join(p["t"] for p in payload["parts"] if p["op"] != ignored).split("\n")[0]
            for ignored in ("add", "del")] == [content(draft)["title"], content(saved)["title"]]
    identical = client.post(f"{APP}/compare", json={"a": b, "b": b}).json()
    assert identical["stats"] == {"add": 0, "del": 0}
    assert all(part["op"] == "eq" for part in identical["parts"])
    assert_error(client.post(f"{APP}/compare", json={"a": {**a, "v": 8}, "b": b}), 404, "NOT_FOUND")


@pytest.mark.parametrize("before,after,stats", [
    pytest.param("请发甲稿。", "请发乙稿。", {"add": 1, "del": 1}, id="replacement"),
    pytest.param("附图📄", "附图", {"add": 0, "del": 2}, id="utf16"),
    pytest.param("没有变化。" * 1000, "没有变化。" * 1000, {"add": 0, "del": 0}, id="same-long-text"),
    pytest.param("", "", {"add": 0, "del": 0}, id="empty"),
])
def test_compare_text(collaboration_client, before, after, stats):
    response = collaboration_client.post(f"{APP}/compare", json={"a": before, "b": after})
    assert response.status_code == 200, response.text
    result = response.json()
    assert_parts(result["parts"], before, after)
    assert_stats(result)
    assert result["stats"] == stats


def test_finalized_document_allows_comments_but_not_adoption(collaboration_client, make_client):
    client = collaboration_client
    draft, url = drafts_url(client)
    review = client.post("/api/v1/reviews", json={
        "appId": "document", "recordId": draft["id"], "version": 1, "assignee": "samplereviewer",
    })
    assert review.status_code == 201, review.text
    login(client, "samplereviewer")
    response = client.post(f"/api/v1/reviews/{review.json()['id']}/decisions", json={"version": 1, "decision": "confirm"})
    assert response.status_code == 200, response.text
    login(client, "sampleoperator")
    assert item(client.get(url))["status"] == "已定稿"

    created = item(client.post(f"{url}/comments", json={"para": 0, "text": " 请保留原条款。 "}))
    assert created == {"id": created["id"], "para": 0, "by": "样例办理员", "at": created["at"],
                       "text": "请保留原条款。", "replies": [], "resolved": False}
    assert_beijing_time(created["at"])
    comment_url = f"{url}/comments/{created['id']}"
    login(client, "sampleadmin")
    replied = item(client.patch(comment_url, json={"reply": "已核对。"}))
    assert replied["replies"] == [{"by": "样例管理员", "text": "已核对。", "at": replied["replies"][0]["at"]}]
    assert_beijing_time(replied["replies"][0]["at"])
    resolved = item(client.patch(comment_url, json={"resolved": True}))
    assert resolved == {**replied, "resolved": True, "resolvedBy": "样例管理员", "resolvedAt": resolved["resolvedAt"]}
    assert_beijing_time(resolved["resolvedAt"])
    client = mount_collaboration(make_client(ROOT / "apps"))
    login(client, "sampleoperator")
    assert item(client.patch(comment_url, json={"resolved": True})) == resolved

    from haiknow_apps.document.comments import by_draft

    platform = client.app.state.platform
    records = Records(platform.data, platform.directory.user("sampleoperator"), "document")
    assert by_draft(SimpleNamespace(records=records)) == {draft["id"]: [resolved]}
    audit = platform.store.audit_list("document")
    assert [(r["user"], r["detail"]["version"]) for r in reversed(audit)
            if r["action"] == "v1.record.save" and r["detail"]["recordId"] == created["id"]] == [
                ("sampleoperator", 1), ("sampleadmin", 2), ("sampleadmin", 3),
            ]
    preview = client.post(f"{url}/polish", json={"style": "formal"}).json()["preview"]
    assert_error(client.put(url, json={"content": preview}), 409, "LOCKED")
    assert item(client.get(url))["versions"] == draft["versions"]


def test_concurrent_replies_preserve_each_other_and_resolution(collaboration_client):
    client = collaboration_client
    _, url = drafts_url(client)
    created = item(client.post(f"{url}/comments", json={"para": 0, "text": "注释"}))
    comment_url = f"{url}/comments/{created['id']}"
    requests = [{"reply": "回复甲"}, {"reply": "回复乙"}, {"resolved": True}]

    def patch(body):
        return item(client.patch(comment_url, json=body))

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(patch, requests))
    final = patch({"resolved": True})
    assert {reply["text"] for reply in final["replies"]} == {"回复甲", "回复乙"}
    assert final["resolved"] is True
    assert patch({"resolved": False})["resolved"] is False


def test_collaboration_rejects_invalid_inputs_and_other_drafts(collaboration_client):
    client = collaboration_client
    draft, url = drafts_url(client)
    _, other_url = drafts_url(client)
    for body in ({"style": "unknown"}, {"style": "formal", "para": 99}, {"style": "formal", "para": True}):
        assert_error(client.post(f"{url}/polish", json=body), 400, "INVALID_REQUEST")
    for body in ({"para": -1, "text": "段落无效"}, {"para": 99, "text": "段落无效"}, {"para": 0, "text": " "}):
        assert_error(client.post(f"{url}/comments", json=body), 400, "INVALID_REQUEST")
    created = item(client.post(f"{url}/comments", json={"para": 0, "text": "注释"}))
    for body in ({}, {"reply": " "}, {"resolved": "true"}):
        assert_error(client.patch(f"{url}/comments/{created['id']}", json=body), 400, "INVALID_REQUEST")
    for target in (f"{other_url}/comments/{created['id']}", f"{url}/comments/missing"):
        assert_error(client.patch(target, json={"resolved": True}), 404, "NOT_FOUND")
    assert_error(client.post(f"{APP}/compare", json={"a": {"id": draft["id"], "v": -1}, "b": ""}),
                 400, "INVALID_REQUEST")

    login(client, "sampleobserver")
    assert_error(client.post(f"{url}/polish", json={"style": "formal"}), 403, "FORBIDDEN")
    assert_error(client.post(f"{url}/comments", json={"para": 0, "text": "注释"}), 403, "FORBIDDEN")
    assert client.post(f"{APP}/compare", json={"a": "甲", "b": {"id": draft["id"], "v": 0}}).status_code == 200
    login(client, "sampleoutsider")
    assert_error(client.post(f"{APP}/compare", json={"a": {"id": draft["id"], "v": 0}, "b": ""}), 404, "NOT_FOUND")
    assert_error(client.patch(f"{url}/comments/{created['id']}", json={"resolved": True}), 404, "NOT_FOUND")
    client.cookies.clear()
    assert_error(client.post(f"{APP}/compare", json={"a": "甲", "b": "乙"}), 401, "UNAUTHENTICATED")

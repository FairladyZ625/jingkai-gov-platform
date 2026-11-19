"""通过公文应用真实入口验证路由、数据版本及权限。"""

import json
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from haiknow_sdk.ai import AI, AIError
from haiknow_sdk.resources import Records

from jkq.app import create_app

APP = "/api/apps/document"
APPS = Path(__file__).resolve().parents[2]
PASSWORD = secrets.token_urlsafe(12)
INPUTS = {
    "orig": "示例征集通知", "oldEnd": "2026-11-02", "newEnd": "2026-11-06", "reason": "示例原因",
    "docNo": "测试[2026]08号", "to": "各单位", "sign": "测试单位", "date": "2026年11月1日",
}


class Knowledge:
    status = "现行有效"

    def detail(self, user, identity, version=None):
        assert identity == "policy-sample"
        return {"id": identity, "space": "policy", "title": "示例政策",
                "version": 1, "status": self.status, "text": "示例政策正文。"}


@pytest.fixture
def document(isolated_platform, cheap_password_hash, monkeypatch):
    config, _ = isolated_platform
    path = config / "projects.yaml"
    seed = json.loads(path.read_text())
    seed["companies"][0]["projects"] = [{"id": "jkq", "name": "示例经开区", "products": []}]
    path.write_text(json.dumps(seed))
    path = config / "roles.yaml"
    roles = {
        "admin": {"name": "管理员", "grants": {"*": ["view", "operate", "approve", "admin"]}},
        "sampleobserver": {"name": "观察员", "grants": {"document": ["view"]}},
        "samplereviewer": {"name": "审核员", "grants": {"document": ["view", "approve"]}},
    }
    path.write_text(json.dumps({"apps": ["document"], "roles": roles}))
    accounts = {"sampleadmin": "admin", "sampleobserver": "sampleobserver", "samplereviewer": "samplereviewer"}
    (config / "users.yaml").write_text(json.dumps({"demoUsers": [
        {"id": identity, "username": identity, "name": identity, "role": role, "passwordEnv": "JKQ_TEST_DOC_PASSWORD"}
        for identity, role in accounts.items()
    ]}))
    monkeypatch.setattr(AI, "chat", lambda *args, **kwargs: {"result": '{"issues":[]}'})
    monkeypatch.delenv("HAIKNOW_ROOT", raising=False)
    monkeypatch.delenv("JKQ_WEB_DIR", raising=False)
    monkeypatch.delenv("JKQ_MOCK_GOV_URL", raising=False)
    monkeypatch.delenv("HAIKNOW_DEMO_LOGIN", raising=False)
    monkeypatch.setenv("JKQ_DEMO_MODE", "1")
    monkeypatch.setenv("JKQ_TEST_DOC_PASSWORD", PASSWORD)
    monkeypatch.setenv("HAIKNOW_SECRET", "jkq-test-session-signing")
    monkeypatch.setenv("HAIKNOW_APPS_DIR", str(APPS))
    with TestClient(create_app()) as client:
        login(client, "sampleadmin")
        knowledge = Knowledge()
        client.app.state.platform.kb = knowledge
        yield client, knowledge


def login(client, identity):
    payload(client.post("/api/v1/auth/login", json={"username": identity, "password": PASSWORD}))


def payload(response):
    assert response.status_code == 200, response.text
    return response.json()


def create(client, **kwargs):
    original = payload(client.post(f"{APP}/drafts", json={"templateId": "T06", "inputs": INPUTS, **kwargs}))["item"]
    return f"{APP}/drafts/{original['id']}", original


def test_check_fix_and_recheck_persist_new_version(document):
    client, knowledge = document
    url, original = create(client, refs=[{"id": "policy-sample"}], extra=["载止时间另行通知。"])
    knowledge.status = "已失效"
    finding = payload(client.post(f"{url}/check"))
    assert finding["languageCheck"]["status"] == "completed"
    issues = finding["issues"]
    assert all({"id", "level", "kind", "text", "para"} <= set(issue) for issue in issues)
    expired, = [issue for issue in issues if issue["kind"] == "政策引用"]
    assert (expired["level"], expired["para"]) == ("error", 3)
    ids = [issue["id"] for issue in issues if "fix" in issue]
    fixed = payload(client.post(f"{url}/fix", json={"ids": [*ids, "不存在"]}))
    item = fixed["item"]
    assert fixed["ignoredIds"] == ["不存在"] and fixed["unfixableIds"] == []
    assert item["versions"][-1]["v"] == original["versions"][-1]["v"] + 1
    assert item["refs"] == []
    assert payload(client.get(url))["item"] == item
    assert payload(client.get(url, params={"version": 0}))["item"]["versions"] == original["versions"]
    recheck = payload(client.post(f"{url}/check"))
    assert recheck["issues"] == fixed["issues"]
    assert [(issue["kind"], issue["level"]) for issue in recheck["issues"]] == [("缺要素", "error")]
    repeated = payload(client.post(f"{url}/fix", json={"ids": ids}))
    assert repeated["item"] == item
    assert repeated["ignoredIds"] == ids


def test_language_failure_and_request_errors(document, monkeypatch):
    client, _ = document
    url, original = create(client)
    rules = payload(client.post(f"{url}/check"))["issues"]

    def unavailable(*_args, **_kwargs):
        raise AIError("timeout", "模拟语言检查超时")

    monkeypatch.setattr(AI, "chat", unavailable)
    assert payload(client.post(f"{url}/check")) == {
        "issues": rules, "languageCheck": {"status": "incomplete", "message": "语言检查未完成"},
    }
    assert client.post(f"{url}/fix", json={"ids": "错误类型"}).json()["error"]["code"] == "INVALID_REQUEST"
    assert client.post(f"{APP}/drafts/missing/check").json()["error"]["code"] == "NOT_FOUND"
    assert payload(client.post(f"{url}/fix", json={"ids": []}))["item"] == original

    login(client, "sampleobserver")
    assert client.post(f"{url}/check").status_code == 200
    denied = client.post(f"{url}/fix", json={"ids": []})
    assert (denied.status_code, denied.json()["error"]["code"]) == (403, "FORBIDDEN")
    client.cookies.clear()
    unauth = client.post(f"{url}/check")
    assert (unauth.status_code, unauth.json()["error"]["code"]) == (401, "UNAUTHENTICATED")


def test_fix_does_not_overwrite_concurrent_version(document, monkeypatch):
    client, _ = document
    url, original = create(client)
    ids = [issue["id"] for issue in payload(client.post(f"{url}/check"))["issues"] if "fix" in issue]
    save = Records.save

    def save_with_concurrent_edit(records, *, id=None, **body):
        data = records.get(id)["data"]
        content = {**data["content"], "title": "并发修改的通知"}
        save(records, id=id, baseVersion=body["baseVersion"], data={**data, "content": content})
        return save(records, id=id, **body)

    monkeypatch.setattr(Records, "save", save_with_concurrent_edit)
    response = client.post(f"{url}/fix", json={"ids": ids})
    assert (response.status_code, response.json()["error"]["code"]) == (409, "VERSION_CONFLICT")
    latest = payload(client.get(url))["item"]["versions"][-1]
    assert latest["v"] == original["versions"][-1]["v"] + 1
    assert latest["content"]["title"] == "并发修改的通知"
    assert latest["content"]["docNo"] == INPUTS["docNo"]


def core_submit(client, body):
    # 通用 POST /api/v1/reviews 已拒绝公文（须经核查后走公文送审接口）；这里直接走数据底座造出定稿状态。
    platform = client.app.state.platform
    return platform.data.submit_review(platform.directory.user("sampleadmin"), body)


def test_finalized_draft_can_be_checked_but_not_fixed(document):
    client, _ = document
    url, original = create(client)
    review = core_submit(client, {
        "appId": "document", "recordId": original["id"], "version": 1, "assignee": "samplereviewer",
    })["id"]
    login(client, "samplereviewer")
    response = client.post(f"/api/v1/reviews/{review}/decisions", json={"version": 1, "decision": "confirm"})
    assert response.status_code == 200, response.text
    login(client, "sampleadmin")
    assert payload(client.post(f"{url}/check"))["issues"]
    result = client.post(f"{url}/fix", json={"ids": ["不存在"]})
    assert (result.status_code, result.json()["error"]["code"]) == (409, "LOCKED")
    assert payload(client.get(url))["item"]["versions"] == original["versions"]


def test_approval_between_check_and_save_blocks_revision(document, monkeypatch):
    client, _ = document
    url, original = create(client)
    review = core_submit(client, {
        "appId": "document", "recordId": original["id"], "version": 1, "assignee": "samplereviewer",
    })
    ids = [issue["id"] for issue in payload(client.post(f"{url}/check"))["issues"] if "fix" in issue]
    assert ids
    platform = client.app.state.platform
    reviewer = platform.directory.user("samplereviewer")
    save = Records.save

    def finalize_before_save(records, *, id=None, **body):
        platform.data.decide_review(reviewer, review["id"], {"version": 1, "decision": "confirm"})
        return save(records, id=id, **body)

    monkeypatch.setattr(Records, "save", finalize_before_save)
    response = client.post(f"{url}/fix", json={"ids": ids})
    assert (response.status_code, response.json()["error"]["code"]) == (409, "LOCKED")
    current = payload(client.get(url))["item"]
    assert current["status"] == "已定稿"
    assert current["versions"] == original["versions"]

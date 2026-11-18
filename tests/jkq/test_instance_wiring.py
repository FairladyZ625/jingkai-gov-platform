"""经 jkq.app.create_app 起实例，验证会话、长任务、审签模块已接入入口。"""

import json
import os
import secrets
import shutil
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="经开区集成测试需要 requirements-dev.txt")

from fastapi.testclient import TestClient

from haiknow_core.passwords import hash_password

from jkq.app import create_app


ROOT = Path(__file__).resolve().parents[2]
CONVERSATIONS = "/api/v1/conversations"
REVIEWS = "/api/v1/reviews"
JOBS = "/api/v1/jobs"
SKILLS = "/api/v1/skills"
PASSWORD = secrets.token_urlsafe(12)  # 每次运行随机，避免口令字面量入库
PANEL = {"app": "policy", "route": "detail", "params": {"id": "PI-03"}}


@pytest.fixture
def client(request, monkeypatch, tmp_path, cheap_password_hash):
    for name in tuple(os.environ):
        if name.startswith(("HAIKNOW_MODEL_", "HAIKNOW_PROVIDER_")):
            monkeypatch.delenv(name)
    config = tmp_path / "config"
    config.mkdir()
    (config / "projects.yaml").write_text(json.dumps({"companies": [{
        "id": "jingkai", "name": "北京经济技术开发区",
        "projects": [{"id": "jkq", "name": "经开区共享智能体工作站"}],
    }]}), encoding="utf-8")
    users = [("sampleoperator", ["sampleoperator"]), ("samplereviewer", ["samplereviewer"]),
             ("sampleobserver", ["sampleobserver"]), ("skillowner", ["member"]),
             ("skilleditor", ["member"]), ("skillreviewer", ["leader"]), ("skilladmin", ["admin"])]
    (config / "users.yaml").write_text(json.dumps({"users": [
        dict(id=uid, name=uid, position=uid, roles=roles, projects=["jkq"]) for uid, roles in users
    ]}), encoding="utf-8")
    apps = tmp_path / "apps"
    shutil.copytree(ROOT / "tests/fixtures/platform-app", apps / "sample-app")
    for name in getattr(request, "param", ()):
        shutil.copytree(ROOT / "apps" / name, apps / name)
    monkeypatch.delenv("HAIKNOW_ROOT", raising=False)
    monkeypatch.delenv("JKQ_WEB_DIR", raising=False)
    monkeypatch.setenv("HAIKNOW_SECRET", "jkq-test-session-signing")
    monkeypatch.delenv("HAIKNOW_DEMO_LOGIN", raising=False)
    monkeypatch.delenv("JKQ_DEMO_MODE", raising=False)
    shutil.copyfile(ROOT / "config/roles.yaml", config / "roles.yaml")
    monkeypatch.setenv("HAIKNOW_CONFIG_DIR", str(config))
    monkeypatch.setenv("HAIKNOW_APPS_DIR", str(apps))
    monkeypatch.setenv("HAIKNOW_DATA_DIR", str(tmp_path / "data"))
    app = create_app()
    store = app.state.platform.store
    with store._lock, store._db as db:
        store.begin_write()
        for uid, roles in users:
            # 经开区关闭卫华免密演示登录，测试账号走真实口令登录。
            db.execute(
                "insert into users (id,username,name,password_hash,status,last_login,failed_logins,"
                "locked_until,demo,all_projects,session_gen) values (?,?,?,?,'active',null,0,0,0,0,0)",
                (uid, uid, uid, hash_password(PASSWORD)),
            )
            db.executemany("insert or ignore into roles values (?,?,1)", [(role, role) for role in roles])
            db.executemany("insert into user_roles values (?,?)", [(uid, role) for role in roles])
            db.execute("insert into project_members values (?,?)", ("jkq", uid))
    with TestClient(app) as client:
        yield client


def login(client, uid):
    response = client.post("/api/v1/auth/login", json={"username": uid, "password": PASSWORD})
    assert response.status_code == 200, response.text


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert error["message"] and isinstance(error["details"], dict)


def submit_review(client):
    login(client, "sampleoperator")
    record = client.post("/api/v1/apps/sample-app/records", json={
        "project": "jkq", "type": "report", "data": {"title": "样例记录"},
    })
    assert record.status_code == 201, record.text
    review = client.post(REVIEWS, json={
        "appId": "sample-app", "recordId": record.json()["id"], "version": 1,
        "assignee": "samplereviewer",
    })
    assert review.status_code == 201, review.text
    return review.json()


def test_conversation_store_is_shared_on_app_state(client):
    login(client, "sampleoperator")
    created = client.post(CONVERSATIONS, json={"title": "政策咨询"})
    assert created.status_code == 200, created.text
    cid = created.json()["item"]["id"]
    client.app.state.conversations.append_message("sampleoperator", cid, role="user", content="问题")
    assert [m["content"] for m in client.get(f"{CONVERSATIONS}/{cid}").json()["messages"]] == ["问题"]


def test_conversation_routes_succeed_through_instance(client):
    login(client, "sampleoperator")
    cid = client.post(CONVERSATIONS, json={"title": "政策咨询"}).json()["item"]["id"]
    patched = client.patch(f"{CONVERSATIONS}/{cid}", json={"panel": PANEL})
    assert patched.status_code == 200 and patched.json()["item"]["panel"] == PANEL
    assert client.get(f"{CONVERSATIONS}/{cid}").json()["item"]["panel"] == PANEL
    assert [item["id"] for item in client.get(CONVERSATIONS).json()["items"]] == [cid]
    assert client.delete(f"{CONVERSATIONS}/{cid}").status_code == 204
    assert client.get(CONVERSATIONS).json() == {"items": [], "total": 0}
    restored = client.post(f"{CONVERSATIONS}/{cid}/restore")
    assert restored.status_code == 200 and restored.json()["item"]["id"] == cid
    assert client.get(CONVERSATIONS).json()["total"] == 1


def test_conversation_routes_return_errors_through_instance(client):
    assert_error(client.get(CONVERSATIONS), 401, "UNAUTHENTICATED")
    login(client, "sampleoperator")
    cid = client.post(CONVERSATIONS, json={}).json()["item"]["id"]
    assert_error(client.post(CONVERSATIONS, json={"title": 1}), 422, "CHECK_FAILED")
    assert_error(client.patch(f"{CONVERSATIONS}/{cid}", json={"panel": {}}), 422, "CHECK_FAILED")
    for method in ("get", "delete"):
        assert_error(client.request(method, f"{CONVERSATIONS}/missing"), 404, "NOT_FOUND")
    assert_error(client.post(f"{CONVERSATIONS}/missing/restore"), 404, "NOT_FOUND")
    login(client, "samplereviewer")
    assert_error(client.get(f"{CONVERSATIONS}/{cid}"), 404, "NOT_FOUND")


def test_job_route_uses_jingkai_view_and_sdk_falls_back(client):
    client.app.state.platform.jobs.operations[("sample-app", "transcribe")] = ("1", None)
    login(client, "sampleoperator")
    response = client.post(JOBS, json={
        "appId": "sample-app", "project": "jkq", "operation": "transcribe",
        "input": {"ref": "audio-1"}, "idempotencyKey": "instance-wiring",
    })
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    job = client.get(f"{JOBS}/{job_id}").json()["job"]
    assert {key: job[key] for key in ("id", "kind", "ref", "status")} == {
        "id": job_id, "kind": "transcribe", "ref": "audio-1", "status": "running",
    }
    sdk = client.get(f"{JOBS}/{job_id}?app=sample-app")
    assert sdk.status_code == 200, sdk.text
    assert "job" not in sdk.json() and sdk.json()["id"] == job_id
    assert_error(client.get(f"{JOBS}/missing"), 404, "NOT_FOUND")


def test_review_routes_use_jingkai_contract(client):
    review = submit_review(client)
    login(client, "samplereviewer")
    pending = client.get(REVIEWS)
    assert pending.status_code == 200, pending.text
    assert [item["id"] for item in pending.json()["items"]] == [review["id"]]
    path = f"{REVIEWS}/{review['id']}/decisions"
    decided = client.post(path, json={"decision": "approve", "version": 1})
    assert decided.status_code == 200, decided.text
    assert decided.json()["item"]["decision"]["decision"] == "approve"
    assert client.get(REVIEWS).json() == {"items": []}
    assert_error(client.post(path, json={"decision": "approve", "version": 1}), 409, "ALREADY_DECIDED")
    missing = client.post(f"{REVIEWS}/missing/decisions", json={"decision": "approve", "version": 1})
    assert_error(missing, 404, "NOT_FOUND")
    login(client, "sampleobserver")
    assert_error(client.post(path, json={"decision": "reject", "version": 1}), 403, "FORBIDDEN")


def test_review_sdk_requests_fall_back_to_core(client):
    review = submit_review(client)
    submitted = client.get(f"{REVIEWS}?app=sample-app&mine=submitted")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["items"][0]["review"] == "platform"
    login(client, "samplereviewer")
    path = f"{REVIEWS}/{review['id']}/decisions"
    confirmed = client.post(path, json={"decision": "confirm", "version": 1})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed" and "item" not in confirmed.json()


def test_skill_crud_and_publication_use_default_instance_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"get", "post"} <= paths[SKILLS].keys()
    assert {"get", "patch", "delete"} <= paths[SKILLS + "/{sid}"].keys()
    for operation in ("publish", "share", "review", "rate", "fork", "restore", "restore-deleted"):
        assert "post" in paths[f"{SKILLS}/{{sid}}/{operation}"]
    assert_error(client.get(SKILLS), 401, "UNAUTHENTICATED")
    login(client, "skillowner")
    listing = client.get(SKILLS)
    assert listing.status_code == 200 and listing.json()["items"] == []
    assert client.get(f"{SKILLS}/meta/options").status_code == 200
    created = client.post(SKILLS, json={"name": "实例技能"})
    assert created.status_code == 200, created.text
    skill = created.json()["item"]
    path = f"{SKILLS}/{skill['id']}"
    assert client.patch(path, json={"summary": "更新说明"}).status_code == 200
    assert client.get(path).json()["item"]["summary"] == "更新说明"
    assert client.delete(path).json()["ok"]
    assert_error(client.get(path), 404, "NOT_FOUND")
    assert client.post(f"{path}/restore-deleted").json()["ok"]

    shared = client.post(f"{path}/share", json={"scope": "people", "people": ["skilleditor"], "perm": "use"})
    assert shared.status_code == 200 and shared.json()["review"] is None
    login(client, "skilleditor")
    assert_error(client.patch(path, json={"summary": "无权编辑"}), 403, "FORBIDDEN")
    assert client.post(f"{path}/fork").json()["item"]["forkOf"]["id"] == skill["id"]
    for vote, useful_rate in ((True, 100), (False, 0)):
        rated = client.post(f"{path}/rate", json={"useful": vote}).json()["item"]
        assert (rated["ratingN"], rated["usefulRate"]) == (1, useful_rate)
    listed, = [item for item in client.get(SKILLS).json()["items"] if item["id"] == skill["id"]]
    assert (listed["ratingN"], listed["usefulRate"]) == (1, 0)

    login(client, "skillowner")
    first = client.post(f"{path}/publish", json={"share": {"scope": "zone", "perm": "edit"}})
    assert first.status_code == 200, first.text
    review = first.json()["review"]
    body = {"reviewId": review["id"], "version": review["version"]}
    assert_error(client.post(f"{path}/review", json={"decision": "approve", **body}), 409, "SELF_REVIEW")
    login(client, "skilleditor")
    assert skill["id"] not in {item["id"] for item in client.get(SKILLS).json()["items"]}
    assert_error(client.post(f"{path}/review", json={"decision": "approve", **body}), 403, "FORBIDDEN")
    login(client, "skillreviewer")
    assert_error(client.post(f"{path}/review", json={"decision": "reject", "reason": " ", **body}),
                 400, "INVALID_REQUEST")
    rejected = client.post(f"{path}/review", json={"decision": "reject", "reason": "需补充说明", **body})
    assert rejected.status_code == 200 and rejected.json()["item"]["status"] == "rejected"
    login(client, "skillowner")
    second = client.post(f"{path}/publish", json={"share": {"scope": "zone", "perm": "edit"}}).json()["review"]
    login(client, "skilladmin")
    assert_error(client.post(f"{path}/review", json={"decision": "approve", **body}), 409, "STALE_VERSION")
    approved = client.post(f"{REVIEWS}/{second['id']}/decisions", json={
        "decision": "approve", "version": second["version"],
    })
    assert approved.status_code == 200 and approved.json()["item"]["decision"]["decision"] == "approve"
    login(client, "skilleditor")
    assert client.get(path).json()["item"]["canEdit"]
    assert client.patch(path, json={"summary": "获批后协作编辑"}).json()["item"]["status"] == "in_review"


@pytest.mark.parametrize("client", [("document",)], indirect=True)
def test_document_instance_guards_generic_review_entry(client):
    """#41：实例启动即挂载公文送审、导出，通用送审入口拒绝公文，其他应用不受影响。"""
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/apps/document/drafts/{identity}/submit" in paths
    assert "/api/apps/document/drafts/{identity}/export" in paths
    login(client, "sampleoperator")
    blocked = client.post(REVIEWS, json={"appId": "document", "recordId": "any", "version": 1})
    assert_error(blocked, 405, "METHOD_NOT_ALLOWED")
    review = submit_review(client)
    assert review["status"] == "pending"

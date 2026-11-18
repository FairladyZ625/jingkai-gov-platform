"""#24 的 HTTP 契约、重启持久化与下游版本/检索入口。"""
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")  # 轻量 CI 只安装 pytest，core job 安装完整后端。
from fastapi import FastAPI
from fastapi.testclient import TestClient
from haiknow_core.store import Store
from jkq.conversations.store import ConversationStore
from jkq.kb import install
from jkq.kb.docs import RETENTION
from jkq.kb.seed import ROOT

BASE = "/api/v1/kb"
INTERNAL = ["policy", "template", "minutes", "rules", "enterprise"]


@pytest.fixture
def api(tmp_path):
    user = SimpleNamespace(id="sample", roles=["member"])
    grants = {"view", "operate"}
    stores = []

    def boot():
        store = Store(tmp_path)
        stores.append(store)
        platform = SimpleNamespace(store=store, rbac=SimpleNamespace(actions=lambda u, app: grants))
        app = FastAPI()
        install(app, platform, lambda: user)
        return TestClient(app, base_url="http://testserver" + BASE + "/"), platform.kb

    client, service = boot()
    yield client, service, user, grants, boot
    for store in stores:
        store._db.close()


@pytest.mark.parametrize("role,expected", [(r, INTERNAL) for r in ("admin", "leader", "member")] +
                         [("partner", ["policy"])])
def test_spaces_and_libraries(api, role, expected):
    client, _, user, *_ = api
    user.roles = [role]
    items = client.get("spaces").json()["items"]
    assert [s["id"] for s in items] == expected
    assert client.get("libraries").json()["items"] == [
        dict(id=s["id"], name=s["name"], icon=s["icon"], files=s["count"]) for s in items]
    assert client.get("docs").json()["total"] == sum(s["count"] for s in items)
    if role != "partner":
        assert items[-1]["sensitive"]


def test_version_and_alias(api):
    client, service, user, *_ = api
    old = client.get("docs", params={"space": "template", "limit": 1}).json()["hits"][0]
    path = "docs/" + old["id"]
    original = client.get(path).json()["item"]
    assert original["version"] == 1 and original["versions"] == [dict(id=old["citationId"], version=1, date=old["source"]["date"])]
    assert original["chunkList"][0]["end"] == len(original["text"])
    edits = dict(title="样例标题", tags=["格式"], expire="2028-01-01", space="minutes")
    edited = client.patch(path, json=edits).json()["item"]
    assert all(edited[k] == v for k, v in edits.items())
    service.replace_text(user, old["id"], "新版原文")
    pinned = client.get("files/" + old["citationId"]).json()["item"]
    assert pinned["state"] == "来源已修订" and pinned["text"] == original["text"]
    current = client.get(path).json()["item"]
    assert (current["text"], current["version"], [v["version"] for v in current["versions"]]) == ("新版原文", 2, [1, 2])
    file = client.get("files/" + old["id"], params={"version": 1}).json()["item"]
    assert file == dict(id=old["id"], name="样例标题", no=original["source"]["docNo"],
                        text=original["text"], state="来源已修订", url=original["source"]["url"])
    assert client.get(path + "?version=3").status_code == 404


@pytest.mark.parametrize("method,path", [("get", "docs/x"), ("patch", "docs/x"), ("delete", "docs/x"),
                                         ("post", "docs/x/restore"), ("get", "files/x")])
def test_missing(api, method, path):
    response = api[0].request(method, path, json={} if method == "patch" else None)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "NOT_FOUND")


def test_permissions(api):
    client, _, user, grants, _ = api
    restricted = client.get("docs?space=enterprise").json()["hits"][0]["id"]
    user.roles = ["partner"]
    assert client.get("docs?space=enterprise").json()["hits"] == []
    for prefix in ("files/", "docs/"):
        assert client.get(prefix + restricted).status_code == 404
    public = client.get("docs").json()["hits"][0]["id"]
    grants.remove("operate")
    for method, path in [("patch", public), ("delete", public), ("post", public + "/restore")]:
        response = client.request(method, "docs/" + path, json={} if method == "patch" else None)
        assert response.status_code == 403
        assert response.json()["error"] == dict(code="FORBIDDEN", message="没有知识库操作权限",
                                                details=dict(app="kb", need="operate"))
    grants.clear()
    assert client.get("spaces").status_code == 403


def test_restore_deadline_and_candidates(api, monkeypatch):
    client, service, user, _, boot = api
    doc = client.get("docs?space=rules&limit=1").json()["hits"][0]
    path = "docs/" + doc["id"]
    now = 2000000000
    monkeypatch.setattr("jkq.kb.docs.time.time", lambda: now)
    assert client.delete(path).json()["ok"]
    client, service = boot()
    def hits():
        return [d["id"] for d in service.candidates(user) if doc["title"] in d["title"]]
    assert doc["id"] not in hits()
    assert client.get(path).status_code == 404
    now += RETENTION - 1
    assert client.post(path + "/restore").json()["ok"]
    assert doc["id"] in hits()
    assert client.delete(path).status_code == 200
    now += RETENTION
    response = client.post(path + "/restore")
    assert (response.status_code, response.json()["error"]["code"]) == (404, "NOT_FOUND")
    assert doc["id"] not in hits()


def test_seed_counts_across_two_restarts(api):
    client, _, _, _, boot = api
    seed = ROOT / "data/seed"
    read = lambda p: json.loads(p.read_text())
    kb = seed / "real-kb.json"
    expected = len(read(kb)["docs"] if kb.exists() else read(ROOT / "data/public/kb_docs.json"))
    policies = seed / "real-policies.json"
    if policies.exists():
        expected += len(read(policies)["policyDocs"])
    else:
        script = (ROOT / "prototype/v4/data/real-policies.js").read_text()
        expected += len(json.JSONDecoder().raw_decode(script.split("window.JK_REAL = ")[1])[0]["policyDocs"])
    if (seed / "kb-examples.json").exists():
        expected += len(read(seed / "kb-examples.json"))
    expected += sum(len(read(p)) for p in (seed / "real").glob("*.json"))
    for _ in range(2):
        assert client.get("docs?limit=1").json()["total"] == expected
        client, _ = boot()
    assert client.get("docs?limit=1").json()["total"] == expected


def message(service, owner="sample"):
    conversations = ConversationStore(service.store)
    cid = conversations.create(owner)["id"]
    return conversations, cid, conversations.append_message(owner, cid, role="assistant", content="答复")["id"]


def test_saved_cards_reopen_after_restart(api):
    client, service, user, _, boot = api
    doc = client.get("docs?space=template&limit=1").json()["hits"][0]
    version_path = "docs/" + doc["citationId"]
    original = client.get(version_path).json()["item"]
    path = f"messages/{message(service)[2]}/citations"
    refs = {"citations": [dict(fileId=doc["id"], snippet=original["text"][:20])]}
    assert client.put(path, json=refs).json() == {"ok": True}
    service.replace_text(user, doc["id"], "第二版")
    client, _ = boot()
    expected = dict(fileId=doc["citationId"], name=doc["title"], snippet=original["text"][:20],
                    version=1, text=original["text"], state="来源已修订", source=doc["source"])
    assert client.get(path).json() == {"citations": [expected]}
    versions = client.get(version_path).json()["item"]["versions"]
    assert [client.get("docs/" + v["id"]).json()["item"]["text"] for v in versions] == [expected["text"], "第二版"]
    assert client.put(path, json={"citations": [dict(fileId="missing", snippet="")]}).status_code == 404
    assert client.get(path).json()["citations"] == [expected]
    user.roles = ["partner"]
    assert client.get(path).json() == {"citations": []}


def test_citations_follow_message_lifecycle(api):
    client, service, user, *_ = api
    doc = client.get("docs?space=policy&limit=1").json()["hits"][0]
    refs = {"citations": [dict(fileId=doc["id"], snippet="摘录")]}
    conversations, cid, mid = message(service)
    _, _, foreign = message(service, owner="another")
    path = f"messages/{mid}/citations"

    def not_found(method, target):
        response = client.request(method, target, json=refs if method == "put" else None)
        return (response.status_code, response.json()["error"]["code"]) == (404, "NOT_FOUND")

    for target in ("messages/M-missing/citations", f"messages/{foreign}/citations"):
        assert not_found("put", target) and not_found("get", target)
    assert client.put(path, json=refs).json() == {"ok": True}
    user.id = "another"
    assert not_found("get", path) and not_found("put", path)
    user.id = "sample"
    assert [c["fileId"] for c in client.get(path).json()["citations"]] == [doc["citationId"]]
    conversations.set_deleted("sample", cid, deleted=True)
    assert not_found("get", path) and not_found("put", path)
    conversations.set_deleted("sample", cid, deleted=False)
    assert [c["fileId"] for c in client.get(path).json()["citations"]] == [doc["citationId"]]


def test_instance_registers_kb_routes(monkeypatch, tmp_path, cheap_password_hash):
    import os
    from jkq.app import create_app

    for name in tuple(os.environ):
        if name.startswith(("HAIKNOW_", "JKQ_WEB_DIR")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HAIKNOW_SECRET", "jkq-test-session-signing")
    monkeypatch.setenv("HAIKNOW_DEMO_LOGIN", "0")
    monkeypatch.setenv("HAIKNOW_DATA_DIR", str(tmp_path / "database"))
    with TestClient(create_app()) as client:
        response = client.get(BASE + "/spaces")
        assert (response.status_code, response.json()["error"]["code"]) == (401, "UNAUTHENTICATED")
        body = {"username": "test-admin", "password": "demo-password", "name": "测试管理员"}
        assert client.post("/api/auth/bootstrap", json=body).status_code == 200
        assert [s["id"] for s in client.get(BASE + "/spaces").json()["items"]] == INTERNAL
        assert [s["id"] for s in client.get(BASE + "/libraries").json()["items"]] == INTERNAL
        doc = client.get(BASE + "/docs?space=policy&limit=1").json()["hits"][0]
        assert client.get(BASE + "/files/" + doc["id"]).json()["item"]["name"] == doc["title"]
        response = client.get(BASE + "/files/missing")
        assert (response.status_code, response.json()["error"]["code"]) == (404, "NOT_FOUND")


@pytest.mark.parametrize("method,path,body", [
    ("get", "docs?limit=0", None), ("get", "docs?space=bad", None),
    ("get", "docs?offset=-1", None), ("patch", "docs/x", {"space": "bad"}),
    ("patch", "docs/x", {"title": None}), ("patch", "docs/x", ["bad"]),
])
def test_validation_envelope(api, method, path, body):
    response = api[0].request(method, path, json=body)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "CHECK_FAILED" and error["message"] and error["details"]["fields"]


def test_repair_existing_seed_preserves_edits_and_deletion(api):
    client, service, user, _, boot = api
    expired = client.get("docs?space=rules&status=已失效&limit=100").json()["hits"]
    rule = next(d for d in expired if d["source"].get("statusNote") == "已失效（官网标注）")
    policy_id = "rd-4913172"
    path = "docs/" + policy_id
    original = client.get(path).json()["item"]
    excerpt = original["excerpts"][0]
    assert excerpt["original"] and excerpt["original"] in original["text"]
    assert excerpt["source"]["url"] == original["source"]["url"]
    client.patch(path, json={"title": "保留用户标题"})
    client.delete("docs/" + rule["id"])
    with service.store._db as db:
        db.execute("""update jkq_kb_docs set doc=json_remove(json_set(doc,'$.status',?),'$.source.statusNote')
                   where id=?""", ("已失效（官网标注）", rule["id"]))
        db.execute("""update jkq_kb_docs set doc=json_remove(json_set(doc,'$.text',''),'$.excerpts')
                   where id=?""", (policy_id,))
    for _ in range(2):
        client, service = boot()
        assert client.get("docs/" + rule["id"]).status_code == 404
        restored = client.get(path).json()["item"]
        assert restored["title"] == "保留用户标题"
        assert restored["excerpts"] == original["excerpts"] and restored["text"] == original["text"]
        assert any(d["id"] == policy_id and excerpt["original"] in d["text"] for d in service.candidates(user))
    assert client.post("docs/" + rule["id"] + "/restore").status_code == 200
    detail = client.get("docs/" + rule["id"]).json()["item"]
    assert (detail["status"], detail["source"]["statusNote"]) == ("已失效", "已失效（官网标注）")

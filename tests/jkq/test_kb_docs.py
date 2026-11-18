"""#24 的 HTTP 契约、重启持久化与下游版本/检索入口。"""
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")  # 轻量 CI 只安装 pytest，core job 安装完整后端。
from fastapi import FastAPI
from fastapi.testclient import TestClient
from haiknow_core.store import Store
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
    assert original["version"] == 1 and original["versions"] == [1]
    assert original["chunkList"][0]["end"] == len(original["text"])
    edits = dict(title="样例标题", tags=["格式"], expire="2028-01-01", space="minutes")
    edited = client.patch(path, json=edits).json()["item"]
    assert all(edited[k] == v for k, v in edits.items())
    service.replace_text(user, old["id"], "新版原文")
    pinned = client.get("files/" + old["citationId"]).json()["item"]
    assert pinned["state"] == "来源已修订" and pinned["text"] == original["text"]
    current = client.get(path).json()["item"]
    assert (current["text"], current["version"], current["versions"]) == ("新版原文", 2, [1, 2])
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

"""#172/#215：只接收 pytest 的临时实例；不接受站点地址、已有数据库或账号口令。"""
import json
import os
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from haiknow_sdk.ai import AI

ROOT = Path(__file__).resolve().parents[2]
MEMBER, LEADER = "sampleoperator", "samplereviewer"
SOURCE = "本次为虚拟材料核验，仅受理演示清单内的材料。"


class SampleSource:
    """只读原文桩；不存在的文件或版本不能命中。"""
    def detail(self, user, identity, version=None):
        assert identity == "fixture-215" and version in (None, 1)
        return {"id": identity, "space": "policy", "title": "【隔离演示】材料说明",
                "version": 1, "status": "现行有效", "text": SOURCE}


@pytest.fixture
def review_site(isolated_platform, jkq_accounts, monkeypatch):
    config, _ = isolated_platform
    # 不继承宿主实例的路径、模型配置或演示开关；只使用下方临时目录。
    for key in tuple(os.environ):
        if key.startswith(("HAIKNOW_", "JKQ_")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("HAIKNOW_NO_AUTOAPP", "1")
    monkeypatch.setenv("HAIKNOW_CONFIG_DIR", str(config))
    monkeypatch.setenv("HAIKNOW_KB_SEED", "0")
    (config / "projects.yaml").write_bytes((ROOT / "config/projects.yaml").read_bytes())
    path = config / "users.yaml"
    users = json.loads(path.read_text())
    for user in users["users"]:
        if user["id"] in (MEMBER, LEADER):
            user.update(projects=["jkq"], roles=["leader" if user["id"] == LEADER else "member"])
    path.write_text(json.dumps(users))
    monkeypatch.setenv("HAIKNOW_SECRET", secrets.token_hex(32))
    monkeypatch.setenv("HAIKNOW_APPS_DIR", str(ROOT / "apps"))
    monkeypatch.setattr(AI, "chat", lambda *a, **kw: {"result": '{"issues":[]}'})
    create, sign_in = jkq_accounts
    with TemporaryDirectory(prefix="document-review-", dir=config.parent) as state:
        monkeypatch.setenv("HAIKNOW_DATA_DIR", state)
        with TestClient(create()) as client:
            client.app.state.platform.kb = SampleSource()
            yield client, lambda who: sign_in(client, who)


def ok(response):
    assert response.status_code == 200, (response.status_code, response.text)
    return response.json()


def inbox(client, box="review"):
    return ok(client.get("/api/v1/inbox", params={"box": box}))["items"]


def test_leader_cannot_review_own_document(review_site):
    client, login = review_site
    login(LEADER)
    assert inbox(client) == [] and inbox(client, "todo") == []
    draft = ok(client.post("/api/apps/document/drafts", json={"templateId": "T06", "inputs": {
        "orig": "【隔离演示】虚拟申请", "reason": "演练", "oldEnd": "2026-11-20",
        "newEnd": "2026-11-25", "to": "演示组：", "sign": "测试组", "date": "2026年11月18日"
    }}))["item"]
    path = "/api/apps/document/drafts/" + draft["id"]
    issues = ok(client.post(path + "/check"))["issues"]
    assert not any(i["level"] == "error" for i in issues)
    assert any(i["field"] == "docNo" and i["level"] == "warn" for i in issues)
    own = client.post(path + "/submit", json={"assignee": LEADER})
    assert (own.status_code, own.json()["error"]["code"]) == (409, "SELF_REVIEW")
    # 按原政策，无指定人且仅缺文号可以排队；即使有 approve，也不能决定自己的稿。
    unassigned = ok(client.post(path + "/submit", json={}))["review"]
    own = client.post(f"/api/v1/reviews/{unassigned['id']}/decisions",
                      json={"version": unassigned["version"], "decision": "approve"})
    assert (own.status_code, own.json()["error"]["code"]) == (409, "SELF_REVIEW")
    assert inbox(client) == [] and ok(client.get(path))["item"]["status"] == "审签中"
    assert ok(client.get("/api/v1/reviews"))["items"][0]["approver"] is False


@pytest.fixture
def pending_document(review_site):
    client, login = review_site
    login(MEMBER)
    draft = ok(client.post("/api/apps/document/drafts", json={
        "templateId": "T06", "inputs": {"orig": "【隔离演示】材料核验",
        "oldEnd": "2026-11-20", "newEnd": "2026-11-25", "reason": "演练延期"},
        "refs": [{"id": "fixture-215"}],
    }))["item"]
    path = "/api/apps/document/drafts/" + draft["id"]
    issues = ok(client.post(path + "/check"))["issues"]
    assert {"to", "sign", "date"} <= {i["field"] for i in issues if i["level"] == "error"}
    assert any(i["field"] == "docNo" and i["level"] == "warn" for i in issues)
    response = client.post(path + "/submit", json={"assignee": LEADER})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CHECK_FAILED"
    assert response.json()["error"]["message"] == "请先处理核查发现的问题"
    assert ok(client.get(path))["item"]["status"] == "草稿"
    fields = dict(draft["versions"][-1]["content"], docNo="演示〔2026〕1号",
                  to="演示材料组：", sign="虚拟演示组", date="2026年11月18日")
    ok(client.put(path, json={"content": fields}))
    denied = client.post(path + "/submit", json={"assignee": MEMBER})
    assert (denied.status_code, denied.json()["error"]["code"]) == (409, "SELF_REVIEW")
    ok(client.post(path + "/comments", json={"para": 0, "text": "请核对虚拟材料说明。"}))
    submission = ok(client.post(path + "/submit", json={"assignee": LEADER}))
    assert submission["item"]["status"] == "审签中"
    assert submission["item"]["comments"][0]["text"] == "请核对虚拟材料说明。"
    return path, submission["review"]


def test_review_cycle(review_site, pending_document):
    client, login = review_site
    path, first = pending_document
    reason = "请在首段注明本次演练的材料范围。"

    def decide(review, choice, note):
        return client.post("/api/v1/reviews/" + review["id"] + "/decisions", json={
            "version": review["version"], "decision": choice, "reason": note})

    assert decide(first, "approve", "无权通过").status_code == 403
    login(LEADER)
    pending, = inbox(client)
    assert pending["id"] == first["id"] and pending["ref"]["recordId"] == first["ref"]
    assert "【隔离演示】" in pending["title"]
    listed, = ok(client.get("/api/v1/reviews"))["items"]
    assert listed["approver"] is True
    assert (listed["id"], listed["title"], listed["version"]) == (first["id"], pending["title"], first["version"])
    draft = ok(client.get(path))["item"]
    assert draft["refs"][0]["title"] == "【隔离演示】材料说明"
    assert any(SOURCE in p for p in draft["versions"][-1]["content"]["paragraphs"])
    assert draft["comments"][0]["text"] == "请核对虚拟材料说明。"
    note = "首段尚未列出演示清单。"
    ok(client.post(path + "/comments", json={"para": 0, "text": note}))
    assert ok(decide(first, "reject", reason))["item"]["decision"]["comment"] == reason
    assert inbox(client) == []
    login(MEMBER)
    returned = ok(client.get(path))["item"]
    assert returned["status"] == "已退回" and returned["comments"][-1]["text"] == note
    assert returned["returnReason"] == reason
    fields = returned["versions"][-1]["content"]
    fields["paragraphs"][0] += SOURCE
    ok(client.put(path, json={"content": fields, "note": "按批注补充演示范围"}))
    second = ok(client.post(path + "/submit", json={"assignee": LEADER}))["review"]
    assert second["id"] != first["id"] and second["version"] > first["version"]
    login(LEADER)
    assert [r["id"] for r in inbox(client)] == [second["id"]]
    ok(decide(second, "approve", "同意定稿"))
    assert inbox(client) == []
    assert {r["id"] for r in inbox(client, "done")} == {first["id"], second["id"]}
    login(MEMBER)
    assert ok(client.get(path))["item"]["status"] == "已定稿"
    assert client.put(path, json={"content": fields}).status_code == 409
    audit = client.app.state.platform.store.audit_list("document")
    assert [(r["action"], r["user"], r["detail"].get("reviewId") or r["detail"]["id"])
            for r in reversed(audit) if r["action"].startswith("v1.review.")] == [
        ("v1.review.submit", MEMBER, first["id"]), ("v1.review.return", LEADER, first["id"]),
        ("v1.review.submit", MEMBER, second["id"]), ("v1.review.confirm", LEADER, second["id"]),
    ]

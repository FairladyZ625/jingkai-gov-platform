"""使用实例登录、权限与 SQLite 审计验证操作员 HTTP 协议。"""

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from jkq.app import create_app

BASE = "/api/v1/operator"
LOGIN = "/api/v1/auth/login"
VISIT = "给书香里加一条走访记录"
AT = "2026-11-18T14:00:00+08:00"
ACCOUNTS = {"admin": "admin", "member": "wangmin", "partner": "hejun"}


@pytest.fixture
def instance(tmp_path, monkeypatch, reuse_loaded_routers, cheap_password_hash):
    monkeypatch.setenv("HAIKNOW_DATA_DIR", str(tmp_path / "operator-db"))
    monkeypatch.setenv("HAIKNOW_SECRET", "test-signing-value")
    monkeypatch.setenv("JKQ_DEMO_MODE", "1")
    monkeypatch.setenv("HAIKNOW_KB_SEED", "0")
    for role in ("admin", "leader", "member", "partner"):
        monkeypatch.setenv(f"JKQ_DEMO_{role.upper()}_PASSWORD", f"test-{role}")
    app = create_app()
    monkeypatch.setattr(app.state.platform, "model", SimpleNamespace(configured=False))
    return app


def login(instance, role):
    client = TestClient(instance)
    result = client.post(LOGIN, json={"username": ACCOUNTS[role], "password": f"test-{role}"})
    assert result.is_success, result.text
    return client


def plan(client, text=VISIT, **body):
    response = client.post(f"{BASE}/plan", json={"text": text, "context": {"page": "home"}, **body})
    assert response.status_code == 200, response.text
    return response.json()


def report(client, plan_id, statuses, *, confirmed=()):
    return client.post(f"{BASE}/runs", json={
        "planId": plan_id, "confirmed": list(confirmed),
        "steps": [{"id": sid, "status": status, "at": AT} for sid, status in statuses.items()],
    })


def codes(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


def operator_audit(instance):
    return [item for item in instance.state.platform.store.audit_list()
            if item["action"].startswith("operator.")]


def test_routes_are_wired_into_instance_factory(instance):
    # 实例工厂直接挂好操作员路由：未登录得到 401 而不是 404。
    client = TestClient(instance)
    codes(client.get(f"{BASE}/intents"), 401, "UNAUTHENTICATED")
    codes(client.post(f"{BASE}/plan", json={"text": VISIT}), 401, "UNAUTHENTICATED")
    codes(client.post(f"{BASE}/runs/run-x/stop"), 401, "UNAUTHENTICATED")


def test_catalog_and_forbidden_plan_under_real_partner_session(instance):
    codes(TestClient(instance).get(f"{BASE}/intents"), 401, "UNAUTHENTICATED")
    partner = login(instance, "partner")
    items = partner.get(f"{BASE}/intents").json()["items"]
    assert {item["app"] for item in items} == {"enterprise", "policy"}
    assert all(set(item) == {"id", "app", "label", "example", "home"} for item in items)
    assert "enterprise.visit" not in {item["id"] for item in items}

    forbidden = plan(partner, "整理一下文化企业座谈会的纪要")
    assert (forbidden["mode"], forbidden["app"], forbidden["need"]) == ("forbidden", "meeting", "view")
    assert forbidden["steps"] == [] and "planId" not in forbidden
    assert plan(partner)["need"] == "operate"
    assert plan(login(instance, "member"), "审签通过")["need"] == "approve"


def test_visit_example_and_confirmed_receipt(instance):
    client = login(instance, "member")
    result = plan(client)
    assert (result["intent"], result["confidence"], result["mode"], result["slots"]) == (
        "enterprise.visit", 0.92, "execute", {"ent": "E001"},
    )
    assert result["steps"] == [
        {"id": "s1", "label": "打开企业管理维护", "action": "open", "target": "enterprise", "write": False},
        {"id": "s2", "label": "搜索并选择：书香里文化", "action": "type", "target": "ent-search",
         "value": "书香里", "write": False},
        {"id": "s3", "label": "填入走访记录", "action": "type", "target": "vs-notes", "write": False},
        {"id": "s4", "label": "AI 对照台账提取更新建议", "action": "call",
         "tool": "enterprise.propose_update", "write": False},
        {"id": "s5", "label": "写入台账（需要你确认）", "action": "confirm",
         "tool": "enterprise.proposal_decision", "write": True},
    ]
    identity = result["planId"]
    statuses = {step["id"]: "done" for step in result["steps"]}
    denied = report(client, identity, statuses)
    codes(denied, 409, "WRITE_CONFIRMATION_REQUIRED")
    assert denied.json()["error"]["details"] == {"stepId": "s5"}
    assert operator_audit(instance)[0]["detail"] == {
        "via": "operator", "runId": identity, "outcome": "WRITE_CONFIRMATION_REQUIRED", "stepId": "s5",
    }
    # 整批拒绝，前四步也没有形成已完成回执。
    started = report(client, identity, {})
    assert [step["status"] for step in started.json()["steps"]] == ["pending"] * 5
    accepted = report(client, identity, statuses, confirmed=["s5"])
    assert accepted.status_code == 200
    run = accepted.json()
    assert (run["id"], run["planId"], run["status"]) == (identity, identity, "done")
    assert [step["status"] for step in run["steps"]] == ["done"] * 5
    audit = operator_audit(instance)
    assert audit[0]["detail"] == {
        "via": "operator", "runId": identity, "status": "done", "steps": run["steps"], "confirmed": ["s5"],
    }
    assert report(client, identity, statuses, confirmed=["s5"]).json() == run
    assert operator_audit(instance) == audit


@pytest.mark.parametrize(("example", "text", "confidence", "mode"), [
    ("甲乙丙丁戊己庚辛壬癸春夏秋冬梅", "甲乙丙丁戊己庚辛壬癸春夏秋冬梅兰竹菊松", 0.75, "execute"),
    ("甲乙丙丁戊己庚辛", "甲乙丙丁春夏秋冬梅", 0.4, "confirm"),
    ("甲乙丙丁戊己庚辛", "甲乙丙春夏秋冬梅", 0.32, "answer"),
])
def test_confidence_boundaries_are_visible_in_http(instance, example, text, confidence, mode):
    platform = instance.state.platform
    platform.apps["policy"].manifest["intents"] = [
        {"id": "policy.example", "examples": [example], "plan": ["打开示例"]},
    ]
    result = plan(login(instance, "member"), text)
    assert (result["confidence"], result["mode"]) == (confidence, mode)
    assert bool(result["steps"]) is (mode != "answer")


def test_model_fills_only_missing_grounded_text_slots(instance, monkeypatch):
    client = login(instance, "member")
    calls = []

    def chat(app, messages, **options):
        calls.append((app, messages, options))
        return '{"notes":"现场仅记录诉求","ent":"伪造企业","write":false}'

    monkeypatch.setattr(instance.state.platform, "model", SimpleNamespace(configured=True, chat=chat))
    text = f"{VISIT}，现场仅记录诉求"
    result = plan(client, text, context={"entId": "E001"}, model="configured-test-route")
    assert result["slots"] == {"ent": "E001", "notes": "现场仅记录诉求"}
    assert result["steps"][2]["value"] == "现场仅记录诉求"
    assert result["steps"][4]["write"] is True
    assert len(calls) == 1
    app, messages, options = calls[0]
    assert (app, options["model"], options["classification"]) == ("enterprise", "configured-test-route", "confidential")
    assert messages[-1]["content"] == text
    assert options["_principal"].id == "u-wangmin"

    rule_result = plan(client, f"{VISIT}：保留原话", context={"entId": "E099"})
    assert rule_result["slots"] == {"ent": "E001", "notes": "保留原话"}
    assert len(calls) == 1
    assert plan(login(instance, "partner"), text)["mode"] == "forbidden"
    assert len(calls) == 1


def test_rule_wins_over_matching_example_and_keeps_grounded_entity(instance):
    platform = instance.state.platform
    text = "查一下纸鹿二号智驾"
    platform.apps["enterprise"].manifest["intents"].insert(0, {
        "id": "enterprise.alternate", "examples": [text],
    })
    client = login(instance, "member")
    result = plan(client, text, context={"entId": "E099"})
    assert (result["intent"], result["confidence"], result["mode"], result["slots"]) == (
        "enterprise.find", 0.92, "execute", {"ent": "E002"},
    )
    result = plan(client, "补填数据采购额 30 万", context={"entId": "E001"})
    assert result["intent"] == "policy.fill"
    assert result["slots"] == {"ent": "E001", "amount": 300000}
    # 默认实例的 policy.match 已有完整桥绑定，计划给出带企业与覆盖字段的真实调用步骤。
    call = {"tool": "policy.match", "args": {"entId": "E001", "overrides": {"dataPurchase": 300000}}}
    assert [(step["action"], step.get("tool"), step.get("args")) for step in result["steps"]] == [
        ("open", None, None), ("call", call["tool"], call["args"]),
    ]


def _purchase_checks(body):
    return {row["id"]: [check["state"] for check in row["checks"] if check["condition"]["f"] == "dataPurchase"]
            for row in body["results"] if row["id"] in ("RP-001", "RP-003")}


def test_policy_fill_plan_executes_real_match_through_bridge(instance, monkeypatch):
    # 业务路由需要应用模型句柄；本用例不调用模型。
    monkeypatch.setattr(instance.state.platform.model, "for_app", lambda *args, **kwargs: None, raising=False)
    client = login(instance, "member")
    result = plan(client, "补填数据采购额 30 万", context={"entId": "E001"})
    assert result["mode"] == "execute"
    step = next(step for step in result["steps"] if step["action"] == "call")
    app_id, tool = step["tool"].split(".")
    baseline = client.post(f"/api/v1/apps/{app_id}/tools/{tool}", json={"args": {"entId": "E001"}})
    executed = client.post(f"/api/v1/apps/{app_id}/tools/{tool}", json={"args": step["args"]})
    assert baseline.status_code == executed.status_code == 200, executed.text
    assert executed.json()["result"]["profile"]["dataPurchase"] == 300000
    assert _purchase_checks(baseline.json()["result"]) == {"RP-001": ["unknown"], "RP-003": ["unknown"]}
    assert _purchase_checks(executed.json()["result"]) == {"RP-001": ["ok"], "RP-003": ["ok"]}
    calls = [item["detail"] for item in instance.state.platform.store.audit_list()
             if item["action"] == "tool.call" and item["detail"]["tool"] == "policy.match"]
    assert [detail["outcome"] for detail in calls] == ["ok", "ok"]
    assert report(client, result["planId"], {"s1": "done", step["id"]: "done"}).json()["status"] == "done"

    readonly = login(instance, "partner")
    denied = plan(readonly, "补填数据采购额 30 万", context={"entId": "E001"})
    step = next(step for step in denied["steps"] if step["action"] == "call")
    codes(readonly.post("/api/v1/apps/policy/tools/match", json={"args": step["args"]}), 403, "FORBIDDEN")


def test_visit_honors_write_metadata_from_tools_bridge(instance, monkeypatch):
    monkeypatch.setattr(instance.state, "apps_bridge", SimpleNamespace(
        tools=lambda user: {"items": [
            {"name": "enterprise.propose_update", "app": "enterprise", "write": True},
        ]},
    ), raising=False)
    client = login(instance, "member")
    result = plan(client)
    proposal = result["steps"][3]
    assert (proposal["id"], proposal["action"], proposal["write"]) == ("s4", "confirm", True)
    codes(report(client, result["planId"], {"s4": "done"}), 409, "WRITE_CONFIRMATION_REQUIRED")
    assert report(client, result["planId"], {"s4": "done"}, confirmed=["s4"]).is_success


def test_failure_stop_and_late_receipt(instance):
    client = login(instance, "member")
    identity = plan(client)["planId"]
    partial = report(client, identity, {"s1": "done", "s2": "failed"}).json()
    assert partial["status"] == "running"
    stop_url = f"{BASE}/runs/{partial['id']}/stop"
    stopped = client.post(stop_url).json()
    assert stopped["status"] == "stopped"
    assert [step["status"] for step in stopped["steps"]] == ["done", "failed", "skipped", "skipped", "skipped"]
    assert operator_audit(instance)[0]["detail"] == {
        "via": "operator", "runId": identity, "status": "stopped", "skipped": ["s3", "s4", "s5"],
    }
    codes(report(client, identity, {"s5": "done"}, confirmed=["s5"]), 409, "INVALID_STATE")
    assert client.post(stop_url).json() == stopped

    identity = plan(client)["planId"]
    result = report(client, identity, {"s1": "done", "s2": "failed",
                                      "s3": "skipped", "s4": "skipped", "s5": "skipped"})
    assert result.json()["status"] == "failed"
    assert operator_audit(instance)[0]["detail"]["status"] == "failed"


def test_stop_can_arrive_before_first_receipt(instance):
    client = login(instance, "member")
    identity = plan(client)["planId"]
    stopped = client.post(f"{BASE}/runs/{identity}/stop")
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"
    assert [step["status"] for step in stopped.json()["steps"]] == ["skipped"] * 5
    codes(report(client, identity, {"s1": "done"}), 409, "INVALID_STATE")


def test_rejects_forged_steps_foreign_access_and_revoked_permission(instance):
    member = login(instance, "member")
    identity = plan(member)["planId"]
    codes(report(member, identity, {"s6": "done"}), 422, "CHECK_FAILED")
    codes(report(member, identity, {"s1": "done"}, confirmed=["s1"]), 422, "CHECK_FAILED")
    codes(member.post(f"{BASE}/runs", json={
        "planId": identity, "steps": [{"id": "s1", "at": AT, "status": "done", "write": False}],
    }), 422, "CHECK_FAILED")

    admin = login(instance, "admin")
    codes(report(admin, identity, {}), 404, "NOT_FOUND")
    codes(admin.post(f"{BASE}/runs/{identity}/stop"), 404, "NOT_FOUND")
    assert report(member, identity, {"s1": "done"}).status_code == 200
    grants = admin.put("/api/v1/admin/grants/member/enterprise", json={"actions": ["view"]})
    assert grants.status_code == 200, grants.text
    codes(report(member, identity, {"s5": "done"}, confirmed=["s5"]), 403, "FORBIDDEN")
    assert operator_audit(instance)[0]["detail"]["need"] == "operate"
    assert member.post(f"{BASE}/runs/{identity}/stop").json()["status"] == "stopped"

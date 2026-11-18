"""使用真实企业路由、core 版本服务与临时原值库核对走访及工具。"""

import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from os import environ
from importlib import import_module
from pathlib import Path

import pytest
from fastapi import Body, Depends
from haiknow_sdk import DataError, app_context
from haiknow_sdk.resources import Records

PREFIX = "/api/apps/enterprise"


@pytest.fixture
def enterprise(isolated_platform, make_client, tmp_path_factory, monkeypatch):
    config, apps = isolated_platform
    app_dir = apps / "enterprise"
    shutil.copytree(Path(__file__).resolve().parents[1] / "api", app_dir / "api")
    manifest = json.loads((apps / "sample-app/app.json").read_text())
    manifest.update(id="enterprise", defaultRoles={"partner": ["view", "operate"]})
    (app_dir / "app.json").write_text(json.dumps(manifest))
    # 使用仓库里的真实注册点，确保走访、决定和工具路由已挂载。
    (config / "projects.yaml").write_text(json.dumps({"companies": [
        {"id": "sample-company", "name": "样例", "projects": [{"id": "jkq", "name": "经开区"}]}
    ]}))
    users = json.loads((config / "users.yaml").read_text())
    users["users"].append({"id": "partner", "name": "外部协作", "roles": ["partner"], "projects": ["jkq"]})
    (config / "users.yaml").write_text(json.dumps(users))
    raw_dir = tmp_path_factory.mktemp("enterprise-raw")
    monkeypatch.setenv("JKQ_ENTERPRISE_PRIVATE_DB", str(raw_dir / "enterprise.sqlite"))
    with make_client() as client:
        assert client.post("/api/auth/login", json={"user_id": "sampleadmin"}).is_success
        yield client


def company(client, **fields):
    response = client.post(PREFIX + "/companies", json={"name": "虚构走访企业", **fields})
    assert response.is_success, response.text
    return response.json()["item"]["id"]


def visit(client, ident, notes, **fields):
    return client.post(f"{PREFIX}/companies/{ident}/visits", json={"notes": notes, **fields})


def decision(client, proposal, choice, **fields):
    return client.post(f"{PREFIX}/proposals/{proposal['id']}/decision", json={"decision": choice, **fields})


def detail(client, ident):
    response = client.get(f"{PREFIX}/companies/{ident}")
    assert response.is_success, response.text
    return response.json()


def version(client, ident):
    response = client.get(f"/api/v1/apps/enterprise/records/{ident}")
    assert response.is_success, response.text
    return response.json()["version"]


def module(name):
    return import_module(f"haiknow_apps.enterprise.{name}")


def test_walkthrough_accept_reject_and_history(enterprise):
    cid = company(enterprise, employees=25, phone="13900001111")
    notes = "员工增至30人。联系电话变更为13900002222。企业希望协调材料。"
    response = visit(enterprise, cid, notes, type="电话")
    assert response.is_success, response.text
    payload = response.json()
    assert set(payload) == {"visit", "proposals", "issues"}
    assert payload["visit"]["type"] == "电话"
    assert payload["issues"] == ["企业希望协调材料"]
    assert "13900002222" not in response.text
    candidates = {p["field"]: p for p in payload["proposals"]}
    assert set(candidates) == {"phone", "employees"}
    assert all(p["status"] == "pending" and p["source"] in notes for p in candidates.values())
    initial = detail(enterprise, cid)
    assert initial["visits"] == [payload["visit"]]
    assert initial["proposals"] == payload["proposals"]
    assert initial["item"]["employees"] == 25
    assert initial["history"] == []
    assert version(enterprise, cid) == 1

    rejected = decision(enterprise, candidates["phone"], "reject")
    assert rejected.json()["item"]["status"] == "rejected"
    assert rejected.json()["pending"] == 1
    assert version(enterprise, cid) == 1
    assert detail(enterprise, cid)["history"] == []

    accepted = decision(enterprise, candidates["employees"], "accept", value=0)
    assert accepted.json()["item"]["status"] == "accepted"
    assert accepted.json()["pending"] == 0
    assert version(enterprise, cid) == 2
    saved = detail(enterprise, cid)
    assert saved["item"]["employees"] == 0
    assert saved["item"]["phone"] == "139****1111"
    assert saved["proposals"] == []
    change, = saved["history"]
    assert (change["field"], change["old"], change["new"], change["source"]) == ("employees", 25, 0, "走访记录")
    assert change["visitId"] == payload["visit"]["id"]
    for proposal in candidates.values():
        retried = decision(enterprise, proposal, "accept")
        assert (retried.status_code, retried.json()["error"]["code"]) == (409, "LOCKED")
    assert version(enterprise, cid) == 2


@pytest.mark.parametrize("notes", [None, "", " \t\n", []])
def test_blank_notes_400(enterprise, notes):
    cid = company(enterprise)
    response = visit(enterprise, cid, notes)
    assert (response.status_code, response.json()["error"]["code"]) == (400, "INVALID_REQUEST")
    assert detail(enterprise, cid)["visits"] == []


@pytest.mark.parametrize("result", [RuntimeError("上游响应细节"), {"proposals": []}])
def test_model_failure_keeps_visit(enterprise, result):
    visits = module("visits")
    extraction = module("visit_extraction")

    def invoke(*_):
        if isinstance(result, Exception):
            raise result
        return result

    enterprise.app.dependency_overrides[visits.visit_extractor] = lambda: extraction.Extractor(
        extraction.Destination("private-test", "local"), invoke,
    )
    cid = company(enterprise)
    response = visit(enterprise, cid, "走访原文。")
    assert response.is_success and "上游响应细节" not in response.text
    body = response.json()
    assert body["proposals"] == [] and body["issues"] == []
    assert "走访已保存" in body["visit"]["warning"]
    assert detail(enterprise, cid)["visits"] == [body["visit"]]
    assert version(enterprise, cid) == 1


def test_candidate_validation_and_stale_field(enterprise):
    visits = module("visits")
    extraction = module("visit_extraction")
    notes = "职工为30人。希望咨询支持政策。"
    candidates = [
        {"field": "employees", "new": 2.5, "source": "职工为30人"},
        {"field": "industry", "new": "新行业", "source": "职工为30人"},
        {"field": "scale", "new": "大型", "source": "杜撰的外出走访"},
        {"field": "employees", "new": 30, "source": "职工为30人"},
        {"field": "employees", "new": 31, "source": "职工为30人"},
    ]
    enterprise.app.dependency_overrides[visits.visit_extractor] = lambda: extraction.Extractor(
        extraction.Destination("private-test", "local"),
        lambda *_: {"proposals": candidates, "issues": ["无出处的诉求", "希望咨询支持政策"]},
    )
    cid = company(enterprise, employees=21)
    result = visit(enterprise, cid, notes).json()
    proposal, = result["proposals"]
    assert proposal["new"] == 30 and proposal["source"] in notes
    assert result["issues"] == ["希望咨询支持政策"]
    assert "已忽略" in result["visit"]["warning"]
    invalid = decision(enterprise, proposal, "accept", value=3.2)
    assert (invalid.status_code, invalid.json()["error"]["code"]) == (400, "INVALID_REQUEST")
    assert enterprise.patch(f"{PREFIX}/companies/{cid}", json={"employees": 29}).is_success
    stale = decision(enterprise, proposal, "accept")
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "STALE_VERSION")
    assert detail(enterprise, cid)["item"]["employees"] == 29
    assert version(enterprise, cid) == 2
    assert decision(enterprise, proposal, "reject").is_success


def test_private_amounts_and_independent_decisions(enterprise):
    cid = company(enterprise, amounts={"rent": 5100, "area": 100})
    raw = "房租约7.25万元。面积为500平方米。"
    response = visit(enterprise, cid, raw)
    by_field = {p["field"]: p for p in response.json()["proposals"]}
    for field in ("amounts.rent", "amounts.area"):
        assert by_field[field]["new"] == "****"
        assert by_field[field]["source"] in raw
        assert decision(enterprise, by_field[field], "accept").is_success
    result = detail(enterprise, cid)
    assert result["item"]["amounts"] == {"rent": "****", "area": "****"}
    records = enterprise.app.state.platform.store._db.execute("SELECT document FROM v1_versions").fetchall()
    assert all("72500" not in row[0] and "7.25" not in row[0] for row in records)
    for change in result["history"]:
        assert change["source"] == "走访记录"
        assert change["field"] in by_field and change["new"] == "****"
    assert version(enterprise, cid) == 3


def test_new_contact_and_license_keep_previous_entries(enterprise):
    cid = company(enterprise, contacts=[{"name": "示例一", "phone": "13900001111"}], license=["示例资质"])
    notes = "新任行政主管示例二（电话 13900002222）负责对接。已取得出版物经营许可证。"
    response = visit(enterprise, cid, notes)
    assert response.is_success and "13900002222" not in response.text
    candidates = {p["field"]: p for p in response.json()["proposals"]}
    assert set(candidates) == {"contacts", "license"}
    for candidate in candidates.values():
        assert candidate["source"] in notes
        assert decision(enterprise, candidate, "accept").is_success
    saved = detail(enterprise, cid)["item"]
    assert saved["contacts"] == [{"name": "示例一", "phone": "139****1111"},
                                  {"name": "示例二", "title": "行政主管", "phone": "139****2222"}]
    assert saved["license"] == ["示例资质", "出版物经营许可证"]
    assert version(enterprise, cid) == 3


def test_failed_core_commit_and_competing_decisions(enterprise, monkeypatch):
    cid = company(enterprise, employees=4)
    proposal, = visit(enterprise, cid, "员工有5人。").json()["proposals"]
    save = Records.save

    def fail_write(self, **body):
        if body.get("data", {}).get("change", {}).get("proposalId"):
            raise DataError("version_conflict", "模拟 core 版本提交冲突")
        return save(self, **body)

    with monkeypatch.context() as patch:
        patch.setattr(Records, "save", fail_write)
        assert decision(enterprise, proposal, "accept").status_code == 409
        current = detail(enterprise, cid)
        assert not current["history"] and current["proposals"] == [proposal]
        assert version(enterprise, cid) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: decision(enterprise, proposal, "accept"), range(2)))
    assert sorted(r.status_code for r in replies) == [200, 409]
    assert version(enterprise, cid) == 2
    assert len(detail(enterprise, cid)["history"]) == 1


def test_unavailable_company_and_partner(enterprise):
    missing = enterprise.get(PREFIX + "/companies/missing")
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "NOT_FOUND")
    cid = company(enterprise)
    proposal, = visit(enterprise, cid, "员工有10人。").json()["proposals"]
    assert visit(enterprise, "missing", "走访。").status_code == 404
    assert decision(enterprise, {"id": "missing"}, "accept").status_code == 404
    assert enterprise.post("/api/auth/login", json={"user_id": "partner"}).is_success
    assert visit(enterprise, cid, "走访。").status_code == 403
    assert decision(enterprise, proposal, "accept").status_code == 403
    assert version(enterprise, cid) == 1


def test_tools_use_pending_path_and_egress_guard(enterprise):
    tools = module("visit_tools")
    extraction = module("visit_extraction")
    visits = module("visits")
    calls = []

    def payload(ledger, notes):
        calls.append((ledger, notes))
        return extraction.mock_extract(ledger, notes)

    blocked = extraction.Destination("unlisted", "cloud")
    allowed = extraction.Destination("approved", "cloud")
    allowlist = frozenset({"approved"})
    enterprise.app.dependency_overrides[visits.visit_extractor] = lambda: extraction.Extractor(
        blocked, payload, allowlist,
    )

    # 应用内 HTTP 桩模拟网关，以服务端路由决定目的地，用户参数只传业务输入。
    @enterprise.app.post(PREFIX + "/conversation-stub/{route}/{name}")
    def conversation(route: str, name: str, args: dict = Body(), ctx=Depends(app_context)):
        destination = {"local": extraction.Destination("local-model", "local"),
                       "external": blocked, "approved": allowed}[route]
        return tools.run_tool(ctx, name, args, destination=destination, allowlist=allowlist,
                              extractor=extraction.Extractor(destination, payload, allowlist))

    cid = company(enterprise, employees=7, phone="13900009999")
    assert {t["name"] for t in enterprise.get(PREFIX + "/tools").json()["items"]} == {
        "enterprise.search", "enterprise.get", "enterprise.propose_update",
    }
    assert enterprise.post(PREFIX + "/tools/enterprise.search", json={"args": {"q": "虚构"}}).json()[
        "result"]["items"][0]["id"] == cid
    args = {"id": cid, "notes": "员工增至13人。", "decision": "accept", "model": "approved"}

    response = visit(enterprise, cid, args["notes"])
    assert response.is_success and response.json()["proposals"] == []
    assert "白名单" in response.json()["visit"]["warning"]
    for name in ("enterprise.search", "enterprise.get", "enterprise.propose_update"):
        denied = enterprise.post(f"{PREFIX}/conversation-stub/external/{name}", json=args)
        assert (denied.status_code, denied.json()["error"]["code"]) == (403, "outbound_denied")
    assert calls == []

    for route in ("local", "approved"):
        result = enterprise.post(f"{PREFIX}/conversation-stub/{route}/enterprise.propose_update", json=args)
        proposal, = result.json()["result"]["proposals"]
        assert proposal["status"] == "pending"
    assert all(ledger["phone"] == "139****9999" for ledger, _ in calls)
    assert len(calls) == 2
    assert version(enterprise, cid) == 1
    assert detail(enterprise, cid)["item"]["employees"] == 7


def raw_company(client, ident):
    doc = client.get(f"/api/v1/apps/enterprise/records/{ident}").json()
    with sqlite3.connect(environ["JKQ_ENTERPRISE_PRIVATE_DB"]) as db:
        raw, = db.execute("SELECT body FROM snapshots WHERE ref = ?", (doc["data"]["snapshot"],)).fetchone()
    return json.loads(raw)


@pytest.mark.parametrize(("unit", "expected"), [("万元", 120), ("元", 1_200_000), ("亿元", 0.012)])
def test_revenue_uses_ledger_unit(enterprise, unit, expected):
    cid = company(enterprise, revenue={"value": 45, "unit": unit})
    proposal, = visit(enterprise, cid, "营收为120万元。").json()["proposals"]
    assert decision(enterprise, proposal, "accept").is_success
    assert raw_company(enterprise, cid)["revenue"] == {"value": expected, "unit": unit}
    assert version(enterprise, cid) == 2
    change, = detail(enterprise, cid)["history"]
    assert change["field"] == "revenue.value"


@pytest.mark.parametrize(("unit", "notes"), [
    ("", "营收为120万元。"), ("美元", "营收为120万元。"),
    ("万元", "营收为120。"), ("万元", "营收为120万欧元。"),
    ("万元", "营收为120万元 美元。"),
])
def test_unknown_revenue_unit_requires_manual_review(enterprise, unit, notes):
    cid = company(enterprise, revenue={"value": 45, "unit": unit})
    result = visit(enterprise, cid, notes).json()
    assert result["proposals"] == []
    assert "人工核对" in result["visit"]["warning"]
    assert raw_company(enterprise, cid)["revenue"] == {"value": 45, "unit": unit}
    assert version(enterprise, cid) == 1


@pytest.mark.parametrize(("notes", "candidate", "field", "initial"), [
    ("职工现有30人。", {"new": 300, "source": "职工现有30人"}, "employees", 25),
    ("职工现有30人。", {"new": 30, "unit": "人次", "source": "职工现有30人"}, "employees", 25),
    ("办公室容纳30人。", {"new": 30, "source": "办公室容纳30人"}, "employees", 25),
    ("职工现有30人次。", {"new": 30, "source": "职工现有30人"}, "employees", 25),
    ("职工现有30人至50人。", {"new": 30, "source": "职工现有30人"}, "employees", 25),
    ("目前尚未确认，已取得出版物经营许可证的说法待核实。", {
        "new": "出版物经营许可证", "source": "已取得出版物经营许可证",
    }, "license", []),
    ("营收为120万元。", {"new": 120, "source": "营收为120万元"}, "revenue.value", {"value": 45, "unit": "万元"}),
    *[
        (f"目前{negative}取得出版物经营许可证。", {"new": "出版物经营许可证", "source": source}, "license", [])
        for negative, source in [
            ("尚未", "取得出版物经营许可证"),
            ("没有", "出版物经营许可证"),
            ("未", "取得出版物经营许可证"),
        ]
    ],
])
def test_model_evidence_must_support_field_value_and_unit(enterprise, notes, candidate, field, initial):
    visits = module("visits")
    extraction = module("visit_extraction")
    enterprise.app.dependency_overrides[visits.visit_extractor] = lambda: extraction.Extractor(
        extraction.Destination("private-test", "local"),
        lambda *_: {"proposals": [{"field": field, **candidate}], "issues": []},
    )
    key = field.split(".")[0]
    cid = company(enterprise, **{key: initial})
    assert visit(enterprise, cid, notes).json()["proposals"] == []
    assert raw_company(enterprise, cid)[key] == initial
    assert version(enterprise, cid) == 1
    assert detail(enterprise, cid)["history"] == []


@pytest.mark.parametrize("amount", ["四十八万", "四十八万元", "肆拾捌萬圓", "四十点八万", "48万"])
def test_partner_and_tools_receive_safe_summaries(enterprise, amount):
    cid = company(enterprise, employees=7)
    notes = f"年房租约{amount}每年，需要协调。职工现有30人。"
    payload = visit(enterprise, cid, notes, type=f"含{amount}的走访").json()
    assert payload["proposals"]
    ident = payload["visit"]["id"]
    issue = enterprise.post("/api/v1/apps/enterprise/records", json={
        "project": "jkq", "type": "enterprise.issue", "data": {"item": {
            "entId": cid, "title": f"需要协调每年{amount}的房租",
        }},
    })
    assert issue.is_success, issue.text
    assert amount in detail(enterprise, cid)["issues"][0]["title"]

    # 工具即使以经办人身份调用，也只返回面向模型的展示。
    def tool_get():
        return enterprise.post(f"{PREFIX}/tools/enterprise.get", json={"args": {"id": cid}})

    tool = tool_get()
    assert tool.is_success and amount not in tool.text
    assert tool.json()["result"]["visits"][0]["id"] == ident
    assert tool.json()["result"]["visits"][0].get("notes", "") == ""
    safe = enterprise.post(f"{PREFIX}/tools/enterprise.propose_update", json={"args": {
        "id": cid, "notes": notes, "type": f"含{amount}的走访",
    }})
    assert safe.is_success and amount not in safe.text and safe.json()["result"]["issues"]
    assert safe.json()["result"]["proposals"][0].get("source", "") == ""

    assert enterprise.post("/api/auth/login", json={"user_id": "partner"}).is_success
    lookup = enterprise.get(f"{PREFIX}/companies/{cid}")
    assert lookup.is_success and amount not in lookup.text
    assert lookup.json()["visits"][-1]["id"] == ident
    assert lookup.json()["visits"][-1].get("notes", "") == ""
    assert lookup.json()["proposals"][0].get("source", "") == ""
    assert amount not in tool_get().text
    with sqlite3.connect(environ["JKQ_ENTERPRISE_PRIVATE_DB"]) as db:
        row, = db.execute("SELECT body FROM visit_notes WHERE id = ?", (ident,)).fetchone()
    assert json.loads(row)["notes"] == notes


@pytest.mark.parametrize("fail_model", [False, True])
def test_saved_visit_refreshes_detail_sort_and_overdue_filter(enterprise, fail_model):
    visits = module("visits")
    extraction = module("visit_extraction")
    today = datetime.now(visits.BEIJING).date()
    old = (today - timedelta(days=120)).isoformat()
    cid = company(enterprise, lastVisit=old, lastVisitDays=120)
    other = company(enterprise, name="仍未回访的企业", lastVisitDays=110)

    def listing(**params):
        reply = enterprise.get(f"{PREFIX}/companies", params=params)
        assert reply.is_success
        return reply.json()

    assert [row["id"] for row in listing(alert=1)["items"]] == [cid, other]
    if fail_model:
        def fail(*_):
            raise RuntimeError("模拟模型故障")
        enterprise.app.dependency_overrides[visits.visit_extractor] = lambda: extraction.Extractor(
            extraction.Destination("private-test", "local"), fail,
        )
    result = visit(enterprise, cid, "员工现有8人。").json()
    assert ("warning" in result["visit"]) == fail_model
    date = result["visit"]["date"]
    item = detail(enterprise, cid)["item"]
    assert (item["lastVisit"], item["lastVisitDays"]) == (date, 0)
    first, refreshed = listing(sort="lastVisit")["items"]
    assert first["id"] == other and refreshed["id"] == cid
    assert (refreshed["lastVisit"], refreshed["lastVisitDays"]) == (date, 0)
    assert [row["id"] for row in listing(alert=1)["items"]] == [other]
    assert version(enterprise, cid) == 1
    assert detail(enterprise, cid)["history"] == []


def test_generic_record_write_cannot_mark_proposal_accepted(enterprise):
    cid = company(enterprise, employees=4)
    proposal, = visit(enterprise, cid, "职工现有5人。").json()["proposals"]
    path = f"/api/v1/apps/enterprise/records/{cid}"
    original = enterprise.get(path).json()
    forged = enterprise.put(path, json={"baseVersion": 1, "data": {
        **original["data"], "change": {"proposalId": proposal["id"]},
    }})
    assert forged.is_success, forged.text
    assert detail(enterprise, cid)["proposals"] == [proposal]
    assert decision(enterprise, proposal, "accept").is_success
    assert version(enterprise, cid) == 3
    assert raw_company(enterprise, cid)["employees"] == 5
    assert decision(enterprise, proposal, "accept").status_code == 409


def test_revenue_unit_change_makes_pending_amount_stale(enterprise):
    cid = company(enterprise, revenue={"value": 45, "unit": "万元"})
    proposal, = visit(enterprise, cid, "营收为120万元。").json()["proposals"]
    assert enterprise.patch(f"{PREFIX}/companies/{cid}", json={"revenue": {"value": 45, "unit": "元"}}).is_success
    stale = decision(enterprise, proposal, "accept")
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "STALE_VERSION")
    assert raw_company(enterprise, cid)["revenue"] == {"value": 45, "unit": "元"}
    assert version(enterprise, cid) == 2


def test_acceptance_recovered_after_commit_reply_is_interrupted(enterprise, monkeypatch):
    cid = company(enterprise, employees=4)
    proposal, = visit(enterprise, cid, "职工现有5人。").json()["proposals"]
    write = Records.save

    def commit_then_interrupt(self, **body):
        write(self, **body)
        raise DataError("internal_error", "模拟 core 提交后中断")

    with monkeypatch.context() as patch:
        patch.setattr(Records, "save", commit_then_interrupt)
        assert decision(enterprise, proposal, "accept").status_code == 500

    assert raw_company(enterprise, cid)["employees"] == 5
    assert detail(enterprise, cid)["proposals"] == []
    assert decision(enterprise, proposal, "accept").status_code == 409
    assert version(enterprise, cid) == 2
    assert len(detail(enterprise, cid)["history"]) == 1


def test_legacy_proposal_is_retained_but_requires_reextraction(enterprise):
    cid = company(enterprise, employees=4)
    with sqlite3.connect(environ["JKQ_ENTERPRISE_PRIVATE_DB"]) as db:
        db.execute("CREATE TABLE visit_notes (id TEXT PRIMARY KEY, company TEXT, body TEXT)")
        db.execute("""CREATE TABLE visit_proposals (
            id TEXT PRIMARY KEY, company TEXT, body TEXT, rejected INTEGER NOT NULL DEFAULT 0
        )""")
        db.execute("INSERT INTO visit_proposals VALUES (?, ?, ?, 0)", ("old", cid, json.dumps({"entId": cid})))
    assert detail(enterprise, cid)["proposals"] == []
    assert decision(enterprise, {"id": "old"}, "accept").status_code == 409
    assert version(enterprise, cid) == 1
    proposal, = visit(enterprise, cid, "职工现有5人。").json()["proposals"]
    assert decision(enterprise, proposal, "accept").is_success
    with sqlite3.connect(environ["JKQ_ENTERPRISE_PRIVATE_DB"]) as db:
        assert db.execute("SELECT status FROM visit_proposals WHERE id = 'old'").fetchone() == ("legacy",)



def test_model_revenue_with_explicit_supported_unit(enterprise):
    visits = module("visits")
    extraction = module("visit_extraction")
    enterprise.app.dependency_overrides[visits.visit_extractor] = lambda: extraction.Extractor(
        extraction.Destination("private-test", "local"),
        lambda *_: {"proposals": [{"field": "revenue.value", "new": 120, "unit": "万元",
                                   "source": "营收为120万元"}], "issues": []},
    )
    cid = company(enterprise, revenue={"value": 45, "unit": "元"})
    proposal, = visit(enterprise, cid, "营收为120万元。").json()["proposals"]
    assert decision(enterprise, proposal, "accept").is_success
    assert raw_company(enterprise, cid)["revenue"] == {"value": 1_200_000, "unit": "元"}

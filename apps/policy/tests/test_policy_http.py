"""用 FastAPI 挂载政策业务路由，替换 SDK 登录态依赖。"""

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from haiknow_sdk import PermissionDenied, app_context

from apps.policy.api import policy_catalog
from apps.policy.api.policy_routes import router


PREFIX = "/api/apps/policy"
MATCH_CASE = Path(__file__).resolve().parents[3] / "tests/fixtures/policy_match_case.json"


class SnapshotClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 18, 12, tzinfo=tz)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(policy_catalog, "datetime", SnapshotClock)
    app = FastAPI()
    app.include_router(router, prefix=PREFIX)
    app.dependency_overrides[app_context] = lambda: None
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    ("query", "wanted"),
    [("object=个人", "RP-021"), ("window=open", "RP-023"), ("window=ended", "PI-03"), ("window=unknown", "RP-006")],
)
def test_list_filters(api, query, wanted):
    response = api.get(f"{PREFIX}/items?{query}")
    assert response.status_code == 200
    result = response.json()
    assert set(result) == {"items", "total", "docs"}
    assert result["total"] == len(result["items"])
    assert wanted in {item["id"] for item in result["items"]}


def test_detail_and_unknown_item_id(api):
    response = api.get(f"{PREFIX}/items/PI-03")
    assert response.status_code == 200
    item = response.json()["item"]
    assert item["docNo"] == "京技管〔2021〕161号"
    assert item["times"]["open"] is False
    assert item["real"] is True
    assert item["source"]["url"].endswith("t20240426_3639277.html")
    response = api.get(f"{PREFIX}/items/missing")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "事项不存在", "details": {}}}


def test_match_ent_id_and_overrides(api):
    case = json.loads(MATCH_CASE.read_text(encoding="utf-8"))
    response = api.post(f"{PREFIX}/match", json={"entId": case["entId"]})
    assert response.status_code == 200
    original = response.json()
    expected = {item_id: level for level, ids in case["expected"].items() for item_id in ids}
    assert {row["id"]: row["level"] for row in original["results"]} == expected

    response = api.post(
        f"{PREFIX}/match",
        json={"entId": case["entId"], "overrides": {"majorResearchTask": True, "computePurchase": 0, "license": []}},
    )
    assert response.status_code == 200
    changed = response.json()
    assert changed["profile"]["license"] == []
    by_id = {row["id"]: row for row in changed["results"]}
    assert by_id["RP-015"]["level"] == "ok"
    assert by_id["RP-006"]["level"] == "no"
    assert by_id["RP-006"]["calc"] is None
    assert any(check["condition"]["f"] == "computePurchase" and check["state"] == "no" for check in by_id["RP-006"]["checks"])
    assert api.post(f"{PREFIX}/match", json={"entId": case["entId"]}).json() == original


def test_match_manual_profile_excludes_other_subjects_and_indicates_missing_facts(api):
    response = api.post(f"{PREFIX}/match", json={"profile": {"subjectType": "个人"}})
    assert response.status_code == 200
    match = response.json()
    result = next(row for row in match["results"] if row["id"] == "RP-021")
    assert result["level"] == "check"
    assert "PI-03" not in {row["id"] for row in match["results"]}
    assert any(check["state"] == "unknown" and check["reason"] for check in result["checks"])


def test_unknown_demo_company(api):
    response = api.post(f"{PREFIX}/match", json={"entId": "missing"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    ("base", "amount", "capped", "text"),
    [
        (420000, 200000, True, "42 万元 × 50% = 21 万元，超过封顶，按 20 万元"),
        (400000, 200000, False, "40 万元 × 50% = 20 万元"),
        (400000.01, 200000, True, "40.000001 万元 × 50% = 20.0000005 万元，超过封顶，按 20 万元"),
        (120000, 60000, False, "12 万元 × 50% = 6 万元"),
    ],
)
def test_historical_bookstore_estimate(api, base, amount, capped, text):
    response = api.post(f"{PREFIX}/calc", json={"itemId": "PI-03", "amount": base})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"item", "rule", "result", "note"}
    assert body["result"] == {"amount": amount, "base": base, "kind": "ratio", "capped": capped, "text": text}
    assert "历史" in body["note"]


@pytest.mark.parametrize("amount", [0, -1, True, "420000", None])
def test_calc_rejects_invalid_amount(api, amount):
    response = api.post(f"{PREFIX}/calc", json={"itemId": "PI-03", "amount": amount})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_calc_missing_item_and_manual_formula(api):
    missing = api.post(f"{PREFIX}/calc", json={"itemId": "missing", "amount": 420000})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"
    result = api.post(f"{PREFIX}/calc", json={"itemId": "RP-021", "amount": 420000})
    assert result.status_code == 200
    assert result.json()["result"] is None
    assert "人工核算" in result.json()["note"]


def test_request_errors_follow_json_envelope(api):
    response = api.post(f"{PREFIX}/match", json={"entId": "E002", "profile": {}})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    response = api.post(f"{PREFIX}/match", content=b'{"profile":{"rent":NaN}}')
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    response = api.get(f"{PREFIX}/items?window=bad")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_routes_require_platform_view_grant(api):
    def unauthenticated():
        raise HTTPException(401, "未登录")

    def forbidden():
        raise PermissionDenied("policy", "view")

    api.app.dependency_overrides[app_context] = unauthenticated
    response = api.get(f"{PREFIX}/items")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"

    api.app.dependency_overrides[app_context] = forbidden
    response = api.post(f"{PREFIX}/calc", json={"itemId": "PI-03", "amount": 420000})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"

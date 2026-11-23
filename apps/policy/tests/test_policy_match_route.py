"""经实例入口验证政策匹配 POST 已挂载：企业覆盖字段生效，只读角色被拒。"""

from shutil import copyfile

import pytest
from fastapi.testclient import TestClient

from jkq.app import create_app
from jkq.settings import REPO_ROOT


MATCH = "/api/apps/policy/match"
DATA_ITEMS = ("RP-001", "RP-003")


@pytest.fixture
def policy_client(isolated_platform, reuse_loaded_routers, cheap_password_hash, monkeypatch, tmp_path):
    config, _ = isolated_platform
    for name in ("projects.yaml", "roles.yaml", "users.yaml"):
        copyfile(REPO_ROOT / "config" / name, config / name)
    monkeypatch.setenv("HAIKNOW_APPS_DIR", str(REPO_ROOT / "apps"))
    monkeypatch.setenv("HAIKNOW_SECRET", "test-policy-session")
    monkeypatch.setenv("JKQ_ENTERPRISE_PRIVATE_DB", str(tmp_path / "enterprise.db"))
    monkeypatch.delenv("HAIKNOW_DEMO_LOGIN", raising=False)
    monkeypatch.setenv("JKQ_DEMO_MODE", "1")
    for role in ("admin", "leader", "member", "partner"):
        monkeypatch.setenv(f"JKQ_DEMO_{role.upper()}_PASSWORD", f"test-{role}")

    def make(role="admin"):
        client = TestClient(create_app())
        username = {"admin": "admin", "partner": "hejun"}[role]
        response = client.post("/api/v1/auth/login", json={"username": username, "password": f"test-{role}"})
        assert response.status_code == 200, response.text
        return client

    return make


def _data_items(body):
    return {row["id"]: row for row in body["results"] if row["id"] in DATA_ITEMS}


def test_match_post_applies_enterprise_overrides(policy_client):
    client = policy_client()
    base = client.post(MATCH, json={"entId": "E001"})
    assert base.status_code == 200, base.text
    filled = client.post(MATCH, json={"entId": "E001", "overrides": {"dataPurchase": 300000}})
    assert filled.status_code == 200, filled.text
    before, after = _data_items(base.json()), _data_items(filled.json())
    assert set(before) == set(after) == set(DATA_ITEMS)
    for item_id in DATA_ITEMS:
        # 补填的数据采购额让该条件从「待补充」变为「符合」，其余条件保持原判断。
        old_checks = {check["condition"]["f"]: check["state"] for check in before[item_id]["checks"]}
        new_checks = {check["condition"]["f"]: check["state"] for check in after[item_id]["checks"]}
        assert (old_checks.pop("dataPurchase"), new_checks.pop("dataPurchase")) == ("unknown", "ok")
        assert new_checks == old_checks


def test_view_only_role_cannot_match_enterprise(policy_client):
    response = policy_client("partner").post(MATCH, json={"entId": "E001", "overrides": {"dataPurchase": 300000}})
    assert response.status_code == 403


def test_general_enterprise_profile_does_not_confirm_specialized_policy_scope(policy_client):
    response = policy_client().post(MATCH, json={"profile": {
        "subjectType": "企业", "regInZone": True,
        "tags": ["智能网联汽车", "人工智能"], "license": ["高新技术企业"], "yearsInZone": 3,
    }})
    assert response.status_code == 200, response.text
    results = {row["id"]: row for row in response.json()["results"]}
    for item_id, field in {
        "RP-028": "supplyChainFinanceProvider",
        "RP-038": "exportCreditInsuredEnterprise",
        "RP-050": "recognizedIncubator",
        "RP-062": "assemblyProject",
    }.items():
        row = results[item_id]
        assert row["level"] == "check", (item_id, row["level"])
        assert any(c["condition"]["f"] == field and c["state"] == "unknown" for c in row["checks"])

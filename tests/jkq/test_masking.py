"""Issue #14：真实会话与 RBAC，业务数据及 CSV 排版使用接口桩。"""

import csv
from io import StringIO
from pathlib import Path
import shutil

import pytest

from jkq.masking import MaskRules, _apply, enterprise_card, install

ROOT = Path(__file__).resolve().parents[2]
BASE = "/api/apps/enterprise"
DETAIL = BASE + "/companies/E1"
ROW = {"id": "E1", "name": "样例,企业", "contacts": [{"phone": "13900003456"}, {"phone": "18011112222"}],
       "amounts": {"revenue": 12345678, "tax": 45678}, "revenue": {"value": 12345678}}
MASKED = {**ROW, "contacts": [{"phone": "139****3456"}, {"phone": "180****2222"}],
          "amounts": {"revenue": "****", "tax": "****"}, "revenue": {"value": "****"}}
CHANGES = [{"field": "联系电话", "old": "13900003456", "new": "18011112222", "source": "13900003456"}]
PROPOSALS = [{"field": "amounts.tax", "old": 45678, "new": 56789, "source": "税额 45678"}]
SPACES = [{"id": "policy", "name": "政策", "icon": "P", "count": 7},
          {"id": "enterprise", "name": "企业", "icon": "E", "count": 3}]
USERS = {
    "admin": "sampleadmin",
    "leader": "sampleleader",
    "member": "samplemember",
    "partner": "samplepartner",
}


@pytest.mark.parametrize("value", ["", None, "1", "123", 123, "1234567"])
def test_short_fields_are_fully_hidden(value):
    record = {"contacts": [{"phone": value}, {}, {"phone": "13900003456"}]}
    _apply(record, ["contacts[]", "phone"], 3, "****", 4)
    assert record["contacts"] == [{"phone": "****"}, {}, {"phone": "139****3456"}]


def test_malformed_contact_cannot_pass_through():
    with pytest.raises(ValueError):
        _apply({"contacts": ["13900003456"]}, ["contacts[]", "phone"], 3, "****", 4)


def test_reload(tmp_path):
    pytest.importorskip("yaml")
    path = tmp_path / "rules.yaml"
    shutil.copy(ROOT / "config/mask_rules.yaml", path)
    rules = MaskRules(path)
    assert rules.projector("enterprise")(ROW) == MASKED
    path.write_text(path.read_text().replace("139****3456", "**56"))
    rules.reload()
    assert rules.projector("enterprise")(ROW)["contacts"][0]["phone"] == "**56"
    path.write_text("rules: []")
    with pytest.raises(ValueError):
        rules.reload()
    assert rules.projector("enterprise")(ROW)["contacts"][0]["phone"] == "**56"


class Source:
    def detail(self, company_id, request):
        assert company_id == ROW["id"]
        return {"item": {**ROW, "history": CHANGES}, "visits": [], "history": CHANGES, "proposals": PROPOSALS}

    def companies(self, request):
        return {"items": [ROW], "total": 1}

    def export_rows(self, request):
        return [ROW] if request.query_params["ids"] == ROW["id"] else []

    def format_csv(self, rows):
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["名称", "电话", "营收", "税额"])
        for row in rows:
            writer.writerow([row["name"], row["contacts"][0]["phone"], row["amounts"]["revenue"],
                             row["amounts"]["tax"]])
        return {"filename": "样例.csv", "csv": buffer.getvalue()}

    def spaces(self, request):
        return {"items": SPACES}

    def kb_docs(self, space, excluded, request):
        hits = [{"space": key} for key in ("policy", "enterprise") if key not in excluded and space in (None, key)]
        return {"hits": hits, "total": len(hits)}


@pytest.fixture
def instance(request):
    pytest.importorskip("fastapi")
    yaml = pytest.importorskip("yaml")
    from fastapi import Depends
    from fastapi.testclient import TestClient
    from haiknow_core.main import create_app

    request.getfixturevalue("cheap_password_hash")
    request.getfixturevalue("reuse_loaded_routers")
    config, _apps = request.getfixturevalue("isolated_platform")
    shutil.copy(ROOT / "config/mask_rules.yaml", config / "mask_rules.yaml")
    roles = {
        "admin": {"name": "管理员", "mask": False,
                  "grants": {"*": ["view", "operate", "approve", "admin"]}},
        "leader": {"name": "审签领导", "mask": False,
                   "grants": {"*": ["view", "operate", "approve"]}},
        "member": {"name": "经办人员", "mask": False,
                   "grants": {"enterprise": ["view", "operate"], "kb": ["view"]}},
        "partner": {"name": "外部协作者", "mask": True,
                    "grants": {"enterprise": ["view"], "kb": ["view"]}},
    }
    (config / "roles.yaml").write_text(yaml.safe_dump({"roles": roles}, allow_unicode=True), encoding="utf-8")
    (config / "users.yaml").write_text(yaml.safe_dump({"users": [
        {"id": "sampleadmin", "name": "管理员", "roles": ["admin"], "projects": ["*"]},
        {"id": "sampleleader", "name": "审签领导", "roles": ["leader"], "projects": ["*"]},
        {"id": "samplemember", "name": "经办人员", "roles": ["member"], "projects": ["*"]},
        {"id": "samplepartner", "name": "外部协作者", "roles": ["partner"], "projects": ["*"]},
    ]}, allow_unicode=True), encoding="utf-8")
    app = create_app(ROOT)
    install(app, Source())

    @app.post("/api/v1/conversations/{conversation_id}/messages")
    def message(conversation_id: str, body: dict, project=Depends(app.state.enterprise_projector)):
        return {"conversation": {"id": conversation_id}, "user": {"content": body["text"]},
                "reply": {"role": "assistant", "cards": [enterprise_card(ROW, project)]}}

    with TestClient(app) as client:
        yield client, config


def login(instance, role="partner"):
    client, _ = instance
    response = client.post("/api/auth/login", json={"user_id": USERS[role]})
    assert response.status_code == 200
    return client


@pytest.mark.parametrize("role", ["admin", "leader", "member", "partner"])
def test_detail(instance, role):
    result = login(instance, role).get(DETAIL)
    assert result.status_code == 200
    masked = role == "partner"
    history = [] if masked else CHANGES
    assert result.json() == {"item": {**(MASKED if masked else ROW), "history": history}, "visits": [],
                             "history": history, "proposals": [] if masked else PROPOSALS}


def test_list(instance):
    assert login(instance).get(BASE + "/companies").json() == {"items": [MASKED], "total": 1}


def test_csv(instance):
    payload = login(instance).get(BASE + "/export", params={"ids": "E1"}).json()
    assert list(csv.reader(StringIO(payload["csv"])))[1] == [ROW["name"], "139****3456", "****", "****"]


@pytest.mark.parametrize("role", ["partner", "member"])
def test_card(instance, role):
    response = login(instance, role).post("/api/v1/conversations/C1/messages", json={"text": "查看企业"})
    assert response.status_code == 200
    card_item = MASKED if role == "partner" else ROW
    assert response.json()["reply"]["cards"] == [
        {"type": "enterprise-brief", "entId": "E1", "item": card_item}]


@pytest.mark.parametrize("role", ["partner", "member"])
def test_kb_libraries(instance, role):
    client = login(instance, role)
    visible = SPACES[:1] if role == "partner" else SPACES
    assert client.get("/api/v1/kb/spaces").json() == {"items": visible}
    assert client.get("/api/v1/kb/libraries").json() == {"items": [
        {"id": row["id"], "name": row["name"], "icon": row["icon"], "files": row["count"]} for row in visible]}


@pytest.mark.parametrize("mask", [True, False])
def test_partner_space_and_write_boundaries(instance, mask):
    yaml = pytest.importorskip("yaml")
    client = login(instance)
    path = instance[1] / "roles.yaml"
    roles = yaml.safe_load(path.read_text())
    roles["roles"]["partner"]["mask"] = mask
    path.write_text(yaml.safe_dump(roles, allow_unicode=True), encoding="utf-8")
    assert client.get(DETAIL).json()["item"] == {**(MASKED if mask else ROW), "history": [] if mask else CHANGES}
    assert client.get("/api/v1/kb/spaces").json()["items"] == SPACES[:1]
    assert client.get("/api/v1/kb/docs").json() == {"hits": [{"space": "policy"}], "total": 1}
    for result in (client.get("/api/v1/kb/docs?space=enterprise"), client.patch(DETAIL, json={"name": "改名"})):
        assert result.status_code == 403
        assert result.json()["error"]["code"] == "FORBIDDEN"

"""#17 的清单门、真实 core HTTP 路由及对话桥契约。"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys

import pytest
from fastapi import Request

from conftest import ROOT
from haiknow_core.main import current_user
from haiknow_core.manifest_ext import validate_extensions
from haiknow_core.stability import FAILURE_THRESHOLD
from jkq.apps_bridge import install

APP = "tool-sample"
BASE = f"/api/v1/apps/{APP}/tools"
ARGS = {"project": "sample-project", "title": "一条虚构记录"}
FIELDS = ["tools", "starters", "chatCards", "deepLink", "dataClass", "accepts", "intents", "routes"]


def manifest(app_id=APP):
    template = (ROOT / "apps/_template/app.json").read_text(encoding="utf-8")
    return json.loads(template.replace("__APP_ID__", app_id).replace("__OWNER__", "fixture-owner"))


class MemoryReviewSink:
    def __init__(self):
        self.items = {}

    def create_tool_review(self, app, tool, args, requester):
        review_id = f"test-review-{len(self.items) + 1}"
        self.items[review_id] = dict(
            id=review_id, app=app, tool=tool, args=copy.deepcopy(args), requester=requester.id, status="pending",
        )
        return review_id

    def get_review(self, id):
        return self.items.get(id)


@pytest.fixture
def api(make_client, isolated_platform):
    config, apps = isolated_platform
    users_path = config / "users.yaml"
    users = json.loads(users_path.read_text(encoding="utf-8"))
    users["users"].append({
        "id": "partner", "name": "样例协作者", "roles": ["partner"], "projects": ["sample-project"],
    })
    users_path.write_text(json.dumps(users), encoding="utf-8")
    for app_id in (APP, "staff-tools"):
        target = apps / app_id
        shutil.copytree(ROOT / "apps/_template", target, ignore=shutil.ignore_patterns("__pycache__"))
        data = manifest(app_id)
        if app_id == APP:
            data["defaultRoles"]["partner"] = ["view"]
            data["tools"].append({
                "name": f"{APP}.get_record", "description": "读取指定版本的记录",
                "write": False, "input": {"rid": "string", "version": "integer?"},
                "endpoint": f"GET /api/apps/{APP}/records/{{rid}}",
            })
        (target / "app.json").write_text(json.dumps(data), encoding="utf-8")
    embed = apps / "sample-embed"
    embed.mkdir()
    data = manifest(embed.name)
    data.update(
        kind="embed", url="https://embed.example.invalid/sample", tools=[],
        defaultRoles={"partner": ["view"]}, privateMetadata={"backend": "示例内部字段"},
    )
    (embed / "app.json").write_text(json.dumps(data), encoding="utf-8")
    client = make_client()
    reviews = MemoryReviewSink()

    def list_skills(user):
        return [{"id": "sample-skill"}] if "sampleoperator" in user.roles else []

    def preflight_update(user, args):
        client.app.state.platform.data.get_record(user, APP, args["rid"])

    bridge = install(
        client.app, current_user, review_sink=reviews, list_skills=list_skills,
        write_preflights={f"{APP}.update_record": preflight_update},
    )

    @client.app.post("/api/v1/chat-fixture/{app}/{tool}")
    async def chat(request: Request, app: str, tool: str, body: dict):
        return await bridge.call_from_chat(request, app, tool, body["args"])

    return client, reviews


def login(client, user):
    assert client.post("/api/auth/login", json={"user_id": user}).status_code == 200


def tool_audit(client):
    return [
        row for row in client.app.state.platform.store.audit_list()
        if row["action"] == "tool.call"
    ]


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    return error


def test_catalog_and_details_use_real_partner_grants(api):
    client, _ = api
    for path in ("/api/v1/apps", f"/api/v1/apps/{APP}", "/api/v1/tools"):
        assert_error(client.get(path), 401, "UNAUTHENTICATED")
    login(client, "partner")
    catalog = client.get("/api/v1/apps").json()
    assert set(catalog) == {"items", "skills"}
    assert {entry["id"] for entry in catalog["items"]} == {APP, "sample-embed"}
    assert catalog["skills"] == []
    assert client.get(f"/api/v1/apps/{APP}").json() == next(entry for entry in catalog["items"] if entry["id"] == APP)
    assert client.get("/api/v1/tools").json()["items"] == [
        {"name": f"{APP}.list_records", "app": APP, "write": False},
        {"name": f"{APP}.create_record", "app": APP, "write": True},
        {"name": f"{APP}.get_record", "app": APP, "write": False},
    ]
    assert_error(client.get("/api/v1/apps/unknown"), 404, "NOT_FOUND")
    error = assert_error(client.get("/api/v1/apps/staff-tools"), 403, "FORBIDDEN")
    assert error["details"] == {"app": "staff-tools", "need": "view"}

    login(client, "sampleoperator")
    catalog = client.get("/api/v1/apps").json()
    assert {"staff-tools", APP}.issubset(entry["id"] for entry in catalog["items"])
    assert catalog["skills"] == [{"id": "sample-skill"}]
    assert any(tool["app"] == "staff-tools" for tool in client.get("/api/v1/tools").json()["items"])


def test_read_tool_calls_same_business_route_and_audits_once_per_source(api):
    client, reviews = api
    login(client, "sampleoperator")
    direct = client.post(f"/api/apps/{APP}/records", json=ARGS)
    assert direct.status_code == 201
    login(client, "partner")
    direct = client.get(f"/api/apps/{APP}/records", params={"project": "sample-project"})
    assert direct.status_code == 200 and len(direct.json()["items"]) == 1
    for path in (f"{BASE}/list_records", f"/api/v1/chat-fixture/{APP}/{APP}.list_records"):
        result = client.post(path, json={"args": {"project": "sample-project"}})
        assert result.status_code == 200, result.text
        assert result.json() == {"tool": f"{APP}.list_records", "result": direct.json()}
    rows = tool_audit(client)
    assert len(rows) == 2
    assert {row["detail"]["via"] for row in rows} == {"ui", "chat"}
    for row in rows:
        assert (row["user"], row["app"]) == ("partner", APP)
        assert row["detail"]["outcome"] == "ok"
        assert row["detail"]["need"] == "view"
        assert row["detail"]["tool"] == f"{APP}.list_records"
    assert reviews.items == {}


def test_chat_write_creates_one_pending_review_without_touching_business_records(api):
    client, reviews = api
    login(client, "sampleoperator")
    ui = client.post(f"{BASE}/create_record", json={"args": ARGS})
    assert ui.status_code == 200, ui.text
    assert ui.json()["result"]["data"]["title"] == ARGS["title"]
    records_path = f"/api/apps/{APP}/records"
    before = client.get(records_path).json()
    assert len(before["items"]) == 1 and reviews.items == {}
    body = {**ARGS, "title": "待确认的另一条记录"}
    chat = client.post(f"/api/v1/chat-fixture/{APP}/create_record", json={"args": body})
    assert chat.status_code == 200, chat.text
    result = chat.json()["result"]
    assert result == {"reviewId": "test-review-1", "status": "pending", "message": "待确认"}
    assert len(reviews.items) == 1
    assert reviews.get_review(result["reviewId"]) == {
        "id": result["reviewId"], "app": APP, "tool": f"{APP}.create_record",
        "args": body, "requester": "sampleoperator", "status": "pending",
    }
    assert client.get(records_path).json() == before
    rows = tool_audit(client)
    assert len(rows) == 2
    assert {(row["detail"]["via"], row["detail"]["need"], row["detail"]["outcome"]) for row in rows} == {
        ("chat", "operate", "pending"), ("ui", "operate", "ok"),
    }


@pytest.mark.parametrize(("args", "status", "code"), [
    ({"project": "limited-project", "title": "样例"}, 404, "NOT_FOUND"),
    ({"project": "sample-project"}, 422, "invalid_request"),
    ({"project": "sample-project", "title": ""}, 422, "invalid_request"),
    ({"project": "sample-project", "title": "样例", "content": "字" * 2001}, 422, "invalid_request"),
])
def test_write_tool_checks_business_input_and_scope_before_review(api, args, status, code):
    client, reviews = api
    login(client, "sampleoperator")
    for path in (f"{BASE}/create_record", f"/api/v1/chat-fixture/{APP}/create_record"):
        assert_error(client.post(path, json={"args": args}), status, code)
    assert reviews.items == {}
    assert client.get(f"/api/apps/{APP}/records").json()["items"] == []
    rows = tool_audit(client)
    assert {(row["detail"]["via"], row["detail"]["outcome"]) for row in rows} == {("ui", code), ("chat", code)}
    assert len(rows) == 2


def test_chat_write_requires_registered_preflight_and_checks_target_record(api):
    client, reviews = api
    platform = client.app.state.platform
    platform.apps[APP].manifest["tools"].append({
        "name": f"{APP}.update_record", "description": "修改样例记录",
        "write": True, "input": {"rid": "string", "baseVersion": "integer", "title": "string"},
        "endpoint": f"PUT /api/apps/{APP}/records/{{rid}}",
    })
    login(client, "sampleadmin")
    target = client.post(f"/api/apps/{APP}/records", json={**ARGS, "project": "limited-project"}).json()
    login(client, "sampleoperator")
    args = {"rid": target["id"], "baseVersion": 1, "title": "修改样例"}
    chat = f"/api/v1/chat-fixture/{APP}/update_record"
    for path in (f"{BASE}/update_record", chat):
        assert_error(client.post(path, json={"args": args}), 404, "NOT_FOUND")
    client.app.state.apps_bridge.write_preflights.clear()
    assert_error(client.post(chat, json={"args": args}), 500, "internal_error")
    assert reviews.items == {}
    login(client, "sampleadmin")
    assert client.get(f"/api/apps/{APP}/records/{target['id']}").json() == target
    assert {(row["detail"]["via"], row["detail"]["outcome"]) for row in tool_audit(client)} == {
        ("ui", "NOT_FOUND"), ("chat", "NOT_FOUND"), ("chat", "internal_error"),
    }


@pytest.mark.parametrize("unavailable", ["disabled", "circuit"])
def test_unavailable_app_checks_permissions_before_availability_and_audits(api, unavailable):
    client, reviews = api
    entry = client.app.state.platform.apps[APP]
    if unavailable == "disabled":
        login(client, "sampleadmin")
        assert client.put(f"/api/v1/admin/apps/{APP}", json={"enabled": False}).status_code == 200
        client.cookies.clear()
    else:

        for _ in range(FAILURE_THRESHOLD):
            entry.circuit.record(True)

    detail = f"/api/v1/apps/{APP}"
    paths = (f"{BASE}/create_record", f"/api/v1/chat-fixture/{APP}/create_record")
    assert_error(client.get(detail), 401, "UNAUTHENTICATED")
    for path in paths:
        assert_error(client.post(path, json={"args": ARGS}), 401, "UNAUTHENTICATED")

    login(client, "sampleoutsider")
    assert_error(client.get(detail), 403, "FORBIDDEN")
    login(client, "partner")
    for path in paths:
        assert_error(client.post(path, json={"args": ARGS}), 403, "FORBIDDEN")
    assert_error(client.get(f"{detail}/records"), 503, "app_unavailable")
    assert_error(client.get(f"/api/apps/{APP}/records"), 503, "app_unavailable")

    login(client, "sampleoperator")
    detail_response = client.get(detail)
    assert_error(detail_response, 503, "app_unavailable")
    if unavailable == "circuit":
        assert int(detail_response.headers["retry-after"]) > 0
    for path in paths:
        assert_error(client.post(path, json={"args": ARGS}), 503, "app_unavailable")

    rows = tool_audit(client)
    assert len(rows) == 4
    assert {(row["user"], row["detail"]["via"], row["detail"]["outcome"]) for row in rows} == {
        ("partner", "ui", "FORBIDDEN"), ("partner", "chat", "FORBIDDEN"),
        ("sampleoperator", "ui", "app_unavailable"), ("sampleoperator", "chat", "app_unavailable"),
    }
    assert reviews.items == {}


def test_catalog_and_detail_only_show_embed_url_to_platform_admin(api):
    client, _ = api
    for user, url in (("partner", None), ("sampleadmin", "https://embed.example.invalid/sample")):
        login(client, user)
        legacy = next(item for item in client.get("/api/apps").json()["apps"] if item["id"] == "sample-embed")
        summary = next(item for item in client.get("/api/v1/apps").json()["items"] if item["id"] == "sample-embed")
        detail = client.get("/api/v1/apps/sample-embed").json()
        assert detail == summary
        assert detail["url"] == legacy["url"] == url
        assert "privateMetadata" not in detail and "defaultRoles" not in detail
        assert detail["deepLink"] == {"params": ["project", "recordId"]}


@pytest.mark.parametrize(("app", "tool", "need"), [
    (APP, "create_record", "operate"),
    ("staff-tools", "list_records", "view"),
])
def test_ui_and_chat_deny_the_same_permission_and_audit_once(api, app, tool, need):
    client, reviews = api
    login(client, "partner")
    for path in (f"/api/v1/apps/{app}/tools/{tool}", f"/api/v1/chat-fixture/{app}/{tool}"):
        error = assert_error(client.post(path, json={"args": ARGS}), 403, "FORBIDDEN")
        assert error["details"] == {"app": app, "need": need}
    assert reviews.items == {}
    rows = tool_audit(client)
    assert len(rows) == 2
    for row in rows:
        assert row["detail"] == {
            "via": row["detail"]["via"], "tool": f"{app}.{tool}", "need": need, "outcome": "FORBIDDEN",
        }
    assert {row["detail"]["via"] for row in rows} == {"ui", "chat"}


def test_unknown_tools_and_invalid_request_do_not_execute(api):
    client, reviews = api
    login(client, "sampleoperator")
    for target in ("unknown", "staff-tools.list_records"):
        assert_error(client.post(f"{BASE}/{target}", json={"args": {}}), 404, "TOOL_NOT_FOUND")
    assert_error(client.post("/api/v1/apps/unknown/tools/unknown", json={"args": {}}), 404, "NOT_FOUND")
    for args in ([], None, "sample"):
        assert_error(client.post(f"{BASE}/list_records", json={"args": args}), 422, "invalid_request")
    assert reviews.items == {}


def test_path_args_are_bound_to_current_app_and_used_by_real_router(api):
    client, _ = api
    login(client, "sampleoperator")
    record = client.post(f"/api/apps/{APP}/records", json=ARGS).json()
    response = client.post(f"{BASE}/get_record", json={"args": {"rid": record["id"], "version": 1}})
    assert response.status_code == 200 and response.json()["result"]["id"] == record["id"]
    for value in ("..", "../records", "%2f", None):
        assert_error(
            client.post(f"{BASE}/get_record", json={"args": {"rid": value}}), 422, "invalid_request",
        )


def test_missing_review_integration_fails_without_business_write(api):
    client, reviews = api
    client.app.state.apps_bridge.review_sink = None
    login(client, "sampleoperator")
    response = client.post(f"/api/v1/chat-fixture/{APP}/create_record", json={"args": ARGS})
    assert_error(response, 500, "internal_error")
    assert reviews.items == {}
    assert client.get(f"/api/apps/{APP}/records").json()["items"] == []
    assert [row["detail"]["outcome"] for row in tool_audit(client)] == ["internal_error"]


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("remove", [True, False])
def test_manifest_gate_detects_each_invalid_extension(tmp_path, monkeypatch, field, remove):
    from scripts import check

    monkeypatch.setattr(check, "ROOT", tmp_path)
    path = tmp_path / "apps" / "_template" / "app.json"
    path.parent.mkdir(parents=True)
    data = manifest()
    if remove:
        data.pop(field)
    else:
        data[field] = 42
    path.write_text(json.dumps(data), encoding="utf-8")
    (path.parent / "web").mkdir()
    (path.parent / "web/index.js").touch()
    monkeypatch.setattr(sys, "argv", ["check.py", "--only", "manifest"])
    assert check.main() == 1
    report = check.Report()
    check.check_manifest(report, "_template")
    assert len(report.errors) == 1
    assert f"应用 {APP} " in report.errors[0] and field in report.errors[0]


@pytest.mark.parametrize(("field", "key"), [
    ("tools", "name"), ("tools", "description"), ("tools", "write"), ("tools", "input"), ("tools", "endpoint"),
    ("accepts", "kind"), ("accepts", "ext"), ("accepts", "match"),
    ("intents", "id"), ("intents", "action"), ("intents", "plan"),
])
def test_manifest_requires_nested_fields(field, key):
    data = manifest()
    data[field][0].pop(key)
    assert validate_extensions(data) == [f"缺少字段 {field}[0].{key}"]


@pytest.mark.parametrize("endpoint", [
    "GET https://example.invalid/", "GET /api/apps/staff-tools/records",
    f"GET /api/apps/{APP}/../records", f"GET /api/apps/{APP}/%2e%2e/records",
    f"GET /api/apps/{APP}/records?q=x", f"DELETE /api/apps/{APP}/records",
])
def test_manifest_rejects_unscoped_and_mismatched_tool_endpoints(endpoint):
    data = manifest()
    data["tools"][0]["endpoint"] = endpoint
    assert "tools[0].endpoint" in validate_extensions(data)[0]


@pytest.mark.parametrize("target", ["read-tool", "other-endpoint", "invalid-value"])
def test_manifest_restricts_template_preflight(target):
    data = manifest()
    read, write = data["tools"]
    if target == "read-tool":
        read["preflight"] = "record.create"
        field = "tools[0].preflight"
    else:
        field = "tools[1].preflight"
        if target == "other-endpoint":
            write["endpoint"] += "/other"
        else:
            write["preflight"] = {}
    assert field in validate_extensions(data)[0]


def test_template_and_generated_app_pass_manifest_cli(tmp_path):
    assert not validate_extensions(manifest(), required=True)
    assert validate_extensions({"id": "legacy-v1"}) == []
    (tmp_path / "CODEOWNERS").touch()
    shutil.copytree(ROOT / "apps/_template", tmp_path / "apps/_template")
    subprocess.run([
        sys.executable, str(ROOT / "scripts/new_app.py"), APP, "样例应用",
        "--owner", "fixture-owner", "--root", str(tmp_path),
    ], check=True, capture_output=True, text=True)
    data = json.loads((tmp_path / "apps" / APP / "app.json").read_text(encoding="utf-8"))
    assert data["tools"][0]["name"] == f"{APP}.list_records"
    assert validate_extensions(data, required=True) == []
    result = subprocess.run(
        [sys.executable, "scripts/check.py", "--only", "manifest", "--app", "_template"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    assert "全部通过。" in result.stdout

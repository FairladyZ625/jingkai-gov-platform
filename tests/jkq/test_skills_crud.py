"""技能白名单与 §3.7 真实 HTTP、SQLite 回归。"""
import json

import pytest

from jkq.skills.spec import SkillError, validate_spec

ROOT = "/api/v1/skills"
SPEC = {"triggers": ["办理"], "inputs": [{"key": "ent"}],
        "steps": [{"type": "tool", "tool": "policy.match"}, {"type": "kb"},
                  {"type": "computer"}, {"type": "model"}]}


@pytest.mark.parametrize("spec,code", [
    ({"tools": ["other"]}, "SKILL_TOOL_NOT_ALLOWED"),
    ({"steps": [{"type": "tool", "tool": "other"}]}, "SKILL_TOOL_NOT_ALLOWED"),
    ({"steps": [{"type": "model", "tool": "other"}]}, "SKILL_TOOL_NOT_ALLOWED"),
    ({"steps": [{"type": "model"}] * 6}, "INVALID_REQUEST"),
    ({"steps": [{"type": "unknown"}]}, "INVALID_REQUEST"),
    ({"inputs": "文本"}, "INVALID_REQUEST"),
])
def test_invalid_spec(spec, code):
    with pytest.raises(SkillError) as error:
        validate_spec(spec)
    assert error.value.status == 400 and error.value.error["code"] == code


def test_valid_spec():
    normalized = validate_spec(SPEC)
    assert all(normalized[key] == value for key, value in SPEC.items())
    assert validate_spec({}) == {"cat": "知识", "model": "auto", "prompt": "", "triggers": [],
                                 "inputs": [], "steps": [], "kb": [], "output": {"format": "要点", "title": ""}}
    assert len(validate_spec({"steps": [{"type": "model"}] * 5})["steps"]) == 5


@pytest.fixture
def api(request):
    pytest.importorskip("fastapi")
    from fastapi import HTTPException, Request
    from jkq.skills.api import install

    config, _ = request.getfixturevalue("isolated_platform")
    roles = config / "roles.yaml"
    data = json.loads(roles.read_text())
    for role in ("sampleoperator", "sampleextra", "sampleobserver"):
        actions = ["view"] if role == "sampleobserver" else ["view", "operate"]
        data["roles"][role] = {"grants": {"skills": actions}}
    roles.write_text(json.dumps(data))
    client = request.getfixturevalue("make_client")()

    def identity(request: Request):
        user = client.app.state.platform.rbac.users.get(request.headers.get("x-test-user"))
        if not user:
            raise HTTPException(401, "请先登录")
        return user

    install(client.app, identity)
    return client


def call(api, method, path="", user="sampleoperator", **kw):
    return api.request(method, ROOT + path, headers={"x-test-user": user}, **kw)


def create(api):
    response = call(api, "POST", json={"name": "政策查询", "spec": SPEC})
    assert response.status_code == 200, response.text
    return response.json()["item"]


def publish(api, item, scope, perm="use"):
    # #44 的写入端尚未注册，夹具只通过同一个持久化入口准备已发布记录。
    skills = api.app.state.skills
    user = skills.platform.rbac.users[item["authorId"]]
    doc = skills.load(user, item["id"], edit=True)
    skills.save(user, doc, {"status": "published", "share": {
        "scope": scope, "people": ["sampleextra"], "perm": perm}})


def error(response, status, code):
    assert response.status_code == status, response.text
    value = response.json()["error"]
    assert value["code"] == code and value["message"] and isinstance(value["details"], dict)


def test_visibility_and_edit(api):
    item = create(api)
    path = "/" + item["id"]
    error(call(api, "GET", user=""), 401, "UNAUTHENTICATED")
    error(call(api, "GET", "/missing"), 404, "NOT_FOUND")
    for q in ("", "?mine=true", "?review=true"):
        assert call(api, "GET", q, user="sampleextra").json()["items"] == []
    error(call(api, "GET", path, user="sampleextra"), 403, "FORBIDDEN")
    publish(api, item, "people")
    detail = call(api, "GET", path, user="sampleextra").json()
    assert detail.keys() == {"item", "runs"} and detail["runs"] == []
    assert detail["item"]["canEdit"] is False
    error(call(api, "PATCH", path, user="sampleextra", json={"name": "无权修改"}), 403, "FORBIDDEN")
    error(call(api, "POST", path + "/restore", user="sampleextra", json={"v": item["version"]}), 403, "FORBIDDEN")
    error(call(api, "DELETE", path, user="sampleextra"), 403, "FORBIDDEN")
    assert call(api, "GET", user="sampleobserver").json()["items"] == []
    publish(api, item, "zone", "edit")
    error(call(api, "PATCH", path, user="sampleobserver", json={"name": "只读"}), 403, "FORBIDDEN")
    assert call(api, "PATCH", path, user="sampleextra", json={"name": "共享编辑"}).status_code == 200
    error(call(api, "DELETE", path, user="sampleextra"), 403, "FORBIDDEN")
    assert call(api, "DELETE", path, user="sampleadmin").status_code == 200
    error(call(api, "POST", path + "/restore-deleted", user="sampleextra"), 403, "FORBIDDEN")
    assert call(api, "POST", path + "/restore-deleted", user="sampleadmin").status_code == 200


def test_version_fork_restore_and_undo(api):
    item = create(api)
    path = "/" + item["id"]
    publish(api, item, "people")
    edited = call(api, "PATCH", path, json={"name": "新版", "spec": {"steps": []}}).json()["item"]
    assert edited["version"] != item["version"]
    fork = call(api, "POST", path + "/fork", user="sampleextra").json()["item"]
    assert fork["forkOf"] == {"id": item["id"], "version": edited["version"]}
    assert fork["id"] != item["id"] and fork["authorId"] == "sampleextra"
    assert fork["status"] == "draft" and fork["share"]["scope"] == "private"
    error(call(api, "POST", path + "/restore", json={"v": "9.9.9"}), 404, "NOT_FOUND")
    restored = call(api, "POST", path + "/restore", json={"v": item["version"]}).json()["item"]
    assert len({restored["version"], edited["version"], item["version"]}) == 3
    for key in ("name", "summary", "base", "icon", "spec"):
        assert restored[key] == item[key] == restored["versions"][0][key]
    assert restored["versions"][1]["name"] == "新版"
    assert call(api, "DELETE", path).json()["ok"]
    assert call(api, "GET").json()["items"] == []
    error(call(api, "GET", path), 404, "NOT_FOUND")
    error(call(api, "POST", path + "/restore-deleted", user="sampleextra"), 403, "FORBIDDEN")
    undo = call(api, "POST", path + "/restore-deleted", json={"item": {"authorId": "other"}})
    assert undo.json()["item"] == restored
    assert call(api, "GET").json()["items"][0]["id"] == item["id"]


def test_editor_options_and_rejected_save(api):
    meta = call(api, "GET", "/meta/options").json()
    assert {"tools", "models", "spaces", "computerTasks", "users", "myDept"} <= meta.keys()
    assert SPEC["steps"][0]["tool"] in {tool["id"] for tool in meta["tools"]}
    body = {"name": "不合规", "spec": {"steps": [{"type": "tool", "tool": "unknown"}]}}
    error(call(api, "POST", json=body), 400, "SKILL_TOOL_NOT_ALLOWED")
    item = create(api)
    path = "/" + item["id"]
    error(call(api, "PATCH", path, json=body), 400, "SKILL_TOOL_NOT_ALLOWED")
    assert call(api, "GET", path).json()["item"] == item
    assert len(call(api, "GET").json()["items"]) == 1


def test_department_change_and_private_history(api):
    item = create(api)
    path = "/" + item["id"]
    platform = api.app.state.platform
    store = platform.store
    with store._lock, store._db as db:
        db.execute("INSERT INTO departments (id, name) VALUES ('service', '服务处')")
        db.executemany("INSERT INTO user_departments VALUES (?, 'service')",
                       [(item["authorId"],), ("sampleextra",)])
    publish(api, item, "dept", "edit")
    assert call(api, "GET", path, user="sampleextra").json()["item"]["canEdit"]
    error(call(api, "GET", path, user="sampleobserver"), 403, "FORBIDDEN")
    with store._lock, store._db as db:
        db.execute("DELETE FROM user_departments WHERE user_id='sampleextra'")
    error(call(api, "GET", path, user="sampleextra"), 403, "FORBIDDEN")
    assert call(api, "GET", user="sampleextra").json()["items"] == []

    from jkq.skills.storage import Skills
    reopened = Skills(platform)
    author = platform.rbac.users[item["authorId"]]
    assert reopened.load(author, item["id"])["data"]["spec"] == validate_spec(SPEC)
    assert platform.data.list_records(platform.rbac.users["sampleadmin"], "sample-app")["items"] == []
    with store._lock:
        assert store._db.execute("SELECT id FROM v1_records WHERE id=?", (item["id"],)).fetchone() is None


@pytest.mark.parametrize("spec", [
    {"inputs": [{}]}, {"inputs": [{"key": ""}]}, {"inputs": [{"key": "two words"}]},
    {"inputs": [{"key": "field.1"}]}, {"inputs": [{"key": "f1"}, {"key": "f1"}]},
    {"kb": None}, {"kb": [1]}, {"output": None}, {"output": {"format": []}},
    {"output": {"title": 1}}, {"model": False},
])
def test_invalid_editor_fields(spec):
    with pytest.raises(SkillError) as error:
        validate_spec(spec)
    assert error.value.status == 400 and error.value.error["code"] == "INVALID_REQUEST"


def test_rejected_content_never_creates_record_or_revision(api):
    item = create(api)
    path = "/" + item["id"]
    for body in ('{"spec":{"extension":[{"value":1e400}]}}', '{"spec":{"inputs":[{"key":"two words"}]}}'):
        for method, target in (("POST", ""), ("PATCH", path)):
            response = api.request(method, ROOT + target, content=body, headers={
                "content-type": "application/json", "x-test-user": "sampleoperator"})
            error(response, 400, "INVALID_REQUEST")
    assert call(api, "GET", path).json()["item"] == item
    assert [row["id"] for row in call(api, "GET").json()["items"]] == [item["id"]]


def test_minimal_editor_spec_across_versions(api):
    item = call(api, "POST", json={"spec": {}}).json()["item"]
    path = "/" + item["id"]
    edited = call(api, "PATCH", path, json={"spec": {"kb": ["政策"], "output": {"format": "表格"}}}).json()["item"]
    fork = call(api, "POST", path + "/fork").json()["item"]
    restored = call(api, "POST", path + "/restore", json={"v": item["version"]}).json()["item"]
    for entry in (item, restored, edited, fork):
        assert isinstance(entry["spec"]["kb"], list)
        assert isinstance(entry["spec"]["output"]["title"], str)
    assert fork["spec"] == edited["spec"] and edited["spec"]["output"]["format"] == "表格"
    assert restored["spec"] == item["spec"] and item["spec"]["output"]["format"] == "要点"


def test_platform_audit_lists_skill_actions(api):
    item = create(api)
    path = "/" + item["id"]
    assert call(api, "PATCH", path, json={"name": "新版"}).status_code == 200
    assert call(api, "DELETE", path).status_code == 200
    assert call(api, "POST", path + "/restore-deleted").status_code == 200
    for user, status in (("sampleoperator", 403), ("sampleadmin", 200)):
        assert api.post("/api/auth/login", json={"user_id": user}).status_code == 200
        response = api.get("/api/audit", params={"app_id": "skills"})
        assert response.status_code == status
    events = [row for row in response.json()["items"] if row["detail"].get("recordId") == item["id"]]
    assert [row["action"] for row in reversed(events)] == [
        "skill.create", "skill.update", "skill.delete", "skill.restore_deleted"]
    assert all(row["user"] == "sampleoperator" for row in events)


def test_audit_failure_rolls_back_revision(api):
    import sqlite3

    item = create(api)
    store = api.app.state.platform.store
    with store._lock, store._db as db:
        db.execute("""CREATE TRIGGER reject_skill_audit BEFORE INSERT ON audit
                      WHEN NEW.action='skill.delete' BEGIN
                      SELECT RAISE(ABORT, '测试审计不可写'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="测试审计不可写"):
        call(api, "DELETE", "/" + item["id"])
    assert call(api, "GET", "/" + item["id"]).json()["item"] == item
    skills_store = api.app.state.skills.store
    assert len(skills_store.audit_list("skills")) == 1

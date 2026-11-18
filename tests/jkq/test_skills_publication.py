"""#44 经真实 HTTP 路由、core 审签和 SQLite 事务验证分享边界。"""
import json

import pytest

ROOT = "/api/v1/skills"


@pytest.fixture
def api(request):
    pytest.importorskip("fastapi")
    from fastapi import Request
    from jkq import reviews_api
    from jkq.skills import api as crud, publication

    config, _ = request.getfixturevalue("isolated_platform")
    roles = config / "roles.yaml"
    grants = json.loads(roles.read_text())
    for role, actions in {"sampleoperator": ["view", "operate"], "sampleextra": ["view", "operate"],
                          "sampleobserver": ["view"], "leader": ["view", "approve"]}.items():
        grants["roles"][role] = {"grants": {"skills": actions}}
    roles.write_text(json.dumps(grants))
    people = config / "users.yaml"
    users = json.loads(people.read_text())
    next(u for u in users["users"] if u["id"] == "samplereviewer")["roles"] = ["leader"]
    people.write_text(json.dumps(users))
    client = request.getfixturevalue("make_client")()

    def identity(request: Request):
        return client.app.state.platform.rbac.users[request.headers["x-test-user"]]

    reviews_api.install(client.app, identity)
    crud.install(client.app, identity)
    publication.install(client.app, identity)
    store = client.app.state.platform.store
    with store._lock, store._db as db:
        db.execute("INSERT INTO departments (id,name) VALUES ('same','同部门')")
        db.executemany("INSERT INTO user_departments VALUES (?, 'same')", [("sampleoperator",), ("sampleextra",)])
    return client


def call(api, method, path="", user="sampleoperator", body=None):
    return api.request(method, ROOT + path, headers={"x-test-user": user}, json=body)


def create(api, owner="sampleoperator"):
    return "/" + call(api, "POST", user=owner, body={"name": "共享技能"}).json()["item"]["id"]


def listed(api, user, path, query=""):
    return path[1:] in [item["id"] for item in call(api, "GET", query, user).json()["items"]]


def error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize("scope,visible", [("private", False), ("dept", True), ("people", True)])
def test_immediate_scope(api, scope, visible):
    path = create(api)
    share = {"scope": scope, "people": ["sampleextra"], "perm": "use"}
    response = call(api, "POST", path + "/publish", body={"share": share}).json()
    assert response["review"] is None and response["item"]["status"] == "published"
    assert listed(api, "sampleextra", path) == visible
    assert not listed(api, "sampleobserver", path)
    error(call(api, "PATCH", path, "sampleextra", {"name": "修改"}), 403, "FORBIDDEN")
    call(api, "POST", path + "/share", body={"scope": "people", "people": ["sampleextra"], "perm": "edit"})
    assert call(api, "PATCH", path, "sampleextra", {"name": "可修改"}).status_code == 200
    error(call(api, "POST", path + "/share", "sampleextra", {"scope": "zone"}), 403, "FORBIDDEN")


@pytest.mark.parametrize("reviewer,choice", [("sampleadmin", "approve"), ("samplereviewer", "reject")])
def test_review(api, reviewer, choice):
    path = create(api)
    result = call(api, "POST", path + "/publish", body={"share": {"scope": "zone"}}).json()
    error(call(api, "POST", path + "/review", body={"decision": "approve"}), 409, "SELF_REVIEW")
    review = result["review"]
    assert review["type"] == "skill" and review["ref"] == path[1:]
    for user in ("sampleextra", "sampleadmin", "samplereviewer"):
        assert not listed(api, user, path)
    assert listed(api, reviewer, path, "?review=true")
    assert not listed(api, "sampleextra", path, "?review=true")
    queue = api.get("/api/v1/reviews", headers={"x-test-user": reviewer}).json()["items"]
    assert [entry["id"] for entry in queue] == [review["id"]]
    error(call(api, "POST", path + "/review", "sampleextra", {"decision": choice}), 403, "FORBIDDEN")
    for rejection in ({"decision": "reject"}, {"decision": "reject", "reason": " "}):
        error(call(api, "POST", path + "/review", reviewer, rejection), 400, "INVALID_REQUEST")
    if choice == "approve":
        resp = api.post("/api/v1/reviews/" + review["id"] + "/decisions", headers={"x-test-user": reviewer},
                        json={"decision": choice, "version": review["version"]})
    else:
        resp = call(api, "POST", path + "/review", reviewer, {"decision": choice, "reason": "需补充"})
    assert resp.status_code == 200, resp.text
    assert listed(api, "sampleextra", path) == (choice == "approve")
    assert api.get("/api/v1/reviews", headers={"x-test-user": reviewer}).json()["items"] == []


def test_self_and_stale(api):
    path = create(api, "sampleadmin")
    call(api, "POST", path + "/share", "sampleadmin", {"scope": "zone"})
    error(call(api, "POST", path + "/review", "sampleadmin", {"decision": "approve"}), 409, "SELF_REVIEW")
    call(api, "PATCH", path, "sampleadmin", {"name": "新版本"})
    error(call(api, "POST", path + "/review", "samplereviewer", {"decision": "approve"}), 409, "STALE_VERSION")


def test_latest_vote(api):
    path = create(api)
    call(api, "POST", path + "/publish", body={"share": {"scope": "people", "people": ["sampleobserver"]}})
    error(call(api, "POST", path + "/rate", "sampleextra", {"useful": True}), 403, "FORBIDDEN")
    error(call(api, "POST", path + "/rate", "sampleobserver", {"useful": 1}), 400, "INVALID_REQUEST")
    for user, vote, count, rate in (("sampleobserver", True, 1, 100), ("sampleobserver", False, 1, 0),
                                    ("sampleoperator", True, 2, 50)):
        response = call(api, "POST", path + "/rate", user, {"useful": vote})
        assert response.status_code == 200, response.text
        item = call(api, "GET", user=user).json()["items"][0]
        assert (item["ratingN"], item["usefulRate"]) == (count, rate)


@pytest.mark.parametrize("share", [{"scope": "outside"}, {"scope": "people", "people": []},
                                    {"scope": "people", "people": ["missing"]}, {"perm": "admin"}])
def test_invalid_share_preserves_draft(api, share):
    path = create(api)
    error(call(api, "POST", path + "/publish", body={"share": share}), 400, "INVALID_REQUEST")
    assert call(api, "GET", path).json()["item"]["status"] == "draft"


def test_failed_review_creation_rolls_back_publication(api):
    import sqlite3

    path = create(api)
    store = api.app.state.skills.store
    with store._lock, store._db as db:
        db.execute("""CREATE TRIGGER reject_review BEFORE INSERT ON v1_reviews
                      BEGIN SELECT RAISE(ABORT, '审核写入失败'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="审核写入失败"):
        call(api, "POST", path + "/publish", body={"share": {"scope": "zone"}})
    assert call(api, "GET", path).json()["item"]["status"] == "draft"

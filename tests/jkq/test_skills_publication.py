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


def publish_zone(api, path, perm="use"):
    response = call(api, "POST", path + "/publish", body={"share": {"scope": "zone", "perm": perm}})
    assert response.status_code == 200, response.text
    return response.json()["review"]


def decide(api, path, review, choice="approve", **extra):
    return call(api, "POST", path + "/review", "samplereviewer",
                {"decision": choice, "reviewId": review.get("reviewId", review["id"]),
                 "version": review["version"], **extra})


def review_queue(api, endpoint=ROOT, user="samplereviewer"):
    params = {"review": "true"} if endpoint == ROOT else {}
    response = api.get(endpoint, params=params, headers={"x-test-user": user})
    assert response.status_code == 200, response.text
    return response.json()["items"]


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
        resp = decide(api, path, review, choice, reason="需补充")
    assert resp.status_code == 200, resp.text
    assert listed(api, "sampleextra", path) == (choice == "approve")
    assert api.get("/api/v1/reviews", headers={"x-test-user": reviewer}).json()["items"] == []


def test_self_and_stale(api):
    path = create(api, "sampleadmin")
    review = call(api, "POST", path + "/share", "sampleadmin", {"scope": "zone"}).json()["review"]
    error(call(api, "POST", path + "/review", "sampleadmin", {
        "decision": "approve", "reviewId": review["reviewId"], "version": review["version"],
    }), 409, "SELF_REVIEW")
    call(api, "PATCH", path, "sampleadmin", {"name": "新版本"})
    error(decide(api, path, review), 409, "STALE_VERSION")


@pytest.mark.parametrize("operation", ["patch", "restore"])
def test_approved_zone_changes_require_new_review(api, operation):
    path = create(api)
    approved = publish_zone(api, path, perm="edit")
    assert decide(api, path, approved).status_code == 200
    assert listed(api, "sampleobserver", path)
    assert call(api, "GET", path, "sampleobserver").json()["item"]["version"] == "0.1.0"

    if operation == "patch":
        response = call(api, "PATCH", path, "sampleextra", {"spec": {"prompt": "更新内容"}})
    else:
        response = call(api, "POST", path + "/restore", "sampleextra", {"v": "0.1.0"})
    assert response.status_code == 200, response.text
    draft = response.json()["item"]
    assert (draft["version"], draft["status"]) == ("0.2.0", "in_review")
    assert draft["spec"]["prompt"] == ("更新内容" if operation == "patch" else "")
    assert not listed(api, "sampleobserver", path)
    error(call(api, "GET", path, "sampleobserver"), 403, "FORBIDDEN")
    for user in ("sampleoperator", "sampleextra"):
        assert listed(api, user, path)
        assert call(api, "GET", path, user).json()["item"]["version"] == draft["version"]

    pending, = review_queue(api)
    assert pending["id"] == path[1:] and pending["reviewId"] != approved["reviewId"]
    assert pending["version"] > approved["version"] and pending["spec"] == draft["spec"]
    error(decide(api, path, approved), 409, "STALE_VERSION")
    assert decide(api, path, pending).status_code == 200
    assert listed(api, "sampleobserver", path)
    public = call(api, "GET", path, "sampleobserver").json()["item"]
    assert (public["version"], public["spec"]) == (draft["version"], draft["spec"])
    assert [snapshot["v"] for snapshot in public["versions"]] == ["0.1.0", "0.2.0"]


def test_zone_public_history_only_includes_approved_content(api):
    path = create(api)
    call(api, "PATCH", path, body={"spec": {"prompt": "首发前私有草稿"}})
    call(api, "PATCH", path, body={"spec": {"prompt": "首发公开版本"}})
    assert decide(api, path, publish_zone(api, path)).status_code == 200
    call(api, "PATCH", path, body={"spec": {"prompt": "审核驳回内容"}})
    rejected, = review_queue(api)
    assert decide(api, path, rejected, "reject", reason="需要补充").status_code == 200
    assert not listed(api, "sampleobserver", path)
    call(api, "PATCH", path, body={"spec": {"prompt": "再次获批的内容"}})
    pending, = review_queue(api)
    assert decide(api, path, pending).status_code == 200

    public = call(api, "GET", path, "sampleobserver").json()["item"]
    assert [(snapshot["v"], snapshot["spec"]["prompt"]) for snapshot in public["versions"]] == [
        ("0.3.0", "首发公开版本"), ("0.5.0", "再次获批的内容"),
    ]
    owner = call(api, "GET", path).json()["item"]
    assert [snapshot["v"] for snapshot in owner["versions"]] == ["0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0"]
    for version in ("0.2.0", "0.4.0"):
        error(call(api, "POST", user="sampleextra", body={
            "forkOf": {"id": path[1:], "version": version},
        }), 404, "NOT_FOUND")
    rate = call(api, "POST", path + "/rate", "sampleobserver", {"useful": True})
    assert rate.status_code == 200
    assert rate.json()["item"]["versions"] == public["versions"]


def test_queue_tracks_active_review_after_author_edit(api):
    path = create(api)
    original = publish_zone(api, path)
    reviewer_path = "/api/v1/reviews"
    pending, = review_queue(api)
    assert (pending["reviewId"], pending["version"]) == (original["id"], original["version"])
    inbox, = review_queue(api, reviewer_path)
    assert (inbox["reviewId"], inbox["version"]) == (pending["reviewId"], pending["version"])

    edited = call(api, "PATCH", path, body={"spec": {"prompt": "补充后重新送审"}})
    assert edited.status_code == 200, edited.text
    assert review_queue(api) == review_queue(api, reviewer_path) == []
    error(decide(api, path, pending), 409, "STALE_VERSION")
    replacement = publish_zone(api, path)
    assert replacement["reviewId"] != pending["reviewId"]
    for body in ({"decision": "approve"}, {"decision": "approve", "version": replacement["version"]},
                 {"decision": "approve", "reviewId": replacement["reviewId"], "version": True}):
        error(call(api, "POST", path + "/review", "samplereviewer", body), 400, "INVALID_REQUEST")
    error(decide(api, path, pending), 409, "STALE_VERSION")
    error(decide(api, path, pending, version=replacement["version"]), 409, "STALE_VERSION")
    error(api.post(f"{reviewer_path}/{pending['reviewId']}/decisions",
                   headers={"x-test-user": "samplereviewer"},
                   json={"decision": "approve", "version": pending["version"]}), 409, "STALE_VERSION")
    assert not listed(api, "sampleobserver", path)
    assert decide(api, path, replacement).status_code == 200
    assert review_queue(api) == review_queue(api, reviewer_path) == []
    error(decide(api, path, replacement), 409, "STALE_VERSION")


def test_legacy_zone_edit_is_hidden_without_approval(api):
    from jkq.skills.storage import Skills

    path = create(api)
    assert decide(api, path, publish_zone(api, path)).status_code == 200
    # 模拟已有库中旧版 CRUD 继承 published 状态的记录。
    skills = api.app.state.skills
    owner = skills.platform.rbac.users["sampleoperator"]
    doc = skills.load(owner, path[1:], edit=True)
    Skills.save(skills, owner, doc, {"version": "0.2.0", "name": "旧流程中未经审核的版本"})
    assert not listed(api, "sampleobserver", path)
    error(call(api, "GET", path, "sampleobserver"), 403, "FORBIDDEN")
    assert call(api, "GET", path).json()["item"]["version"] == "0.2.0"


def test_withdrawing_zone_scope_revokes_previous_editor_grant(api):
    path = create(api)
    assert decide(api, path, publish_zone(api, path, perm="edit")).status_code == 200
    assert call(api, "GET", path, "sampleextra").json()["item"]["canEdit"]
    call(api, "POST", path + "/share", body={"scope": "private"})
    pending = publish_zone(api, path, perm="edit")
    error(call(api, "GET", path, "sampleextra"), 403, "FORBIDDEN")
    error(call(api, "PATCH", path, "sampleextra", {"name": "无权修改"}), 403, "FORBIDDEN")
    assert decide(api, path, pending).status_code == 200
    assert call(api, "GET", path, "sampleextra").json()["item"]["canEdit"]


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


@pytest.mark.parametrize("operation", ["publish", "patch"])
def test_failed_review_creation_rolls_back_publication(api, operation):
    import sqlite3

    path = create(api)
    if operation == "patch":
        assert decide(api, path, publish_zone(api, path)).status_code == 200
    before = call(api, "GET", path).json()["item"]
    store = api.app.state.skills.store
    with store._lock, store._db as db:
        db.execute("""CREATE TRIGGER reject_review BEFORE INSERT ON v1_reviews
                      BEGIN SELECT RAISE(ABORT, '审核写入失败'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="审核写入失败"):
        if operation == "publish":
            publish_zone(api, path)
        else:
            call(api, "PATCH", path, body={"name": "不能保存的版本"})
    assert call(api, "GET", path).json()["item"] == before
    assert review_queue(api) == []


def test_concurrent_votes_keep_both_users(api):
    from concurrent.futures import ThreadPoolExecutor

    path = create(api)
    call(api, "POST", path + "/publish", body={"share": {"scope": "dept"}})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [pool.submit(call, api, "POST", path + "/rate", user, {"useful": useful})
                     for user, useful in (("sampleoperator", False), ("sampleextra", True))]
        assert [job.result().status_code for job in responses] == [200, 200]
    item = call(api, "GET", path).json()["item"]
    assert (item["ratingN"], item["usefulRate"]) == (2, 50)

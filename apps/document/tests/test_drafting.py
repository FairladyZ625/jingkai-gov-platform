import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import Request

ROOT = Path(__file__).resolve().parents[3]
APP = "/api/apps/document"
INPUTS = {"orig": "示例申报通知", "oldEnd": "2026-11-02", "newEnd": "2026-11-06"}


@pytest.fixture
def document_client(isolated_platform, make_client):
    config, _ = isolated_platform
    path = config / "projects.yaml"
    seed = json.loads(path.read_text())
    seed["companies"][0]["projects"].append({"id": "jkq", "name": "经开区", "products": []})
    path.write_text(json.dumps(seed))

    path = config / "users.yaml"
    seed = json.loads(path.read_text())
    for user in seed["users"]:
        if user["id"] != "sampleoutsider":
            user["projects"].append("jkq")
    path.write_text(json.dumps(seed))

    path = config / "roles.yaml"
    seed = json.loads(path.read_text())
    for role, actions in {
        "sampleoperator": ["view", "operate"],
        "samplereviewer": ["view", "approve"],
        "sampleobserver": ["view"],
        "sampleoutsider": ["view", "operate"],
    }.items():
        seed["roles"][role] = {"grants": {"document": actions}}
    path.write_text(json.dumps(seed))
    client = make_client(ROOT / "apps")
    login(client, "sampleoperator")
    return client


def login(client, identity):
    response = client.post("/api/auth/login", json={"user_id": identity})
    assert response.status_code == 200


def create(client, **overrides):
    return client.post(f"{APP}/drafts", json={"templateId": "T06", "inputs": INPUTS, **overrides})


def item(response):
    assert response.status_code == 200, response.text
    return response.json()["item"]


def content(draft):
    return draft["versions"][-1]["content"]


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    return error["details"]


def test_catalog_and_document_fields(document_client):
    client = document_client
    response = client.get(f"{APP}/templates")
    assert response.status_code == 200
    catalogue = response.json()
    assert set(catalogue) == {"items", "groups"}
    assert [t["id"] for t in catalogue["items"]] == [f"T{i:02}" for i in range(1, 11)]
    assert [group for group, _ in catalogue["groups"]] == ["A", "B", "C"]
    for template in catalogue["items"]:
        assert set(template) == {"id", "group", "groupName", "name", "purpose", "inputs", "kind"}
        response = create(client, templateId=template["id"], inputs={k: s for k, _, s in template["inputs"]})
        draft = item(response)
        assert set(draft) == {"id", "title", "templateId", "policyId", "status", "author", "versions", "comments", "refs"}
        assert draft["templateId"] == template["id"]
        assert set(content(draft)) == {"title", "docNo", "to", "paragraphs", "sign", "date"}
        assert set(draft["versions"][0]) == {"v", "at", "by", "content"}
        assert draft["status"] == "草稿"
        assert draft["comments"] == []
        assert draft["refs"] == []
    documents = client.get(f"{APP}/documents").json()
    assert len(documents["items"]) == 10
    latest = documents["items"][0]
    assert set(latest) == {"id", "title", "templateId", "status", "author", "updated", "versions", "comments"}


def test_mock_fills_only_supplied_values(document_client):
    client = document_client
    draft = item(create(client, inputs={**INPUTS, "orig": "示例 <征集> & 申报", "reason": "  "}, extra=["补充说明"]))
    draft_content = content(draft)
    assert draft_content["title"] == "关于调整《示例 <征集> & 申报》申报期限的通知"
    assert draft_content["paragraphs"] == [
        "因【待补：调整原因】，现将《示例 <征集> & 申报》的申报截止时间由2026-11-02调整至2026-11-06。",
        "请按照调整后的期限提交申报。",
        "补充说明",
    ]
    assert draft_content["docNo"] == "【待补：发文字号】"
    assert draft_content["to"] == "【待补：主送机关】"
    assert draft_content["sign"] == "【待补：发文机关】"
    assert draft_content["date"] == "【待补：成文日期】"
    audit = client.app.state.platform.store.audit_list("document")
    row = next(row for row in audit if row["action"] == "document.draft.mock")
    assert row["detail"] == {"recordId": draft["id"], "provider": "mock"}


def test_three_saves_and_history_survive_restart(document_client, make_client):
    client = document_client
    original = item(create(client))
    url = f"{APP}/drafts/{original['id']}"
    assert item(client.get(url)) == original
    for n in range(1, 4):
        saved = item(client.put(url, json={"content": {**content(original), "title": f"第 {n} 次保存"}, "note": "测试保存"}))
        assert [v["v"] for v in saved["versions"]] == list(range(1, n + 1))
        assert saved["versions"][-1]["by"].endswith("（测试保存）")
    client = make_client(ROOT / "apps")
    login(client, "sampleoperator")
    draft = item(client.get(url))
    assert draft == saved
    assert item(client.get(url, params={"version": 0}))["versions"] == original["versions"]
    for n in range(1, 4):
        version = item(client.get(url, params={"version": n}))["versions"]
        assert [v["v"] for v in version] == [n]
        assert version[0]["content"]["title"] == f"第 {n} 次保存"
    assert client.get(f"{APP}/documents").json()["items"][0]["versions"] == 3
    assert_error(client.get(url, params={"version": 4}), 404, "NOT_FOUND")
    assert_error(client.get(url, params={"version": 2 ** 64}), 404, "NOT_FOUND")
    assert_error(client.get(url, params={"version": -1}), 400, "INVALID_REQUEST")


def test_concurrent_saves_append_unique_versions(document_client):
    client = document_client
    draft = item(create(client))
    url = f"{APP}/drafts/{draft['id']}"

    def save(title):
        return item(client.put(url, json={"content": {**content(draft), "title": title}}))

    titles = ["保存甲", "保存乙", "保存丙"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        revisions = list(pool.map(save, titles))
    assert sorted(v["versions"][-1]["v"] for v in revisions) == [1, 2, 3]
    assert {v["content"]["title"] for v in item(client.get(url))["versions"]} == set(titles)


def test_core_review_locks_document_without_new_version(document_client):
    client = document_client
    draft = item(create(client))
    url = f"{APP}/drafts/{draft['id']}"
    saved = item(client.put(url, json={"content": content(draft)}))
    body = {"appId": "document", "recordId": draft["id"], "version": 2, "assignee": "samplereviewer"}
    submitted = client.post("/api/v1/reviews", json=body)
    assert submitted.status_code == 201, submitted.text
    assert item(client.get(url))["status"] == "审签中"
    login(client, "samplereviewer")
    response = client.post(f"/api/v1/reviews/{submitted.json()['id']}/decisions", json={"version": 2, "decision": "confirm"})
    assert response.status_code == 200, response.text
    login(client, "sampleoperator")
    frozen = item(client.get(url))
    assert frozen["status"] == "已定稿"
    assert frozen["versions"] == saved["versions"]
    assert_error(client.put(url, json={"content": {**content(saved), "title": "尝试改稿"}}), 409, "LOCKED")
    assert item(client.get(url)) == frozen


def test_approval_between_read_and_save_rolls_back(document_client, monkeypatch):
    from haiknow_sdk.resources import Records

    client = document_client
    draft = item(create(client))
    identity = draft["id"]
    url = f"{APP}/drafts/{identity}"
    platform = client.app.state.platform
    review = client.post("/api/v1/reviews", json={
        "appId": "document", "recordId": identity, "version": 1, "assignee": "samplereviewer",
    })
    assert review.status_code == 201, review.text
    reviewer = platform.directory.user("samplereviewer")
    original_save = Records.save

    def approve_before_save(records, **body):
        platform.data.decide_review(reviewer, review.json()["id"], {"version": 1, "decision": "confirm"})
        return original_save(records, **body)

    monkeypatch.setattr(Records, "save", approve_before_save)
    response = client.put(url, json={"content": {**content(draft), "title": "并发改稿"}})
    assert_error(response, 409, "LOCKED")
    frozen = item(client.get(url))
    assert frozen["status"] == "已定稿"
    assert frozen["versions"] == draft["versions"]
    operator = platform.directory.user("sampleoperator")
    assert platform.data.get_record(operator, "document", identity)["version"] == 1


def test_product_route_guards_generic_mutation(document_client):
    from apps.document.api.drafting_router import records_guard

    client = document_client
    draft = item(create(client))
    platform_app = client.app
    count = len(platform_app.router.routes)
    platform_app.include_router(records_guard)
    routes = platform_app.router.routes
    routes[:] = routes[count:] + routes[:count]  # 使用 #11 的路由优先规则。
    url = "/api/v1/apps/document/records"
    assert_error(client.post(url, json={}), 405, "METHOD_NOT_ALLOWED")
    assert_error(client.put(f"{url}/{draft['id']}", json={}), 405, "METHOD_NOT_ALLOWED")
    assert item(client.get(f"{APP}/drafts/{draft['id']}")) == draft


def test_missing_template_bad_inputs_and_missing_draft(document_client):
    client = document_client
    assert_error(create(client, templateId="T99"), 404, "NOT_FOUND")
    details = assert_error(create(client, inputs={"orig": "  ", "newEnd": None}), 400, "INVALID_REQUEST")
    assert details == {"fields": ["orig", "oldEnd", "newEnd"]}
    assert_error(create(client, inputs={"orig": ["错误类型"]}), 400, "INVALID_REQUEST")
    assert_error(client.get(f"{APP}/drafts/missing"), 404, "NOT_FOUND")
    draft = item(create(client))
    url = f"{APP}/drafts/{draft['id']}"
    assert_error(client.put(url, json={"content": {"title": "缺字段"}}), 400, "INVALID_REQUEST")
    assert item(client.get(url)) == draft


def test_permissions_and_denial_audit(document_client):
    client = document_client
    draft = item(create(client))
    url = f"{APP}/drafts/{draft['id']}"
    login(client, "sampleobserver")
    assert item(client.get(url)) == draft
    assert assert_error(create(client), 403, "FORBIDDEN") == {"app": "document", "need": "operate"}
    assert assert_error(client.put(url, json={"content": content(draft)}), 403, "FORBIDDEN") == {
        "app": "document", "need": "operate",
    }
    audit = client.app.state.platform.store.audit_list("document")
    denied = [row for row in audit if row["action"] == "document.denied"]
    assert [row["user"] for row in denied] == ["sampleobserver", "sampleobserver"]
    login(client, "sampleoutsider")
    assert_error(client.get(url), 404, "NOT_FOUND")
    assert_error(create(client), 404, "NOT_FOUND")
    assert client.get(f"{APP}/documents").json() == {"items": []}
    client.cookies.clear()
    assert_error(client.get(url), 401, "UNAUTHENTICATED")


def test_policy_citation_links_to_the_exact_source_version(document_client):
    from haiknow_core.main import current_user
    from haiknow_sdk import DataError

    client = document_client
    article = "示例政策第六条，申请主体应提交能证明申报事实的材料。"

    class MockKnowledge:
        current = 1

        def detail(self, user, identity, version=None):
            assert user.id == "sampleoperator"
            if identity != "policy-demo":
                raise DataError("not_found", "资料不存在")
            versions = {1: article, 2: "示例政策的新版内容。"}
            version = version or self.current
            return {"id": identity, "title": "示例政策", "space": "policy",
                    "version": version, "text": versions[version]}

    knowledge = MockKnowledge()
    client.app.state.platform.kb = knowledge

    @client.app.get("/api/v1/kb/docs/{identity}")
    def source(request: Request, identity: str, version: int):
        return {"item": knowledge.detail(current_user(request), identity, version)}

    refs = [{"id": "policy-demo", "title": "客户端名称"}, {"id": "policy-demo"}]
    draft = item(create(client, refs=refs))
    ref, = draft["refs"]
    assert ref == {"n": 1, "marker": "〔1〕", "id": "policy-demo", "version": 1,
                   "title": "示例政策", "href": "/api/v1/kb/docs/policy-demo?version=1"}
    assert content(draft)["paragraphs"][-1] == f"政策原文摘录：{article}〔1〕"
    knowledge.current = 2
    assert item(client.get(ref["href"]))["text"] == article
    url = f"{APP}/drafts/{draft['id']}"
    assert item(client.put(url, json={"content": content(draft)}))["refs"] == [ref]
    assert_error(create(client, refs=[{"id": "missing"}]), 404, "NOT_FOUND")


def test_missing_kb_service_does_not_invent_references(document_client):
    client = document_client
    assert_error(create(client, refs=[{"id": "policy-demo"}]), 503, "APP_UNAVAILABLE")
    assert client.get(f"{APP}/documents").json() == {"items": []}

"""公文送审、决定与 Word 回读的 HTTP 验收。"""
import sys
from io import BytesIO

import pytest
from docx import Document
from haiknow_core.main import current_user

from apps.document.api import review_export
from apps.document.tests.test_drafting import APP, ROOT, assert_error, content, create, document_client, item, login
from jkq import reviews_api



def loaded_module(client):
    """平台以 haiknow_apps.document.* 加载应用后端，补丁须打在实际挂载的模块上。"""
    routes = list(client.app.routes)
    while routes:
        route = routes.pop()
        included = getattr(route, "original_router", None)
        if included is not None:
            routes.extend(included.routes)
        endpoint = getattr(route, "endpoint", None)
        module = getattr(endpoint, "__module__", "")
        if module.startswith("haiknow_apps.document.") and module.endswith(".review_export"):
            return sys.modules[module]
    raise AssertionError("送审路由未经 api/router.py 挂载")


@pytest.fixture
def flow(document_client, make_client, monkeypatch):
    # 复用草稿夹具的项目和权限配置，在首次 HTTP 请求前安装实例路由。
    from apps.document.instance import install

    client = make_client(ROOT / "apps")
    install(client.app)
    reviews_api.install(client.app, current_user)
    login(client, "sampleoperator")
    issues = []
    module = loaded_module(client)
    client.installed_check = module.check_issues
    monkeypatch.setattr(module, "check_issues", lambda ctx, request, record: issues)
    draft = item(create(client))
    url = f"{APP}/drafts/{draft['id']}"
    fields = {"title": "关于开展公开资料核验的通知", "docNo": "演示〔2026〕1号", "to": "各有关单位：",
              "paragraphs": ["请核对已公开的资料。", "", "请在周五前反馈核验结果。"],
              "sign": "公文演示工作组", "date": "2026年11月18日"}
    item(client.put(url, json={"content": fields}))
    return client, url, fields, issues


def test_checks_and_self_review(flow):
    client, url, _, issues = flow
    issues.extend({"id": str(i), "level": level} for i, level in enumerate(["warn", "error", "info", "error"]))
    response = client.post(url + "/submit", json={"assignee": "samplereviewer"})
    assert assert_error(response, 422, "CHECK_FAILED")["issueIds"] == ["1", "3"]
    issues.clear()
    assert_error(client.post(url + "/submit", json={"assignee": "sampleoperator"}), 409, "SELF_REVIEW")
    assert item(client.get(url))["status"] == "草稿"


def read_export(client, url, fields, mark):
    response = client.get(url + "/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == review_export.DOCX_TYPE
    assert response.headers["content-disposition"].endswith(".docx")
    document = Document(BytesIO(response.content))
    assert [p.text for p in document.paragraphs] == [
        fields["title"] + mark, fields["docNo"], fields["to"], *fields["paragraphs"], fields["sign"], fields["date"],
    ]


@pytest.mark.parametrize("decision,status", [("approve", "已定稿"), ("reject", "已退回")])
def test_decide_edit_export(flow, decision, status):
    client, url, fields, issues = flow
    read_export(client, url, fields, "（草稿）")
    issues.append({"id": "w", "level": "warn"})
    response = client.post(url + "/submit", json={"assignee": "samplereviewer"})
    assert item(response)["status"] == "审签中"
    review = response.json()["review"]
    assert review["assignee"] == "samplereviewer"
    read_export(client, url, fields, "（草稿）")
    login(client, "samplereviewer")
    decided = client.post(f"/api/v1/reviews/{review['id']}/decisions",
                          json={"version": review["version"], "decision": decision})
    assert decided.status_code == 200, decided.text
    login(client, "sampleoperator")
    assert item(client.get(url))["status"] == status
    read_export(client, url, fields, "" if decision == "approve" else "（草稿）")
    updated = client.put(url, json={"content": fields})
    if decision == "approve":
        assert_error(updated, 409, "LOCKED")
    else:
        assert content(item(updated)) == fields


def test_check_and_submit_use_same_version(flow, monkeypatch):
    client, url, fields, _ = flow

    def edited_during_check(ctx, request, record):
        item(client.put(url, json={"content": fields}))
        return []

    monkeypatch.setattr(loaded_module(client), "check_issues", edited_during_check)
    assert_error(client.post(url + "/submit", json={}), 409, "STALE_VERSION")
    login(client, "sampleobserver")
    assert_error(client.post(url + "/submit", json={}), 403, "FORBIDDEN")


def test_submit_with_installed_checker(flow, monkeypatch):
    """#39 接入前拒绝无核查送审，接入后直接验证其公开规则。"""
    from importlib.util import find_spec

    client, url, fields, _ = flow
    monkeypatch.setattr(loaded_module(client), "check_issues", client.installed_check)
    item(client.put(url, json={"content": {**fields, "paragraphs": ["【待补：调整原因】"]}}))
    response = client.post(url + "/submit", json={"assignee": "samplereviewer"})
    if find_spec(loaded_module(client).__package__ + ".checking_router") is None:
        assert_error(response, 503, "APP_UNAVAILABLE")
    else:
        assert assert_error(response, 422, "CHECK_FAILED")["issueIds"]
        item(client.put(url, json={"content": fields}))
        response = client.post(url + "/submit", json={"assignee": "samplereviewer"})
        assert item(response)["status"] == "审签中"


def test_generic_review_entry_cannot_bypass_checks(flow):
    """平台通用送审入口不做公文核查，必须拒绝公文；其他应用仍交给平台处理。"""
    client, url, _, issues = flow
    draft = item(client.get(url))
    issues.append({"id": "e", "level": "error"})
    body = {"appId": "document", "recordId": draft["id"], "version": draft["versions"][-1]["v"],
            "assignee": "samplereviewer"}
    assert_error(client.post("/api/v1/reviews", json=body), 405, "METHOD_NOT_ALLOWED")
    assert item(client.get(url))["status"] == "草稿"
    login(client, "samplereviewer")
    pending = client.get("/api/v1/reviews")
    assert pending.status_code == 200, pending.text
    assert pending.json()["items"] == []
    other = client.post("/api/v1/reviews", json={**body, "appId": "policy"})
    assert other.status_code in (403, 404), other.text


def test_export_normalizes_line_breaks_and_control_characters(flow):
    client, url, fields, _ = flow
    body = ["第一行\r\n第二行\r第三行", "分页前\f分页后", "去掉\x00\x07\x1b控制符\t保留制表"]
    item(client.put(url, json={"content": {**fields, "paragraphs": body}}))
    response = client.get(url + "/export")
    assert response.status_code == 200, response.text
    document = Document(BytesIO(response.content))
    texts = [p.text for p in document.paragraphs]
    assert texts[3:6] == ["第一行\n第二行\n第三行", "分页前分页后", "去掉控制符\t保留制表"]
    breaks = document.paragraphs[4]._p.xpath(".//w:br[@w:type='page']")
    assert len(breaks) == 1

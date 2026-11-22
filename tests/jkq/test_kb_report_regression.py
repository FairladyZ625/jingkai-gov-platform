"""公开固定快照 + 临时身份；用真实 HTTP 路由和模拟 provider，不允许外呼。"""
import re
import json
import secrets
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from jkq.kb.search import search
from jkq.kb.seed import documents

ROOT = Path(__file__).resolve().parents[2]
FOLLOW = "请列出这项数据券政策的申报期限、适用对象和需要审签的材料；如果原文没有写，请明确说明"


@pytest.fixture
def client(isolated_platform, cheap_password_hash, monkeypatch):
    from jkq.app import create_app
    from jkq import models

    monkeypatch.setenv("HAIKNOW_CONFIG_DIR", str(ROOT / "config"))
    monkeypatch.setenv("JKQ_DEMO_MODE", "1")
    monkeypatch.setenv("HAIKNOW_DEMO_LOGIN", "0")
    monkeypatch.setenv("HAIKNOW_SECRET", secrets.token_urlsafe(32))
    monkeypatch.setenv("HAIKNOW_APPS_DIR", str(ROOT / "apps"))
    monkeypatch.setenv("JKQ_ENTERPRISE_PRIVATE_DB", str(isolated_platform[0].parent / "fixture.sqlite"))
    password = secrets.token_urlsafe(18)
    for role in ("ADMIN", "MEMBER", "LEADER", "PARTNER"):
        monkeypatch.setenv("JKQ_DEMO_" + role + "_PASSWORD", password)
    # 真实模型连环境变量也不读；模拟 provider 仍经过网关、配额、摘录验证和路由标记。
    provider = models.provider_from_environment
    monkeypatch.setattr(models, "provider_from_environment", lambda m, c: provider(m, c) if m.kind == "mock" else None)
    app = create_app()
    with TestClient(app) as c:
        c.post("/api/v1/auth/login", json=dict(username="liyang", password=password)).raise_for_status()
        def fixture_login(name):
            c.post("/api/v1/auth/login", json=dict(username=name, password=password)).raise_for_status()
        c.fixture_login = fixture_login
        yield c


def post(c, endpoint, **data):
    response = c.post("/api/v1/kb/" + endpoint, json=data)
    response.raise_for_status()
    return response.json()


def test_four_visible_starters_recall_and_answer(client):
    config = (ROOT / "prototype/v4/apps/kb/config.js").read_text()
    questions = re.findall("'([^']+)'", re.search(r"suggestions: \[([^\]]+)", config)[1])
    assert len(questions) == 4
    for q, expected in zip(questions, ["100万元", "万元", "11月20日", "产业"]):
        hits = post(client, "search", q=q)["hits"]
        answer = post(client, "ask", q=q)
        assert not answer["notFound"], q
        assert expected in answer["answer"], q
        for ref in answer["citations"]:
            assert ref["id"] in {h["id"] for h in hits}
            doc = client.get("/api/v1/kb/docs/" + ref["id"]).json()["item"]
            assert ref["snippet"] in doc["text"]
        print(q, answer["source"], answer["citations"][0]["citationId"],
              len(answer["citations"]), "条引文已核对")
        if q == questions[0]:
            assert answer["source"] == "preset"
        else:
            assert answer["source"] == "extract"
        if "产业局" in q:
            assert "职责" in answer["citations"][0]["title"]
    missing = post(client, "ask", q="火星基地有哪些奖励？")
    assert missing["notFound"] and not missing["citations"]


def test_follow_uses_one_cited_version_not_neighbor_notices(client):
    first = post(client, "ask", q="数据券补贴最高能拿多少？")
    ref = first["citations"][0]
    answer = post(client, "ask", q=FOLLOW, scope=ref["citationId"])
    assert "适用于" in answer["answer"]
    for field in ("申报期限", "审签材料"):
        assert field + "：原文未明确" in answer["answer"]
    assert {c["citationId"] for c in answer["citations"]} == {ref["citationId"]}
    assert post(client, "ask", q=FOLLOW, scope="missing@v7")["notFound"]
    assert "先选定" in post(client, "ask", q=FOLLOW)["message"]


def test_new_document_nonstarter_and_scope_authorization(client):
    client.fixture_login("wangmin")
    text = ("虚拟青砾计划的交付周期为四周。\n本办法适用于登记在册的虚拟小组。\n"
            "申报期限为受理之日起十个工作日。\n申请表须由项目负责人审签。")
    imported = post(client, "import", title="虚拟青砾计划办理指南", text=text, space="rules")
    doc = imported["docs"][0]
    question = "请问虚拟青砾计划的交付周期是多少？"
    assert post(client, "search", q=question)["hits"][0]["id"] == doc["id"]
    answer = post(client, "ask", q=question)
    ref, = answer["citations"]
    assert ref["id"] == doc["id"] and ref["snippet"] == text.splitlines()[0]
    scoped = post(client, "ask", q=FOLLOW, scope=ref["citationId"])
    assert {c["snippet"] for c in scoped["citations"]} == set(text.splitlines()[1:])
    assert post(client, "ask", q=FOLLOW, scope=ref["citationId"], filters={"space":"template"})["notFound"]
    client.fixture_login("hejun")
    assert post(client, "ask", q=FOLLOW, scope=ref["citationId"])["notFound"]
    assert not post(client, "search", q=question, scope=ref["citationId"])["hits"]


def test_dedup_source_aliases_not_equal_titles():
    doc = next(d for d in documents() if d["id"] == "KB-P4150108")
    alias = dict(doc, id="alias")
    other = dict(doc, id="another-clause", text="数据券费用按季结算。")
    independent = dict(doc, id="different-source", source=dict(doc["source"], url="https://example.invalid/b"))
    result = search([doc, alias, other, independent], "数据券")
    assert result["total"] == len(result["hits"]) == 3
    assert {"another-clause", "different-source"} <= {h["id"] for h in result["hits"]}
    paired = dict(doc, text="第一条 数据券按季结算。\n第二条 数据券须经核验。")
    clauses = search([paired, dict(paired, id="alias")], "数据券")["hits"]
    assert len(clauses) == 1
    main = clauses[0]
    assert {p["snippet"] for p in [main, *main["relatedPassages"]]} == set(paired["text"].splitlines())
    assert {p["passage"] for p in [main, *main["relatedPassages"]]} == {1, 2}


@pytest.mark.parametrize("reply,question", [
    ("timeout", "实体书店有哪些奖励？"), (503, "实体书店有哪些奖励？"),
    (400, "数据券补贴最高能拿多少？"), ("[]", "实体书店有哪些奖励？"),
])
def test_nonmock_outcome_is_not_a_mock_answer(client, monkeypatch, reply, question):
    import httpx
    from jkq.kb.ask import MODEL_UNAVAILABLE, NOT_FOUND

    service = client.app.state.jkq_models
    monkeypatch.setitem(service.providers, "cloud", dict(
        id="cloud", kind="openai", model="fixture", allow_outbound="internal",
        base_url="https://model.invalid/v1", api_key="",
    ))
    monkeypatch.setattr(service, "primary", "cloud")
    attempts = []

    def upstream(request):
        assert request.url.host == "model.invalid"
        attempts.append(reply)
        if reply == "timeout":
            raise httpx.ReadTimeout("fixture", request=request)
        if isinstance(reply, int):
            return httpx.Response(reply)
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    monkeypatch.setattr(service, "transport", httpx.MockTransport(upstream))
    answer = post(client, "ask", q=question)
    assert attempts == [reply]
    assert answer["notFound"] and answer["citations"] == [] and "source" not in answer
    assert answer["message"] == (NOT_FOUND if reply == "[]" else MODEL_UNAVAILABLE)
    # 故障标记只属于上一次问答。相同账号明确选择 mock 后仍可用，且不请求上游。
    client.put("/api/v1/models/current", json={"model": "mock"}).raise_for_status()
    explicit = post(client, "ask", q="实体书店有哪些奖励？")
    assert explicit["source"] == "extract" and explicit["citations"]
    assert attempts == [reply]


def test_same_snapshot_uses_only_the_current_roles_visible_alias(client):
    # 同一份官网通知分别在通知库、政策库入库。不能先选一个不可见的去重代表。
    q = "亦城人才申报什么时候截止？"
    lead = post(client, "search", q=q)["hits"][0]
    assert lead["id"] == "KB-T4892665" and lead["space"] == "template"
    client.fixture_login("hejun")
    results = post(client, "search", q=q)["hits"]
    assert all(hit["space"] == "policy" for hit in results)
    visible = next(hit for hit in results if hit["source"]["url"] == lead["source"]["url"])
    assert visible["id"] == "rd-4892665" and visible["snippet"] == lead["snippet"]
    assert post(client, "ask", q=FOLLOW, scope=lead["citationId"])["notFound"]
    assert {c["id"] for c in post(client, "ask", q=q)["citations"]} == {visible["id"]}


def test_nonmock_backup_success_still_requires_verifiable_quote(client, monkeypatch):
    import httpx

    service = client.app.state.jkq_models
    for ident in ("cloud", "deepseek"):
        monkeypatch.setitem(service.providers, ident, dict(
            id=ident, kind=service.models[ident].kind, model="fixture", allow_outbound="internal",
            base_url=f"https://{ident}.invalid/v1", api_key="",
        ))
    monkeypatch.setattr(service, "primary", "cloud")
    hosts = []

    def upstream(request):
        hosts.append(request.url.host)
        if request.url.host == "cloud.invalid":
            return httpx.Response(503)
        assert request.url.host == "deepseek.invalid"
        passages = json.loads(json.loads(request.content)["messages"][-1]["content"])["passages"]
        raw = json.dumps([dict(passage=1, quote="虚构，不在正文。"),
                          dict(passage=1, quote=passages[0]["sentences"][0])])
        return httpx.Response(200, json={"choices": [{"message": {"content": raw}}]})

    monkeypatch.setattr(service, "transport", httpx.MockTransport(upstream))
    answer = post(client, "ask", q="实体书店有哪些奖励？")
    assert hosts == ["cloud.invalid", "deepseek.invalid"]
    assert not answer["notFound"] and "source" not in answer and "虚构，不在正文" not in answer["answer"]
    ref, = answer["citations"]
    assert ref["snippet"] in client.get("/api/v1/kb/docs/" + ref["id"]).json()["item"]["text"]

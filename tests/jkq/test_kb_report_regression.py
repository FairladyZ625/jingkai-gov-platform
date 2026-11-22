"""公开固定快照 + 临时身份；用真实 HTTP 路由和模拟 provider，不允许外呼。"""
import re
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

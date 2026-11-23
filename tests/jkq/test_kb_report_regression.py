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


@pytest.mark.parametrize("q", ["群雁计划上市辅导补贴最高多少？", "群雁计划的上市辅导补助上限是多少？",
                              "群雁计划中，上市辅导的资助上限是多少钱？"])
def test_plan_and_clause_are_separate_anchors(client, q):
    a = post(client, "ask", q=q)
    assert not a["notFound"] and a["source"] == "extract"
    assert any("上市辅导" in c["snippet"] and "最高为200万元" in c["snippet"] for c in a["citations"])
    assert all("群雁计划" in c["title"] and "上市辅导" in c["snippet"] for c in a["citations"])
    assert post(client, "ask", q="虚拟白榆计划上市辅导补贴最高多少？")["notFound"]


def test_relational_subsidy_question_requires_the_qualified_cost_clause(client):
    q = "群雁计划对境内上市辅导费用怎么补贴？"
    doc_id = "KB-P4280732"
    assert doc_id in {h["id"] for h in post(client, "search", q=q)["hits"]}
    source = client.get("/api/v1/kb/docs/" + doc_id).json()["item"]["text"]
    expected = next(s.strip() for s in re.split(r"(?<=。)|\n", source)
                    if all(term in s for term in ("境内上市辅导", "实际支付服务费用", "30%", "200万元")))
    ref, = post(client, "ask", q=q)["citations"]
    assert ref["id"] == doc_id and ref["snippet"] == expected
    for qualifier in ("境外上市辅导", "境内上市辅导差旅"):
        result = post(client, "ask", q=q.replace("境内上市辅导", qualifier))
        assert result["notFound"] and not result["citations"]


def test_imported_free_duration_requires_matching_visitor_and_free_activity(client):
    client.fixture_login("wangmin")
    raw = (ROOT / "tests/fixtures/kb_visitor_parking.txt").read_text(encoding="utf-8")
    title, quote, *_ = raw.splitlines()
    doc = post(client, "import", title=title, text=raw, space="rules")["docs"][0]
    q = "鹿桥园区普通访客可以免费停车多久？"
    assert doc["id"] in {h["id"] for h in post(client, "search", q=q)["hits"]}
    result = post(client, "ask", q=q)
    assert [(c["id"], c["snippet"]) for c in result["citations"]] == [(doc["id"], quote)]
    for question in (q.replace("普通访客", "驻场车辆"), "鹿桥园区普通访客停车缴费金额是多少？"):
        missing = post(client, "ask", q=question)
        assert missing["notFound"] and not missing["citations"]
    decoy = post(client, "import", title=title + "（对照）", space="rules",
                 text="鹿桥园区普通访客须登记，驻场车辆免费停车时长为两小时。\n"
                      "鹿桥园区普通访客不再免费停车，停车时长为三天。")["docs"][0]
    denied = post(client, "ask", q=q, scope=f"{decoy['id']}@v{decoy['version']}")
    assert denied["notFound"] and not denied["citations"]
    client.fixture_login("hejun")
    assert post(client, "ask", q=q)["notFound"]


def test_imported_duration_bounds_and_qualifiers(client):
    client.fixture_login("wangmin")
    for title, text, questions, expected in [
        ("园区停车管理通知", "访客车辆应在服务台登记。园区停车每次最长2小时，到时应驶离。",
         ["园区停车最长能停多久？", "园区停车最多几小时？"], "最长2小时"),
        ("星湖仪器借用细则", "维护人员检修最长9小时。星湖仪器借用每次不得超过四十五分钟，不得续借。",
         ["星湖仪器借用时长上限是多少？", "星湖仪器借用最长能用多久？"], "不得超过四十五分钟，不得续借"),
    ]:
        doc = post(client, "import", title=title, text=text, space="rules")["docs"][0]
        for q in questions:
            a = post(client, "ask", q=q, space="rules")
            assert not a["notFound"], q
            assert {c["id"] for c in a["citations"]} == {doc["id"]}
            assert all(expected in c["snippet"] and c["snippet"] in text for c in a["citations"])
    for q in ("星湖仪器借用最短需要多久？", "星湖仪器夜间借用最多几小时？", "园区停车押金是多少？"):
        a = post(client, "ask", q=q, space="rules")
        assert a["notFound"] and not a["citations"], q
    # 只有时长有原文。不能用检修时长、其他文件的费用或常识补缺。
    partial = post(client, "ask", q="星湖仪器借用最长能用多久，押金是多少？", space="rules")
    assert "四十五分钟" in partial["answer"] and "押金" in partial["answer"] and "未" in partial["answer"]
    assert all("不得续借" in c["snippet"] for c in partial["citations"])
    reversed_fields = post(client, "ask", q="星湖仪器借用押金是多少，最长能用多久？", space="rules")
    assert "四十五分钟" in reversed_fields["answer"] and "押金" in reversed_fields["answer"] and "未" in reversed_fields["answer"]
    denied = post(client, "ask", q="星湖仪器借用是否可以续借？", space="rules")
    assert not denied["notFound"] and all("不得续借" in c["snippet"] for c in denied["citations"])
    # 标题命中不能把文中其他活动的时长当作允许停车的时间。
    post(client, "import", title="岚谷停车管理通知", space="rules",
         text="岚谷停车区不允许过夜，摄像记录最长为三十天。")
    assert post(client, "ask", q="岚谷停车最长能停多久？", space="rules")["notFound"]
    client.fixture_login("hejun")
    assert post(client, "ask", q=questions[0])["notFound"]


def test_http_deadline_is_shared_by_model_attempts(client, monkeypatch):
    import asyncio
    import httpx
    from jkq.kb.ask import MODEL_UNAVAILABLE

    service = client.app.state.jkq_models
    for ident in ("cloud", "deepseek"):
        monkeypatch.setitem(service.providers, ident, dict(
            id=ident, kind=service.models[ident].kind, model="fixture", allow_outbound="internal",
            base_url=f"https://{ident}.invalid/v1", api_key=""))
    monkeypatch.setattr(service, "primary", "cloud")
    attempts = []

    async def stalled(request):
        attempts.append((request.url.host, request.extensions["timeout"]["read"]))
        await asyncio.sleep(4)
        pytest.fail("协议桩应在子预算耗尽时取消")

    monkeypatch.setattr(service, "transport", httpx.MockTransport(stalled))
    answer = post(client, "ask", q="群雁计划上市辅导补贴最高多少？", timeoutMs=2400)
    assert [host for host, _ in attempts] == ["cloud.invalid", "deepseek.invalid"]
    # 三个候选（含 mock），按网关原有策略分配；检索已耗时间也从预算扣除。
    assert all(0 < budget < 2.4 / 4 for _, budget in attempts)
    assert answer["unavailable"] and answer["message"] == MODEL_UNAVAILABLE and not answer["citations"]

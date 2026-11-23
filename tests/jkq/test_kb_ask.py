import json
import runpy
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# 「仓库检查」的 pytest job 只装 pytest。直接加载纯问答逻辑，避免知识库包初始化导入 FastAPI。
domain = runpy.run_path(str(ROOT / "jkq/kb/ask.py"))
ask = domain["ask"]
CASES = json.loads((ROOT / "tests/fixtures/kb_eval.json").read_text())


def hit(ident="demo", text="第一条。", *, status="现行有效", space="policy"):
    return dict(id=ident, title=ident, snippet=text, chunk=0, source={"docNo": "示例"},
                status=status, space=space)


class Gateway:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def complete(self, messages, classification):
        self.calls.append((json.loads(messages[-1]["content"]), classification))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def call(self, app, capability, payload, *, principal):
        assert (app, capability) == ("kb", "chat")
        assert "partner" in principal.roles
        return {"result": self.complete(payload["messages"], payload["classification"])}


def output(*pairs):
    return json.dumps([dict(passage=index, quote=quote) for index, quote in pairs], ensure_ascii=False)


@pytest.mark.parametrize("hits", [[], [hit(text=" \n")], [hit(text="原注 [99]。")]])
def test_no_match_never_calls_gateway(hits):
    gateway = Gateway()
    result = ask("有哪些依据？", hits, gateway.complete)
    assert result["confidence"] == "none" and result["notFound"] is True
    assert result["citations"] == [] and result["answer"] == result["message"]
    assert not gateway.calls


def test_each_citation_uses_only_the_whole_sentence_from_the_named_hit():
    valid = "本项不允许代领。"
    second = "受理时限为1.5天。"
    hits = [hit(text=valid + second), hit("separate", "另一份材料。")]
    gateway = Gateway(output(
        (1, "凭空生成的句子。"),
        (1, "允许代领。"),
        (2, valid),
        (True, valid),
        (0, valid),
        (1, valid),
        (1, valid),
        (1, second),
    ))
    result = ask("怎样受理？", hits, gateway.complete)
    assert result["confidence"] == "mid" and result["notFound"] is False
    assert result["answer"].splitlines() == [f"“{valid}”[1]", f"“{second}”[2]"]
    assert [c["n"] for c in result["citations"]] == [1, 2]
    assert all(c["id"] == "demo" and c["snippet"] in hits[0]["snippet"] for c in result["citations"])
    assert len(gateway.calls) == 1


@pytest.mark.parametrize("status", ["已失效", "已更新"])
def test_obsolete_citation_retains_source_status(status):
    source = hit("old", "旧版条款。", status=status)
    gateway = Gateway(output((1, source["snippet"])))
    result = ask("旧版怎么规定？", [source], gateway.complete)
    assert result["confidence"] == "low" and result["citations"][0]["status"] == status
    assert result["citations"][0]["source"] == source["source"]


def test_expiry_date_is_inclusive_and_does_not_erase_superseded_status():
    document = dict(hit(), expire="2026-11-18")
    status = domain["with_current_status"]
    assert status(document, date(2026, 11, 18))["status"] == "现行有效"
    assert status(document, date(2026, 11, 19))["status"] == "已失效"
    old = dict(document, status="已更新")
    assert status(old, date(2026, 11, 19))["status"] == "已更新"


@pytest.mark.parametrize("bad", [TimeoutError("服务商原始错误"), "畸形响应", '{"quote":"编造"}', None])
def test_gateway_failure_returns_readable_answer(bad):
    gateway = Gateway(bad)
    result = ask("问题", [hit()], gateway.complete)
    assert result == domain["no_answer"](domain["MODEL_UNAVAILABLE"])
    assert len(gateway.calls) == 1


def test_when_all_quotes_are_rejected():
    gateway = Gateway(output((1, "第二条。")))
    assert ask("问题", [hit()], gateway.complete) == domain["no_answer"]()


def test_enterprise_hits_use_confidential_route():
    source = hit("archive", "企业档案条目。", space="enterprise")
    gateway = Gateway(output((1, source["snippet"])))
    result = ask("档案里有什么？", [source], gateway.complete)
    assert len(result["citations"]) == 1
    assert gateway.calls[0][1] == "confidential"


@pytest.fixture(scope="module")
def public_docs():
    docs = json.loads((ROOT / "data/public/kb_docs.json").read_text())
    return [dict(doc, source={key: doc.get(key, "") for key in ("org", "date", "url", "docNo")})
            for doc in docs]


def test_demo_fixture_points_to_public_source(public_docs):
    assert len(CASES) == len({case["q"] for case in CASES}) == 10
    docs = {doc["id"]: doc["text"] for doc in public_docs}
    for case in CASES:
        assert case["chunk"] == 0
        assert case["contains"] in docs[case["id"]], case


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_demo_citations_with_bm25(case, public_docs):
    pytest.importorskip("fastapi")
    search = pytest.importorskip("jkq.kb.search", reason="等待 #26 BM25 检索进入 main").search

    def select_first(messages, classification):
        assert classification == "internal"
        passage = json.loads(messages[-1]["content"])["passages"][0]
        return output((passage["passage"], passage["sentences"][0]))

    hits = search([doc for doc in public_docs if doc["text"].strip()], case["q"])["hits"]
    result = ask(case["q"], hits, select_first)
    citation, = result["citations"]
    assert (citation["id"], citation["chunk"]) == (case["id"], case["chunk"])
    assert case["contains"] in citation["snippet"]
    assert citation["snippet"] in next(doc["text"] for doc in public_docs if doc["id"] == case["id"])


@pytest.fixture
def instance_factory(isolated_platform, cheap_password_hash, monkeypatch):
    pytest.importorskip("fastapi")
    from jkq.app import create_app

    monkeypatch.setenv("HAIKNOW_DEMO_LOGIN", "0")
    monkeypatch.setenv("HAIKNOW_SECRET", "jkq-test-session-signing")
    monkeypatch.setenv("HAIKNOW_CONFIG_DIR", str(ROOT / "config"))
    return create_app


def test_default_startup_exposes_ask_before_search_merges(instance_factory, monkeypatch):
    from fastapi.testclient import TestClient
    from jkq.kb import ask as module

    monkeypatch.setattr(module, "_load_search", lambda: None)
    app = instance_factory()
    gateway = Gateway()
    monkeypatch.setattr(app.state.platform.model, "aihub", gateway)
    with TestClient(app) as client:
        endpoint = "/api/v1/kb/ask"
        assert client.post(endpoint, json={"q": "算力券 封顶"}).status_code == 401
        credentials = {"username": "ask-user", "password": "demo-password"}
        assert client.post("/api/auth/bootstrap", json={**credentials, "name": "测试用户"}).status_code == 200
        response = client.post(endpoint, json={"q": "算力券 封顶"})
        assert response.status_code == 200
        assert response.json() == module.no_answer(module.SEARCH_UNAVAILABLE)
        assert gateway.calls == []


def test_http_with_cookie_auth_and_partner_space_filter(instance_factory, monkeypatch):
    from fastapi.testclient import TestClient
    from jkq.kb import ask as module

    public = hit("public", "仅限公开片段。")
    enterprise = hit("private", "企业内部资料。", space="enterprise")
    calls = []

    def search(docs, question, *, filters):
        calls.append(filters)
        assert [doc["space"] for doc in docs] == ["policy"]
        return {"hits": {"问题": [enterprise, public], "无命中": [], "只有企业": [enterprise],
                         "只有标题": [dict(public, snippet="不在正文里的标题")]}[question]}

    monkeypatch.setattr(module, "_load_search", lambda: search)
    app = instance_factory()
    platform = app.state.platform
    # 同时模拟候选服务与检索边界意外返回了过量结果。
    monkeypatch.setattr(platform.kb, "candidates", lambda user: [
        dict(public, text=public["snippet"]), dict(enterprise, text=enterprise["snippet"]),
    ])
    gateway = Gateway(output((1, enterprise["snippet"]), (1, public["snippet"])))
    monkeypatch.setattr(platform.model, "aihub", gateway)
    with TestClient(app) as client:
        endpoint = "/api/v1/kb/ask"
        assert client.post(endpoint, json={"q": "问题"}).json()["error"]["code"] == "UNAUTHENTICATED"
        credentials = {"username": "ask-user", "password": "demo-password"}
        assert client.post("/api/auth/bootstrap", json={**credentials, "name": "测试用户"}).status_code == 200
        session_user = platform.directory.session_user

        def partner_session(uid, generation):
            user = session_user(uid, generation)
            return replace(user, roles=("partner", "admin")) if user is not None else None

        monkeypatch.setattr(platform.directory, "session_user", partner_session)
        response = client.post(endpoint, json={"q": "问题", "space": "policy", "filters": {"validOnly": True}})
        assert response.status_code == 200
        citation, = response.json()["citations"]
        assert citation["id"] == "public" and citation["snippet"] == public["snippet"]
        assert gateway.calls == [({"question": "问题", "passages": [
            {"passage": 1, "title": public["title"], "sentences": [public["snippet"]]},
        ]}, "internal")]
        assert calls[0]["space"] == "policy" and calls[0]["validOnly"] is True
        for q in ("无命中", "只有企业", "只有标题", " ，？！ "):
            assert client.post(endpoint, json={"q": q}).json()["notFound"] is True
        for body in ({"q": "问题", "space": "enterprise"},
                     {"q": "问题", "filters": {"space": "enterprise"}}):
            denied = client.post(endpoint, json=body)
            assert (denied.status_code, denied.json()["error"]["code"]) == (403, "FORBIDDEN")
        invalid = client.post(endpoint, json={"q": []})
        assert (invalid.status_code, invalid.json()["error"]["code"]) == (422, "CHECK_FAILED")
        assert len(gateway.calls) == 1
        gateway.result = TimeoutError()
        failed = client.post(endpoint, json={"q": "问题"}).json()
        assert failed == domain["no_answer"](domain["MODEL_UNAVAILABLE"])

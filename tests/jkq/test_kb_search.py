"""运行万片基准：python3 -m pytest -qs tests/jkq/test_kb_search.py -k benchmark"""
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from jkq.kb.search import install, search
from jkq.kb.stats import stats

ROOT = Path(__file__).resolve().parents[2]


def document(i, **changes):
    doc = dict(id=str(i), title="服务指南", text="支持企业年度申报。", status="现行有效",
               space="policy", kind="政策文件", tags=[], source=dict(date="2026-01-01"),
               example=True, real=False, version=2)
    doc.update(changes)
    return doc


@pytest.fixture(scope="module")
def seed():
    rows = json.loads((ROOT / "data/public/kb_docs.json").read_text())
    return [dict(row, source={k: row.get(k, "") for k in ("date", "org", "docNo", "url")})
            for row in rows]


def test_public_clause_and_seed_counts(seed):
    result = search(seed, "算力券 封顶")
    hit = result["hits"][0]
    assert set(result) == {"hits", "total", "terms", "facets"}
    assert "算力券" in hit["snippet"] and "最高2000万元" in hit["snippet"]
    assert hit["snippet"] in next(d["text"] for d in seed if d["id"] == hit["id"])
    assert hit["id"] == "KB-P3950424" and hit["chunk"] == 0
    assert hit["spaceName"] == "政策库" and hit["chunks"] == 1
    counts = stats(seed)
    assert counts["docs"] == len(seed)
    assert counts["real"] == sum(bool(d["real"]) for d in seed)
    assert counts["example"] == sum(bool(d.get("example")) for d in seed)


def test_filters_sort_facets_limit_and_expiry():
    docs = [document(i) for i in range(60)]
    docs.append(document("expired", space="rules", kind="办法", status="已失效",
                         source=dict(date="2026-04-01", org="示例部门")))
    docs[0]["text"] *= 2
    docs[0]["source"]["date"] = None
    assert stats(docs)["recent"][0]["id"] == "expired"
    r = search(docs, "企业", limit=999)
    assert len(r["hits"]) == 50 and r["total"] == 61
    assert all(d["status"] == "现行有效" for d in r["hits"])
    for field, counts in r["facets"].items():
        for item in counts:
            filtered = search(docs, "企业", filters={field: item["k"]})
            assert filtered["total"] == item["n"]
    dated = search(docs, "企业", sort="date")["hits"]
    assert dated[0]["id"] == "expired" and dated[0]["status"] == "已失效"
    assert dated[0]["source"]["date"] > dated[1]["source"]["date"]
    assert search(docs, "数据库")["total"] == 0


def test_benchmark():
    docs = [document(i, text=f"第{i}条支持企业申报。") for i in range(10000)]
    samples = []
    for _ in range(25):
        start = time.perf_counter()
        result = search(docs, "企业")
        samples.append(1000 * (time.perf_counter() - start))
        assert result["total"] == 10000
    p95 = sorted(samples)[math.ceil(len(samples) * 0.95) - 1]
    print(f"10000 个切片，25 次检索 P95 {p95:.1f} ms")
    assert p95 < 500


def api(monkeypatch, *, vector=False, gateway=None, docs=None):
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    app = fastapi.FastAPI()
    user = SimpleNamespace(id="demo", roles=["partner"])
    docs = docs if docs is not None else [document(1), document(2, space="enterprise")]
    def require(principal, action):
        assert principal is user and action == "view"
    def candidates(principal):
        require(principal, "view")
        return [d for d in docs if d["space"] == "policy"]
    platform = SimpleNamespace(kb=SimpleNamespace(candidates=candidates, require=require),
                               model=SimpleNamespace(aihub=gateway))
    monkeypatch.delenv("JKQ_KB_VECTOR_SEARCH", raising=False)
    if vector:
        monkeypatch.setenv("JKQ_KB_VECTOR_SEARCH", "1")
    install(app, platform, lambda: user, lambda principal: ("policy",))
    return TestClient(app)


def test_partner_errors_stats_suggest_and_default_vector(monkeypatch, seed):
    docs = seed + [document("example"), document("private", space="enterprise")]
    client = api(monkeypatch, docs=docs)
    base = "/api/v1/kb/"
    for q in ("", "  ", "，。！？", "_?!"):
        r = client.post(base + "search", json={"q": q})
        assert (r.status_code, r.json()["error"]["code"]) == (400, "INVALID_QUERY")
    for extra in (dict(space="enterprise"), dict(filters=dict(space="enterprise"))):
        r = client.post(base + "search", json=dict(q="企业", **extra))
        assert (r.status_code, r.json()["error"]["code"]) == (403, "FORBIDDEN")
    r = client.post(base + "search", json=dict(q="算力券 封顶")).json()
    assert "最高2000万元" in r["hits"][0]["snippet"]
    assert {item["k"] for item in r["facets"]["space"]} == {"policy"}
    counts = client.get(base + "stats").json()
    visible = [d for d in docs if d["space"] == "policy"]
    assert counts["real"] == sum(bool(d["real"]) for d in visible)
    assert counts["example"] == sum(bool(d.get("example")) for d in visible)
    assert len(client.get(base + "suggest").json()["items"]) >= 3


def local_settings(providers, route):
    class Settings:
        def route(self, capability):
            return route if capability == "embedding" else None

        def provider(self, ident):
            return providers.get(ident)

    return SimpleNamespace(settings=Settings(), files=None, audit=None)


def local_provider(ident="local-emb", *, enabled=True, allow="confidential",
                   kind="local", url="http://127.0.0.1:8080", models=("emb-a",)):
    return dict(id=ident, kind=kind, enabled=enabled, base_url=url, models=list(models),
                allow_outbound=allow, api_key="")


def test_passage_selection_single_char_and_expired_tie():
    docs = [
        document("toc", title="算力券申报", text="目录。\n申报材料应包括算力券申报要求。"),
        document("tax", title="通知", text="企业税收申报。"),
        document("live", title="办法", text="支持企业年度申报。", status="现行有效"),
        document("dead", title="办法", text="支持企业年度申报。", status="已失效"),
    ]
    toc = search(docs, "算力券")
    assert toc["hits"][0]["id"] == "toc"
    assert toc["hits"][0]["snippet"] == "申报材料应包括算力券申报要求。"
    assert search(docs, "税")["hits"][0]["id"] == "tax"
    ranked = search([docs[2], docs[3]], "企业")["hits"]
    assert [h["id"] for h in ranked] == ["live", "dead"]
    assert ranked[1]["status"] == "已失效"


def test_search_parameter_errors(monkeypatch):
    client = api(monkeypatch)
    base = "/api/v1/kb/search"
    bad = client.post(base, json={"q": "企业", "sort": "unknown"})
    zero = client.post(base, json={"q": "企业", "limit": 0})
    for response in (bad, zero):
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "CHECK_FAILED" and "message" in error and "details" in error


def test_vector_startup_and_semantic_hit(monkeypatch):
    with pytest.raises(RuntimeError, match="embedding"):
        api(monkeypatch, vector=True)

    disabled = local_settings({"cloud": local_provider("cloud", enabled=False, kind="openai",
                                                       url="https://example.com")},
                              dict(provider="cloud", model="emb-a",
                                   fallback_provider=None, fallback_model=None))
    with pytest.raises(RuntimeError, match="本地 embedding"):
        api(monkeypatch, vector=True, gateway=disabled)

    remote = local_settings({"cloud": local_provider("cloud", kind="openai", url="https://example.com")},
                            dict(provider="cloud", model="emb-a",
                                 fallback_provider=None, fallback_model=None))
    with pytest.raises(RuntimeError, match="本地 embedding"):
        api(monkeypatch, vector=True, gateway=remote)

    providers = {
        "cloud": local_provider("cloud", kind="openai", url="https://example.com"),
        "local-emb": local_provider(),
        "local-b": local_provider("local-b", models=("emb-b",)),
    }
    gateway = local_settings(providers, dict(provider="cloud", model="emb-a",
                                             fallback_provider="local-emb", fallback_model="emb-a"))
    calls = []

    def fake_call(self, app_id, capability, payload, timeout=50, *, principal=None, **kwargs):
        provider, model = self._route_candidates(capability)[0][0]["id"], self._route_candidates(capability)[0][1]
        calls.append((provider, payload["input"], payload["classification"]))
        assert (app_id, capability, principal.id, payload["classification"]) == (
            "kb", "embedding", "demo", "confidential")
        assert provider == "local-emb"
        return {"result": [{"embedding": [1, 0]}], "provider": provider, "model": model}

    docs = [document(1), document(2, title="另一份指南", text="企业应当按时申报。")]
    monkeypatch.setattr("haiknow_core.aihub.gateway.Gateway.call", fake_call)
    client = api(monkeypatch, vector=True, gateway=gateway, docs=docs)
    first = client.post("/api/v1/kb/search", json={"q": "企业", "limit": 1}).json()
    assert first["total"] == 2 and len(first["hits"]) == 1
    # 查询向量 + 1 条重排候选，不会把可见库全部向量化。
    assert len(calls) == 2 and {c[0] for c in calls} == {"local-emb"}
    client.post("/api/v1/kb/search", json={"q": "企业", "limit": 1})
    assert len(calls) == 2  # 重复查询走缓存

    # 跨模型或维度不一致时退回 BM25 顺序。
    def mixed_call(self, app_id, capability, payload, timeout=50, *, principal=None, **kwargs):
        provider, model = "local-emb", "emb-a"
        if payload["input"] != "企业":
            provider, model = "local-b", "emb-b"
        return {"result": [{"embedding": [1, 0]}], "provider": provider, "model": model}

    monkeypatch.setattr("haiknow_core.aihub.gateway.Gateway.call", mixed_call)
    baseline = search(docs, "企业")
    mixed = client.post("/api/v1/kb/search", json={"q": "企业"}).json()
    assert [h["id"] for h in mixed["hits"]] == [h["id"] for h in baseline["hits"]]

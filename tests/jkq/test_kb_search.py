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


def test_vector_startup_and_semantic_hit(monkeypatch):
    with pytest.raises(RuntimeError, match="embedding"):
        api(monkeypatch, vector=True)
    calls = []
    def call(app_id, capability, payload, principal):
        calls.append(payload)
        assert (app_id, capability, principal.id) == ("kb", "embedding", "demo")
        return {"result": [{"embedding": [1, 0]}]}
    gateway = SimpleNamespace(settings=SimpleNamespace(route=lambda capability: {"model": "demo"}), call=call)
    client = api(monkeypatch, vector=True, gateway=gateway)
    r = client.post("/api/v1/kb/search", json={"q": "补贴"}).json()
    assert r["total"] == 1 and r["hits"][0]["score"] == 1
    assert len(calls) == 2 and all(c["classification"] == "confidential" for c in calls)

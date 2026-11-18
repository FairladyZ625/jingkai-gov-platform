"""在 #24 已授权的候选文档上按片段检索，以文档为单位分页和计数。"""
from collections import Counter, OrderedDict
from threading import Lock
from functools import lru_cache
import math
import os
import re

from .stats import facet_values, facets, metadata, passages, stats, suggest

WORDS = re.compile(r"[\u3400-\u9fff]+|(?:(?![\u3400-\u9fff])[^\W_])+", re.UNICODE)
CAP_TERMS = ("最高", "不超过", "上限")


def tokens(text):
    for word in WORDS.findall(text.casefold()):
        if "\u3400" <= word[0] <= "\u9fff" and len(word) > 1:
            yield from (word[i:i + 2] for i in range(len(word) - 1))
        else:
            yield word


@lru_cache(maxsize=16384)
def indexed(text, singles):
    frequencies = Counter(tokens(text))
    size = sum(frequencies.values())
    for term in singles:
        frequencies[term] = text.count(term)
    return frequencies, size


def matches(doc, filters):
    fields = facet_values(doc)
    return (all(not filters.get(k) or filters[k] == v for k, v in fields.items())
            and (not filters.get("tag") or filters["tag"] in doc.get("tags", ()))
            and (not filters.get("validOnly") or doc["status"] not in ("已失效", "已更新")))


def search(docs, q, *, filters=None, sort="rel", limit=8, embed=None):
    terms = list(dict.fromkeys(tokens(q)))
    if not terms:
        raise ValueError("请输入有效的检索词")
    expanded = set(terms)
    if "封顶" in terms:
        for synonym in CAP_TERMS:
            expanded.update(tokens(synonym))
    singles = tuple(t for t in terms if len(t) == 1 and "\u3400" <= t <= "\u9fff")
    rows, df, length, npassages = [], Counter(), 0, 0
    for doc in docs:
        if not matches(doc, filters or {}):
            continue
        title, title_size = indexed(doc["title"], singles)
        title_terms = [t for t in expanded if title[t]]
        snippets = []
        present = set(title_terms)
        for snippet in passages(doc):
            frequencies, size = indexed(snippet, singles)
            found = [t for t in expanded if frequencies[t]]
            present.update(found)
            length += size
            npassages += 1
            snippets.append((snippet, frequencies, size, found))
        df.update(present)
        rows.append((doc, title, title_size, title_terms, snippets))
    average = length / npassages if npassages else 1
    weights = {t: math.log1p((len(rows) - n + 0.5) / (n + 0.5)) * (1 if t in terms else 0.45)
               for t, n in df.items()}

    def bm25(frequencies, size, found):
        norm = 1.2 * (0.25 + 0.75 * (size or 1) / average)
        return sum(weights[t] * frequencies[t] * 2.2 / (frequencies[t] + norm) for t in found)

    best = {}
    for doc, title, title_size, title_terms, snippets in rows:
        title_score = bm25(title, title_size or 1, title_terms)
        picked = None
        for snippet, frequencies, size, found in snippets:
            body = bm25(frequencies, size, found)
            original = sum(t in terms for t in found)
            key = (original, len(found) - original, body)
            if picked is None or key > picked[0]:
                picked = (key, snippet, body)
        if picked is None:
            coverage, snippet, body = (0, 0), doc["title"], 0
        else:
            coverage, snippet, body = picked[0][:2], picked[1], picked[2]
        # 标题只轻微影响文档排序；片段选择优先覆盖原查询词，再看同义扩充。
        score = body + 0.25 * title_score
        if (coverage != (0, 0) or title_terms) and (
            doc["id"] not in best or (coverage, score) > (best[doc["id"]][3], best[doc["id"]][0])
        ):
            best[doc["id"]] = (score, snippet, doc, coverage)

    def rank(hit):
        score, _, doc, coverage = hit
        expired = doc["status"] == "已失效"
        return (-coverage[0], -coverage[1], -score * (0.6 if expired else 1), expired, doc["id"])

    ranked = sorted(best.values(), key=rank)
    if embed and ranked:
        # 只重排 BM25 候选；total 和 facets 不依赖分页或模型响应。
        count = min(len(ranked), limit, 8)
        bonuses = embed(q, ranked[:count])
        for i, bonus in enumerate(bonuses):
            score, snippet, doc, coverage = ranked[i]
            ranked[i] = (score + bonus, snippet, doc, coverage)
        ranked.sort(key=rank)
    if sort == "date":
        ranked.sort(key=lambda hit: hit[2]["source"].get("date") or "", reverse=True)
    hits = []
    for hit in ranked[:min(limit, 50)]:
        score, snippet, doc, coverage = hit
        hits.append(dict(metadata(doc), chunk=0, snippet=snippet, score=-rank(hit)[2]))
    return dict(hits=hits, total=len(ranked), terms=terms, facets=facets(hit[2] for hit in ranked))


def local_reranker(gateway):
    from haiknow_core.aihub.config import valid_base_url
    from haiknow_core.aihub.errors import AIError
    from haiknow_core.aihub.gateway import Gateway, allowed_outbound

    class LocalEmbedding(Gateway):
        def _route_candidates(self, capability, model=None):
            pairs = super()._route_candidates(capability, model)
            local = [(p, m) for p, m in pairs if p["kind"] == "local" and m.strip()
                     and valid_base_url(p["base_url"]) and allowed_outbound(p, "confidential")]
            if not local:
                raise AIError("not_configured", "缺少可处理机密资料的本地 embedding 服务")
            return local

    if gateway is None:
        raise RuntimeError("请先配置本地 aihub embedding 路由")
    scoped = LocalEmbedding(gateway.settings, getattr(gateway, 'files', None),
                               getattr(gateway, 'audit', None))
    try:
        scoped._route_candidates("embedding")
    except AIError as exc:
        raise RuntimeError("请配置已启用且可处理机密资料的本地 embedding 服务及模型") from exc
    cache = OrderedDict()
    lock = Lock()

    def rerank(user, q, candidates):
        def vector(text):
            key = ("text", text)
            with lock:
                existing = cache.get(key)
                if existing is not None:
                    cache.move_to_end(key)
                    return existing
            response = scoped.call("kb", "embedding", dict(input=text, classification="confidential"),
                                   principal=user)
            value = ((response["provider"], response["model"]), response["result"][0]["embedding"])
            with lock:
                cache[key] = value
                if len(cache) > 4096:
                    cache.popitem(last=False)
            return value

        try:
            identity, query = vector(q)
            bonuses = []
            for item in candidates:
                snippet, doc = item[1], item[2]
                actual, existing = vector(snippet)
                if actual != identity or len(existing) != len(query):
                    return []
                magnitude = math.hypot(*query) * math.hypot(*existing)
                bonuses.append(max(0, sum(x*y for x, y in zip(query, existing)) / magnitude)
                               if magnitude else 0)
            return bonuses
        except AIError:
            # 配额耗尽、服务停用或上游失败时保留整组 BM25 顺序。
            return []

    return rerank


def install(app, platform, current_user, visible_spaces=None):
    """#11 在 #24 安装后调用。测试桩仅替换候选服务、空间可见性及登录依赖。"""
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
    from typing import Literal, Optional

    if visible_spaces is None:
        from .spaces import visible_spaces
    rerank = None
    if os.getenv("JKQ_KB_VECTOR_SEARCH", "0").lower() in ("1", "true", "yes"):
        rerank = local_reranker(getattr(getattr(platform, "model", None), "aihub", None))

    class Filters(BaseModel):
        space: str = ""
        status: str = ""
        kind: str = ""
        org: str = ""
        year: str = ""
        tag: str = ""
        validOnly: bool = False

    class Query(BaseModel):
        q: str = ""
        space: str = ""
        sort: Literal["rel", "date"] = "rel"
        limit: int = Field(default=8, ge=1)
        filters: Optional[Filters] = None

    from .docs import KbError, KbRoute

    if KbError not in app.exception_handlers:
        # 单独安装（测试桩）时也保持 #24 的错误对象契约。
        async def kb_error(request, exc):
            return JSONResponse({"error": exc.error}, status_code=exc.status)

        app.add_exception_handler(KbError, kb_error)

    router = APIRouter(prefix="/api/v1/kb", route_class=KbRoute)
    session = Depends(current_user)

    @router.post("/search")
    def query(body: Query, user=session):
        docs = platform.kb.candidates(user)
        filters = body.filters.model_dump() if body.filters else {}
        allowed = visible_spaces(user)
        if any(space and space not in allowed for space in (body.space, filters.get("space"))):
            return JSONResponse({"error": dict(code="FORBIDDEN", message="无权查看该空间",
                                               details=dict(app="kb", need="view"))}, status_code=403)
        if body.space:
            filters["space"] = body.space
        if not WORDS.search(body.q):
            return JSONResponse({"error": dict(code="INVALID_QUERY", message="请输入有效的检索词",
                                               details={})}, status_code=400)

        return search(docs, body.q, filters=filters, sort=body.sort, limit=body.limit,
                      embed=(lambda q, rows: rerank(user, q, rows)) if rerank else None)

    @router.get("/stats")
    def statistics(user=session):
        return stats(platform.kb.candidates(user))

    @router.get("/suggest")
    def suggestions(user=session):
        platform.kb.require(user, "view")
        return suggest()

    app.include_router(router)

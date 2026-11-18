"""在 #24 已授权的候选文档上按片段检索，以文档为单位分页和计数。"""
from collections import Counter
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
def indexed(title, snippet):
    frequencies = Counter(tokens(snippet))
    frequencies.update(tokens(title))
    return frequencies, sum(frequencies.values())


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
    rows, df, length = [], Counter(), 0
    for doc in docs:
        if not matches(doc, filters or {}):
            continue
        for chunk, snippet in enumerate(passages(doc)):
            frequencies, size = indexed(doc["title"], snippet)
            found = expanded.intersection(frequencies)
            df.update(found)
            length += size
            rows.append((doc, chunk, snippet, frequencies, size, found))
    average = length / len(rows) if length else 1
    weights = {t: math.log1p((len(rows) - n + 0.5) / (n + 0.5)) * (1 if t in terms else 0.45)
               for t, n in df.items()}
    query_vector = embed(q, "confidential") if embed and rows else None
    best = {}
    for doc, chunk, snippet, frequencies, size, found in rows:
        norm = 1.2 * (0.25 + 0.75 * size / average)
        score = sum(weights[t] * frequencies[t] * 2.2 / (frequencies[t] + norm) for t in found)
        if query_vector is not None:
            vector = embed(snippet, doc.get("classification") or "confidential")
            if len(vector) != len(query_vector):
                raise ValueError("embedding 向量维度不匹配")
            magnitude = math.hypot(*vector) * math.hypot(*query_vector)
            if magnitude:
                score += max(0, sum(x*y for x, y in zip(query_vector, vector)) / magnitude)
        if score <= 0:
            continue
        if doc["status"] == "已失效":
            score *= 0.6
        ident = doc["id"]
        if ident not in best or score > best[ident][0]:
            best[ident] = (score, chunk, snippet, doc)
    ranked = sorted(best.values(), key=lambda hit: (-hit[0], hit[3]["id"]))
    if sort == "date":
        ranked.sort(key=lambda hit: hit[3]["source"].get("date") or "", reverse=True)
    hits = [dict(metadata(doc), chunk=chunk, snippet=snippet, score=score,
                 citationId=f"{doc['id']}@v{doc.get('version', 1)}")
            for score, chunk, snippet, doc in ranked[:min(limit, 50)]]
    return dict(hits=hits, total=len(ranked), terms=terms, facets=facets(hit[3] for hit in ranked))


def install(app, platform, current_user, visible_spaces=None):
    """#11 在 #24 安装后调用。测试桩仅替换候选服务、空间可见性及登录依赖。"""
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
    from typing import Literal, Optional

    if visible_spaces is None:
        from .spaces import visible_spaces
    gateway = None
    if os.getenv("JKQ_KB_VECTOR_SEARCH", "0").lower() in ("1", "true", "yes"):
        gateway = getattr(getattr(platform, "model", None), "aihub", None)
        if not gateway or not gateway.settings.route("embedding"):
            raise RuntimeError("已开启知识库向量检索，请先配置 aihub embedding 路由")

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

    router = APIRouter(prefix="/api/v1/kb")
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

        def embed(text, classification):
            result = gateway.call("kb", "embedding", dict(input=text, classification=classification),
                                  principal=user)
            return result["result"][0]["embedding"]

        return search(docs, body.q, filters=filters, sort=body.sort, limit=body.limit,
                      embed=embed if gateway else None)

    @router.get("/stats")
    def statistics(user=session):
        return stats(platform.kb.candidates(user))

    @router.get("/suggest")
    def suggestions(user=session):
        platform.kb.require(user, "view")
        return suggest()

    app.include_router(router)

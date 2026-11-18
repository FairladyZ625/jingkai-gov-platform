"""仅汇总调用者可见的知识库资料。"""
from collections import Counter
import re


def passages(doc):
    """以原文自然段和句末为边界，返回可逐字核对的片段。"""
    for paragraph in doc.get("text", "").splitlines():
        for sentence in re.findall(r"[^。！？]+[。！？]*", paragraph):
            if sentence.strip():
                yield sentence.strip()


def metadata(doc):
    return {k: v for k, v in doc.items() if k not in ("text", "excerpts", "embedding")}


def facet_values(doc):
    source = doc["source"]
    return dict(space=doc["space"], status=doc["status"], kind=doc["kind"],
                org=source.get("org", ""), year=(source.get("date") or "")[:4])


def facets(docs):
    counts = {key: Counter() for key in ("space", "status", "kind", "org", "year")}
    for doc in docs:
        for key, value in facet_values(doc).items():
            if value:
                counts[key][value] += 1
    return {key: [dict(k=k, n=n) for k, n in counter.most_common()]
            for key, counter in counts.items()}


def stats(docs):
    latest = sorted(docs, key=lambda d: d.get("addedAt") or d["source"].get("date") or "", reverse=True)
    return dict(docs=len(docs), real=sum(bool(d.get("real")) for d in docs),
                example=sum(bool(d.get("example")) for d in docs),
                chunks=sum(1 for d in docs for _ in passages(d)),
                status=dict(Counter(d["status"] for d in docs)),
                recent=[metadata(d) for d in latest[:5]], facets=facets(docs), log=[])


def suggest():
    return {"items": ["算力券支持金额最高是多少？", "申报有哪些材料要求？", "政策有效期到哪一天？"]}

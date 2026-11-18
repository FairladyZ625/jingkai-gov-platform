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
    """#24 的候选记录每份非空正文对应详情 chunkList[0]。"""
    names = {"policy": "政策库", "template": "公文范文", "minutes": "会议纪要",
             "rules": "部门制度", "enterprise": "企业档案"}
    fields = ("id", "title", "space", "kind", "tags", "real", "example", "source",
              "expire", "status", "version", "from")
    result = {k: doc[k] for k in fields if k in doc}
    return dict(result, chunks=int(bool(doc.get("text"))), spaceName=names.get(doc["space"], doc["space"]),
                citationId=f"{doc['id']}@v{doc.get('version', 1)}")



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
                chunks=sum(bool(d.get("text")) for d in docs),
                status=dict(Counter(d["status"] for d in docs)),
                recent=[metadata(d) for d in latest[:5]], facets=facets(docs), log=[])


def suggest():
    return {"items": ["算力券支持金额最高是多少？", "申报有哪些材料要求？", "政策有效期到哪一天？"]}

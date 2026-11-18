"""读取公开快照及 #8 补充资料。相同来源在不同资料集合中保留各自身份。"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from .spaces import NAMES

ROOT = Path(__file__).resolve().parents[2]
SUPPLEMENTS = {"gongwen": "template", "rules": "rules", "minutes": "minutes", "enterprises": "enterprise"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def document(row, space, identity, text):
    source = dict(org=row.get("issuer") or row.get("org") or row.get("source", ""),
                  date=row.get("date", ""), url=row.get("source_url") or row.get("url", ""),
                  docNo=row.get("doc_no") or row.get("docNo") or row.get("no", ""))
    example = row.get("example", False)
    source_status = row.get("status", "")
    status = source_status
    if source_status not in {"", "现行有效", "已失效", "即将到期", "已更新"}:
        source["statusNote"] = source_status
        status = {"已失效（官网标注）": "已失效", "现行（政务服务网）": "现行有效"}.get(source_status, "")
    return dict(id=identity, space=space, title=row.get("title") or row["name"],
                kind=row.get("kind") or row.get("type") or row.get("wenzhong") or NAMES[space],
                tags=row.get("tags", []), real=row.get("real", not example), example=example,
                source=source, expire=row.get("expire", ""), status=status,
                text=text, version=1, **{"from": "官网" if not example else "粘贴"})


def documents(root=ROOT):
    seed = root / "data/seed"
    kb = seed / "real-kb.json"
    records = read(kb)["docs"] if kb.exists() else read(root / "data/public/kb_docs.json")
    by_url = {row["url"]: row["text"] for row in records if row.get("url")}
    for row in records:
        yield document(row, row["space"], row["id"], row["text"])

    policies = seed / "real-policies.json"
    if policies.exists():
        payload = read(policies)
    else:
        # 主种子迁移前，原型的赋值右侧是相同结构的 JSON；不执行脚本。
        script = (root / "prototype/v4/data/real-policies.js").read_text(encoding="utf-8")
        payload, _ = json.JSONDecoder().raw_decode(script.split("window.JK_REAL =", 1)[1].lstrip())
    excerpts = defaultdict(list)
    for clause in payload["policies"]:
        if clause.get("original"):
            excerpts[clause["doc"]].append(dict(clause=clause["clause"], original=clause["original"],
                                                source=clause["source"]))
    for row in payload["policyDocs"]:
        doc = document(dict(row, kind="政策文件", status=row.get("state", "").split(" · ")[0]),
                       "policy", row["id"], by_url.get(row["url"], ""))
        if not doc["text"] and excerpts[row["id"]]:
            doc["excerpts"] = excerpts[row["id"]]
            doc["text"] = "\n\n".join(c["clause"] + " " + c["original"] for c in doc["excerpts"])
        yield doc

    if (seed / "kb-examples.json").exists():
        for row in read(seed / "kb-examples.json"):
            yield document(dict(row, example=True), row["space"], row["id"], row["text"])

    for collection, space in SUPPLEMENTS.items():
        for row in read(seed / "real" / (collection + ".json")):
            title = row.get("title") or row["name"]
            key = hashlib.sha256((title + "\n" + row["source_url"]).encode()).hexdigest()[:24]
            text = row.get("full_text") or row.get("honor_or_list") or row.get("report_title", "")
            yield document(row, space, f"{collection}-{key}", text)

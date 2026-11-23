"""政策目录读取层：优先使用 #29 的 data/seed 种子，缺失时回退原型公开快照。"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone, timedelta
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[3]
APP_DATA = Path(__file__).resolve().parents[1] / "data"
WINDOWS = {"open": True, "ended": False, "unknown": None}
BEIJING = timezone(timedelta(hours=8))


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalized_conditions(item: dict) -> list[dict]:
    """事项详情与匹配检查使用同一条件序列，主体条件始终在第一位。"""
    conditions = list(item.get("conditions") or [])
    if not conditions or conditions[0].get("f") != "subjectType":
        conditions = [{
            "f": "subjectType",
            "op": "==",
            "v": item["object"],
            "label": f"申报对象为{item['object']}",
        }, *conditions]
    return conditions


def _notice_period(times: dict) -> dict:
    notice = times.get("notice") or {}
    period = notice.get("window") or {}
    scope = str(notice.get("scope") or "")
    if not period.get("start") or not period.get("end"):
        return {}
    if any(token in scope for token in ("未确认", "部分覆盖", "仅覆盖")):
        return {}
    return period


def _public_snapshot() -> dict:
    seed = ROOT / "data/seed/real-policies.json"
    supplement = _json(APP_DATA / "public_snapshot_additions.json")
    if seed.is_file():
        snapshot = _json(seed)
    else:
        # 主线当前只有原型的公开快照。只解码 JSON 字面量，后附脚本无需执行。
        source = (ROOT / "web/data/real-policies.js").read_text(encoding="utf-8")
        payload = source.split("window.JK_REAL = ", 1)[1]
        snapshot, _ = json.JSONDecoder().raw_decode(payload)
    docs = {doc["id"]: doc for doc in snapshot["policyDocs"]}
    items = {item["id"]: item for item in snapshot["policies"]}
    for doc in supplement["policyDocs"]:
        docs.setdefault(doc["id"], doc)
    for item in supplement["policies"]:
        items.setdefault(item["id"], item)
    for item_id, updates in supplement["verifiedCorrections"].items():
        if item_id in items:
            items[item_id].update(updates)
    for item_id, extra in supplement["additionalConditions"].items():
        if item_id in items:
            conditions = items[item_id]["conditions"]
            fields = {condition["f"] for condition in conditions}
            conditions.extend(condition for condition in extra if condition["f"] not in fields)
    return {"policyDocs": list(docs.values()), "policies": list(items.values())}


def _public_source(row: dict, url: object) -> bool:
    if row.get("real") is not True or not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.hostname)


def public_catalog(snapshot: dict) -> tuple[dict, dict]:
    docs = {
        doc["id"]: doc
        for doc in snapshot["policyDocs"]
        if _public_source(doc, doc.get("url") or "")
    }
    items = {
        item["id"]: item
        for item in snapshot["policies"]
        if item.get("doc") in docs and _public_source(item, (item.get("source") or {}).get("url"))
    }
    return items, docs


@cache
def catalog() -> tuple[dict, dict]:
    return public_catalog(_public_snapshot())


def _window(item: dict, today: date) -> dict:
    times = item["times"]
    period = _notice_period(times)
    start, end = period.get("start"), period.get("end")
    if not start or not end:
        return times

    if today < date.fromisoformat(start):
        state, deadline_text = None, f"该批次将于 {start} 开始申报（以申报通知为准）"
        status = "未开始"
    elif today > date.fromisoformat(end):
        state, deadline_text = False, f"该批次已于 {end} 截止，下一批时间以后续申报通知为准"
        status = "已截止"
    else:
        state, deadline_text = True, f"当前批次申报至 {end}（以申报通知为准）"
        status = "申报中"
    return {
        **times,
        "open": state,
        "window": f"{start} 至 {end}",
        "noticePending": state is not True,
        "notice": {**times["notice"], "status": status},
        "deadline": end if state else None,
        "deadlineText": deadline_text,
    }


def list_items(q: str, object_type: str, window: str, *, today: date | None = None) -> dict:
    items, docs = catalog()
    query = q.strip().casefold()
    today = today or datetime.now(BEIJING).date()
    results = []
    for item in items.values():
        if object_type and item["object"] != object_type:
            continue
        row = item_with_doc(item, docs[item["doc"]], today=today)
        if window and row["times"]["open"] is not WINDOWS[window]:
            continue
        searchable = (
            row["id"], row["title"], row.get("sub", ""), row["docNo"], row["docTitle"],
            row.get("original", ""), *row.get("keywords", []),
        )
        if query and not any(query in text.casefold() for text in searchable):
            continue
        results.append(row)
    return {"items": results, "total": len(results), "docs": list(docs.values())}


def item_with_doc(item: dict, doc: dict, *, today: date | None = None) -> dict:
    return {
        **item,
        "conditions": normalized_conditions(item),
        "times": _window(item, today or datetime.now(BEIJING).date()),
        "docNo": doc["no"],
        "docTitle": doc["title"],
        "docState": doc["state"],
    }


def enterprise_profile(ent_id: str) -> dict | None:
    """临时按演示 ID 提供匹配画像。接真实企业服务时需传递当前用户权限。"""
    demo = ROOT / "data/seed/demo.json"
    if demo.is_file():
        rows = _json(demo)["enterprises"]
    else:
        rows = _json(APP_DATA / "demo_profiles.json")["enterprises"]
    row = next((row for row in rows if row["id"] == ent_id), None)
    if row is None:
        return None
    fields = ("subjectType", "industry", "scale", "tags", "license", "yearsInZone", "regInZone", "employees", "established")
    return {**(row.get("amounts") or {}), **{field: row[field] for field in fields if field in row}}

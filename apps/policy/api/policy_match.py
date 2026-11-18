"""按事项条件逐项判断，保留原条件和缺失信息。"""

from __future__ import annotations

from collections import Counter
from operator import ge, gt, le


COMPARISONS = {">=": ge, ">": gt, "<=": le}
LEVELS = {"ok": 0, "check": 1, "no": 2}


def _evaluate(condition: dict, profile: dict) -> str:
    field, op, expected = condition["f"], condition["op"], condition["v"]
    value = profile.get(field)
    if value is None or value == "":
        return "unknown"
    if op == "==":
        both_numeric = type(value) in (int, float) and type(expected) in (int, float)
        if not both_numeric and type(value) is not type(expected):
            return "unknown"
        matched = value == expected
    elif op in ("has", "hasAny"):
        if field == "scale" and isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or any(not isinstance(entry, str) for entry in value):
            return "unknown"
        candidates = expected if isinstance(expected, list) else [expected]
        matched = any(candidate in value for candidate in candidates)
    elif op in COMPARISONS and type(value) in (int, float):
        matched = COMPARISONS[op](value, expected)
    else:
        return "unknown"
    return "ok" if matched else "no"


def _display(value) -> str:
    if type(value) is bool:
        return "是" if value else "否"
    if isinstance(value, list):
        return "、".join(map(str, value)) or "空列表"
    return str(value)


def _check(condition: dict, profile: dict) -> dict:
    state = _evaluate(condition, profile)
    label = condition["label"]
    if state == "unknown":
        reason = f"待确认「{label}」，画像缺少可核对的数据"
    else:
        value = _display(profile[condition["f"]])
        outcome = "符合" if state == "ok" else "不符合"
        reason = f"画像值为「{value}」，{outcome}条件「{label}」"
    return {"label": label, "state": state, "reason": reason, "condition": condition}


def match_items(profile: dict, items, *, estimate_item) -> dict:
    results = []
    for item in items:
        conditions = item["conditions"]
        if conditions and conditions[0]["f"] == "subjectType":
            classification, *conditions = conditions
        else:
            classification = {"f": "subjectType", "op": "==", "v": item["object"], "label": f"申报对象为{item['object']}"}
        subject = _check(classification, profile)
        if subject["state"] == "no":
            continue
        checks = [subject, *(_check(condition, profile) for condition in conditions)]
        states = {check["state"] for check in checks}
        level = "no" if "no" in states else "check" if "unknown" in states else "ok"
        times, rule = item["times"], item["rule"]
        results.append({
            "id": item["id"],
            "title": item["title"],
            "level": level,
            "checks": checks,
            "pending": item.get("pending", []),
            "window": times["window"],
            "open": times["open"],
            "ended": times["open"] is False,
            "calc": None if level == "no" else estimate_item(rule, profile.get(rule.get("base"))),
            "rule": rule["text"],
            "doc": item["docNo"],
            "clause": item["clause"],
            "source": item["source"],
            "real": True,
            "category": item.get("category", ""),
        })
    results.sort(key=lambda result: (LEVELS[result["level"]], result["ended"]))
    counts = Counter(result["level"] for result in results)
    return {"profile": profile, "results": results, "summary": {level: counts[level] for level in LEVELS}}

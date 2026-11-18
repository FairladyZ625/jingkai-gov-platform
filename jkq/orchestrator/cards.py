"""把业务工具结果投影为 §4.5 卡片。"""

from .ports import ToolCall


def _card(kind: str, app: str, params: dict, **fields) -> dict:
    return {"type": kind, **fields, "deepLink": {"app": app, "params": params}}


def _list(result: dict, key: str) -> list:
    values = result[key]
    if not isinstance(values, list):
        raise ValueError(f"卡片字段 {key} 必须是数组")
    return values


def _ids(result: dict) -> list[str]:
    if "ids" in result:
        return [key for key in _list(result, "ids") if isinstance(key, str) and key]
    return [
        item["id"] for item in _list(result, "items")
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
    ]


def render_card(call: ToolCall, result: dict) -> dict | None:
    tool, args = call.tool, call.args
    if tool == "policy.match":
        ent = result.get("entId") or result.get("profile", {}).get("entId") or args.get("entId")
        if ent:
            return _card("policy-match", "policy", {"entId": ent}, entId=ent, results=_list(result, "results")[:5])
    if tool == "policy.search":
        ids = _ids(result)
        params = {"tab": "library", **({"itemId": ids[0]} if ids else {})}
        return _card("policy-items", "policy", params, ids=ids)
    if tool == "enterprise.get":
        ent = result.get("entId") or result.get("item", {}).get("id") or args.get("id")
        if ent:
            return _card("enterprise-brief", "enterprise", {"entId": ent}, entId=ent)
    if tool == "enterprise.search":
        ids = _ids(result)
        return _card("enterprise-list", "enterprise", {"entId": ids[0]} if ids else {}, ids=ids)
    if tool == "enterprise.alerts":
        items = _list(result, "items")
        params = {"entId": items[0]["entId"]} if items else {}
        return _card("alerts", "enterprise", params, items=items)
    if tool == "meeting.list":
        ids = _ids(result)
        params = {"meetingId": ids[0], "process": False} if ids else {}
        return _card("meeting-list", "meeting", params, ids=ids)
    if tool == "meeting.summarize" and "todos" in result:
        meeting = result.get("meetingId") or args.get("meetingId")
        if meeting:
            return _card("todos", "meeting", {"meetingId": meeting, "tab": "todos"}, items=_list(result, "todos"))
    if tool == "document.draft":
        template = result.get("templateId") or result.get("item", {}).get("templateId") or args.get("templateId")
        if template:
            return _card("doc-start", "document", {"templateId": template, "autogen": True}, templateId=template)
    if tool == "document.templates":
        return _card("doc-templates", "document", {})
    if tool == "document.compare":
        # §4.5 的主操作是复制。可定位同一份草稿时附上导航。
        a, b = result.get("a", args.get("a")), result.get("b", args.get("b"))
        draft = a.get("id") if isinstance(a, dict) else a
        other = b.get("id") if isinstance(b, dict) else b
        params = {"draftId": draft} if isinstance(draft, str) and draft == other else {}
        return _card("diff", "document", params, a=a, b=b, parts=_list(result, "parts"))
    if tool == "kb.ask":
        hits = _list(result, "citations")
        return _card("kb-hits", "kb", {"fileId": hits[0]["id"]}, hits=hits)
    return _card("app-suggest", call.app, {})

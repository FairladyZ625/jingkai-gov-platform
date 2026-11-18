"""按规则与模型执行一轮对话，使用同一个按请求人授权的工具目录。"""

from dataclasses import dataclass, field
from typing import Literal

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from jkq.conversations.store import encode

from .cards import render_card
from .ports import ModelGateway, ToolBridge, ToolCall
from .rules import match_rule

Classification = Literal["public", "internal", "confidential"]

SYSTEM = (
    "按用户需求使用可用工具。知识、政策或原文问题必须先调用 kb.ask；"
    "若工具不可用，请说明无法查询。依据工具返回的事实作答，不能把待确认说成已执行。"
)
MAX_ROUNDS = 4
MAX_CALLS = 8
# 这些业务动作即使上游漏标 write，也只能请求确认。
CONFIRM_ONLY = {"enterprise.propose_update", "meeting.commit_todos", "document.draft", "document.submit"}
FAILURE_REASONS = {
    "FORBIDDEN": "当前账号没有权限",
    "UNAUTHENTICATED": "登录已失效",
    "APP_UNAVAILABLE": "应用暂不可用",
    "NOT_FOUND": "没有找到目标资源",
    "TOOL_NOT_FOUND": "当前没有可用的此项工具",
    "INVALID_REQUEST": "工具参数不正确",
    "CHECK_FAILED": "工具参数或业务校验未通过",
    "TIMEOUT": "工具响应超时",
}
NO_SOURCE = "知识库里没有找到能回答这个问题的原文。"
NO_MODEL = "模型暂不可用，无法完成这次对话。"


@dataclass
class Reply:
    deltas: list[str] = field(default_factory=list)
    cards: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    intent: str | None = None
    model: str | None = None
    route_note: str | None = None

    def say(self, text: str) -> None:
        self.deltas.extend(text[i:i + 48] for i in range(0, len(text), 48))

    def fields(self) -> dict:
        return {
            "content": "".join(self.deltas), "cards": self.cards, "citations": self.citations,
            "toolCalls": self.tool_calls, "intent": self.intent, "model": self.model,
            "routeNote": self.route_note,
        }


def _tool_directory(items: list[dict], app: str | None) -> dict[str, dict]:
    return {
        item["name"]: item for item in items
        if isinstance(item.get("name"), str)
        and bool(item["name"].partition(".")[2])
        and item["name"].partition(".")[0] == item.get("app")
        and type(item.get("write")) is bool
        and (app is None or item["app"] == app)
        and (item["app"] != "kb" or item["name"] == "kb.ask")
    }


def _failure(exc: Exception) -> str:
    code = getattr(exc, "code", getattr(exc, "kind", ""))
    if isinstance(code, str) and code.upper() in FAILURE_REASONS:
        return FAILURE_REASONS[code.upper()]
    if isinstance(exc, TimeoutError):
        return FAILURE_REASONS["TIMEOUT"]
    return {401: "登录已失效", 403: "当前账号没有权限", 404: "没有找到目标资源"}.get(
        getattr(exc, "status_code", None), "工具服务暂不可用"
    )


def _knowledge(result: dict) -> tuple[str, list[dict]]:
    confidence = result.get("confidence")
    if confidence == "none":
        return NO_SOURCE, []
    if confidence not in ("high", "mid", "low"):
        raise ValueError("知识库置信度无效")
    hits = result.get("citations")
    answer = result.get("answer")
    if not isinstance(hits, list) or not hits or not isinstance(answer, str) or not answer.strip():
        raise ValueError("知识库结果缺少回答或原文出处")
    citations = []
    for hit in hits:
        values = [hit[key] for key in ("id", "title", "snippet")]
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError("知识库出处格式无效")
        citations.append(dict(zip(("fileId", "name", "snippet"), values)))
    return answer, citations


def _error(reply: Reply, entry: dict, reason: str) -> None:
    entry["status"] = "error"
    reply.say(f"未能完成请求，{reason}。")


def _pending(reply: Reply, entry: dict, result: dict) -> None:
    entry["status"] = "pending"
    if isinstance(result.get("reviewId"), str):
        entry["reviewId"] = result["reviewId"]
    reply.say("这项操作需要你确认。")


async def _execute(
    request: Request, bridge: ToolBridge | None, directory: dict, call: ToolCall, reply: Reply,
) -> tuple[dict | None, str]:
    entry = {"tool": call.tool, "args": call.args, "status": "ok"}
    reply.tool_calls.append(entry)
    reply.intent = reply.intent or call.app
    if bridge is None or call.tool not in directory:
        _error(reply, entry, FAILURE_REASONS["TOOL_NOT_FOUND"])
        return None, ""
    if directory[call.tool]["write"] or call.tool in CONFIRM_ONLY:
        # T21 只在会话中保存待确认记录。后续确认执行入口负责复核授权与参数。
        _pending(reply, entry, {})
        return None, ""
    try:
        response = await bridge.call_from_chat(request, call.app, call.tool, call.args)
    except Exception as exc:
        _error(reply, entry, _failure(exc))
        return None, ""
    try:
        result = response["result"]
        if not isinstance(result, dict) or "error" in result or result.get("ok") is False:
            raise ValueError("工具结果无效")
        encode(result).encode("utf-8")
        # 工具在目录读取后被改成写操作时，T16 的对话入口仍会阻止执行。
        if result.get("status") == "pending":
            _pending(reply, entry, result)
            return None, ""
        if call.tool == "kb.ask":
            answer, citations = _knowledge(result)
            if citations:
                reply.cards.append(render_card(call, result))
                reply.citations.extend(citations)
            reply.say(answer)
            return None, ""
        if card := render_card(call, result):
            reply.cards.append(card)
        text = next((
            result[key] for key in ("text", "message", "answer")
            if isinstance(result.get(key), str) and result[key].strip()
        ), "")
        return result, text
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        _error(reply, entry, "工具返回了无法使用的结果")
    return None, ""


def _with_context(call: ToolCall, history: list[dict]) -> ToolCall | None:
    if call.tool != "policy.match" or "overrides" not in call.args:
        return call
    for message in reversed(history):
        if message["role"] != "assistant" or message.get("incomplete"):
            continue
        for previous in reversed(message.get("toolCalls", [])):
            if previous.get("tool") == "policy.match" and previous.get("status", "ok") == "ok":
                if ent_id := previous.get("args", {}).get("entId"):
                    return ToolCall(call.tool, {**call.args, "entId": ent_id})
        break
    return None


def _tool_message(call: ToolCall, result: dict, call_id: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": encode(result)}


async def respond(
    request: Request, user, *, text: str, app: str | None, model: str | None,
    history: list[dict], gateway: ModelGateway | None, bridge: ToolBridge | None,
    classification: Classification,
) -> Reply:
    reply = Reply(intent=app)
    if app == "kb":
        selection = ToolCall("kb.ask", {"q": text})
    else:
        selection = match_rule(text) if app is None else None
    try:
        items = (await run_in_threadpool(bridge.tools, user))["items"] if bridge else []
        directory = _tool_directory(items, app)
    except Exception as exc:
        if selection:
            entry = {"tool": selection.tool, "args": selection.args}
            reply.tool_calls.append(entry)
            reply.intent = selection.app
            _error(reply, entry, _failure(exc))
        else:
            reply.say("工具目录暂不可用，请稍后重试。")
        return reply
    if selection:
        reply.intent = selection.app
        if call := _with_context(selection, history):
            result, summary = await _execute(request, bridge, directory, call, reply)
            if result is not None:
                reply.say(summary or ("查询结果见卡片。" if reply.cards else "工具已完成处理。"))
        else:
            reply.say("请先告诉我为哪家企业核对政策。")
        return reply
    if gateway is None:
        reply.say(NO_MODEL)
        return reply

    recent = [message for message in history if not message.get("incomplete")]
    messages = [{"role": "system", "content": SYSTEM}]
    messages.extend({"role": message["role"], "content": message["content"]} for message in recent)
    messages.append({"role": "user", "content": text})
    if any(message.get("toolCalls") for message in recent):
        classification = "confidential"
    used_ids = set()
    for round_number in range(MAX_ROUNDS):
        try:
            turn = await gateway(
                request, messages=list(messages), tools=sorted(directory),
                model=model, classification=classification,
            )
            encode([turn.deltas, turn.model, turn.route_note]).encode("utf-8")
        except Exception:
            reply.say(NO_MODEL)
            return reply
        reply.model, reply.route_note = turn.model, turn.route_note
        if not turn.calls:
            if not any(delta.strip() for delta in turn.deltas):
                reply.say("模型没有返回回复。")
            else:
                reply.deltas.extend(turn.deltas)
            return reply
        ids = [call.id or f"call-{round_number}-{i}" for i, call in enumerate(turn.calls)]
        if (len(reply.tool_calls) + len(turn.calls) > MAX_CALLS
                or len(set(ids)) != len(ids) or used_ids.intersection(ids)):
            break
        used_ids.update(ids)
        try:
            for call in turn.calls:
                if not isinstance(call.tool, str) or not isinstance(call.args, dict):
                    raise ValueError("工具名称或参数格式无效")
                encode([call.tool, call.args, call.id]).encode("utf-8")
        except (TypeError, ValueError):
            reply.say("模型没有返回可用的工具参数。")
            return reply
        messages.append({
            "role": "assistant", "content": None,
            "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": call.tool, "arguments": encode(call.args)}}
                for call, call_id in zip(turn.calls, ids)
            ],
        })
        for call, call_id in zip(turn.calls, ids):
            result, _ = await _execute(request, bridge, directory, call, reply)
            if result is None:
                return reply
            messages.append(_tool_message(call, result, call_id))
        # 业务结果可能带企业台账或未公开公文，下一轮统一由网关走本地路由。
        classification = "confidential"
    reply.say("已达到本轮工具调用上限，请缩小请求范围后重试。")
    return reply

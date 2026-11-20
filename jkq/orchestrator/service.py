"""按规则与模型执行一轮对话，使用同一个按请求人授权的工具目录。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from jkq.conversations.store import encode

from .cards import render_card
from .classification import Classification
from .ports import MetaSink, ModelGateway, ToolBridge, ToolCall
from .rules import follows_knowledge_question, is_small_talk, kb_command, match_rule

SYSTEM = (
    "按用户需求使用可用工具。知识、政策或原文问题必须先调用 kb.ask；"
    "若工具不可用，请说明无法查询。依据工具返回的事实作答，不能把待确认说成已执行。"
)
MAX_ROUNDS = 4
MAX_CALLS = 8
# 这些业务动作即使上游漏标 write，也只能请求确认。
CONFIRM_ONLY = {"enterprise.propose_update", "meeting.commit_todos", "document.draft", "document.submit", "kb.import"}
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
KB_UNAVAILABLE = "知识库暂时无法提供有出处的回答，请稍后再试。"
NO_MODEL = "模型暂不可用，无法完成这次对话。"
EventSink = Callable[[str, dict], Awaitable[None]]


class ModelStreamError(RuntimeError):
    """网关在已发送文本后中断或改变了本轮的结果类型。"""


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


def _tool_directory(items: list[dict], app: str | None, *, kb_action: bool) -> dict[str, dict]:
    return {
        item["name"]: item for item in items
        if isinstance(item.get("name"), str)
        and bool(item["name"].partition(".")[2])
        and item["name"].partition(".")[0] == item.get("app")
        and type(item.get("write")) is bool
        and (app is None or item["app"] == app)
        and item["name"] != "kb.search"  # 对话中的知识检索统一使用带归因的入口。
        and not (kb_action and item["name"] == "kb.ask")
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
    outcome = result.get("outcome")
    confidence = result.get("confidence")
    hits = result.get("citations")
    if outcome == "no_match" and confidence == "none" and hits == []:
        return NO_SOURCE, []
    if outcome != "answered" or confidence not in ("high", "mid", "low"):
        raise ValueError("知识库置信度无效")
    if not isinstance(hits, list) or not hits:
        raise ValueError("知识库结果缺少回答或原文出处")
    citations = []
    excerpts = []
    for number, hit in enumerate(hits, 1):
        file_id, title, snippet = (hit[key] for key in ("id", "title", "snippet"))
        if (type(hit.get("n")) is not int or hit["n"] != number
                or not all(isinstance(value, str) and value.strip() for value in (file_id, title, snippet))):
            raise ValueError("知识库出处格式无效")
        citations.append({"fileId": file_id, "name": title, "snippet": snippet})
        excerpts.append(f"“{snippet}”[{number}]")
    answer = "\n".join(excerpts)
    if result.get("answer") != answer:
        raise ValueError("回答和知识库引用不一致")
    return answer, citations


async def _execute(
    request: Request, bridge: ToolBridge | None, directory: dict, call: ToolCall, reply: Reply,
    classification: Classification,
) -> tuple[dict | None, str]:
    if call.tool == "kb.ask":
        # 模型只能提供问题正文，不能在业务参数或回执中留下伪造的密级。
        call = ToolCall(call.tool, {key: value for key, value in call.args.items() if key == "q"})
    entry = {"tool": call.tool, "args": call.args, "status": "ok"}
    reply.tool_calls.append(entry)
    reply.intent = reply.intent or call.app

    def reject(reason):
        entry["status"] = "error"
        reply.say(f"未能完成请求，{reason}。")
        return None, ""

    if call.tool == "document.submit" and not str(call.args.get("id") or "").strip():
        entry["status"] = "skipped"
        reply.say("请先告诉我需要送审签的草稿编号。")
        return None, ""
    if bridge is None or call.tool not in directory:
        return reject(FAILURE_REASONS["TOOL_NOT_FOUND"])
    write = directory[call.tool]["write"]
    if call.tool in CONFIRM_ONLY and not write:
        return reject("工具尚未配置审签")
    if call.tool == "kb.ask":
        question = call.args.get("q")
        if not isinstance(question, str) or not question.strip():
            return reject(FAILURE_REASONS["INVALID_REQUEST"])
        if write or not callable(getattr(bridge, "ask_from_chat", None)):
            return reject("知识库暂不可用")
    try:
        if call.tool == "kb.ask":
            response = {"result": await bridge.ask_from_chat(request, question, classification=classification)}
        else:
            response = await bridge.call_from_chat(request, call.app, call.tool, call.args)
    except ClientDisconnect:
        raise
    except Exception as exc:
        return reject(_failure(exc))
    try:
        result = response["result"]
        if not isinstance(result, dict) or "error" in result or result.get("ok") is False:
            raise ValueError("工具结果无效")
        encode(result).encode("utf-8")
        if call.tool == "kb.ask":
            if result.get("outcome") == "unavailable":
                entry["status"] = "error"
                reply.say(KB_UNAVAILABLE)
                return None, ""
            answer, citations = _knowledge(result)
            if citations:
                reply.cards.append(render_card(call, result))
                reply.citations.extend(citations)
            reply.say(answer)
            return None, ""
        if result.get("status") == "pending":
            review_id = result.get("reviewId")
            if not isinstance(review_id, str) or not review_id.strip():
                raise ValueError("工具结果缺少审签编号")
            entry.update(status="pending", reviewId=review_id)
            reply.say("这项操作需要你确认。")
            return None, ""
        if write:
            raise ValueError("写工具未返回待确认结果")
        if card := render_card(call, result):
            reply.cards.append(card)
        text = next((
            result[key] for key in ("text", "message", "answer")
            if isinstance(result.get(key), str) and result[key].strip()
        ), "")
        return result, text
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return reject("工具返回了无法使用的结果")


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


def _tool_message(result: dict, call_id: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": encode(result)}


async def respond(
    request: Request, user, *, text: str, app: str | None, model: str | None,
    history: list[dict], gateway: ModelGateway | None, bridge: ToolBridge | None,
    classification: Classification, on_event: EventSink | None = None, on_meta: MetaSink | None = None,
) -> Reply:
    reply = Reply(intent=app)
    recent = [message for message in history if not message.get("incomplete")]
    last_reply = next((message for message in reversed(recent) if message["role"] == "assistant"), {})
    small_talk = app != "kb" and is_small_talk(text)
    kb_action = app == "kb" and kb_command(text)
    selection = match_rule(text) if app is None else None
    previous_question = next((
        entry.get("args", {}).get("q") for entry in last_reply.get("toolCalls", [])
        if entry.get("tool") == "kb.ask"
    ), None)
    followup = (app in (None, "kb") and not kb_action and previous_question
                and follows_knowledge_question(text))
    question = f"{previous_question}\n{text}" if followup else text
    if app == "kb":
        selection = None if kb_action else ToolCall("kb.ask", {"q": question})
    elif followup and (selection is None or selection.tool == "kb.ask"):
        selection = ToolCall("kb.ask", {"q": question})
    try:
        items = (await run_in_threadpool(bridge.tools, user))["items"] if bridge and not small_talk else []
        directory = _tool_directory(items, app, kb_action=kb_action)
    except Exception as exc:
        if selection:
            entry = {"tool": selection.tool, "args": selection.args}
            reply.tool_calls.append(entry)
            reply.intent = selection.app
            entry["status"] = "error"
            reply.say(f"未能完成请求，{_failure(exc)}。")
            if on_event is not None:
                await on_event("tool", entry)
        else:
            reply.say("工具目录暂不可用，请稍后重试。")
        return reply

    async def execute(call: ToolCall) -> tuple[dict | None, str]:
        result = await _execute(request, bridge, directory, call, reply, classification)
        if on_event is not None:
            await on_event("tool", reply.tool_calls[-1])
        return result

    if selection:
        reply.intent = selection.app
        if call := _with_context(selection, history):
            result, summary = await execute(call)
            if result is not None:
                reply.say(summary or ("查询结果见卡片。" if reply.cards else "工具已完成处理。"))
        else:
            reply.say("请先告诉我为哪家企业核对政策。")
        return reply

    async def finish_without_model_text(summaries: list[str]) -> Reply:
        for summary in dict.fromkeys(summaries):
            reply.say(summary)
        if not summaries:
            if app is None:
                await execute(ToolCall("kb.ask", {"q": text}))
            else:
                reply.say("请说明要在当前应用中查询或办理的事项。")
        return reply

    if gateway is None:
        if small_talk or app is not None:
            reply.say(NO_MODEL)
            return reply
        return await finish_without_model_text([])

    messages = [{"role": "system", "content": SYSTEM}]
    messages.extend({"role": message["role"], "content": message["content"]} for message in recent)
    messages.append({"role": "user", "content": text})
    used_ids = set()
    summaries: list[str] = []

    async def delta(text: str) -> None:
        if text:
            text.encode("utf-8")
            await on_event("delta", {"text": text})
            reply.deltas.append(text)

    for round_number in range(MAX_ROUNDS):
        prior_deltas = len(reply.deltas)
        announced: tuple[str | None, str | None] = (None, None)

        async def announce(model_name: str | None, route_note: str | None) -> None:
            nonlocal announced
            encode([model_name, route_note]).encode("utf-8")
            announced = (model_name, route_note)
            if on_meta is not None:
                await on_meta(*announced)

        try:
            turn = await gateway(
                request, messages=list(messages), tools=sorted(directory),
                model=model, classification=classification,
                on_delta=delta if small_talk and on_event is not None else None,
                on_meta=announce if on_meta is not None else None,
            )
            if not all(isinstance(text, str) for text in turn.deltas):
                raise ValueError("模型回复的文本增量无效")
            encode([turn.deltas, turn.model, turn.route_note]).encode("utf-8")
        except ClientDisconnect:
            raise
        except Exception as exc:
            if len(reply.deltas) > prior_deltas:
                raise ModelStreamError() from exc
            if summaries or (app is None and not small_talk):
                return await finish_without_model_text(summaries)
            reply.say(NO_MODEL)
            return reply
        reply.model = turn.model if turn.model is not None else announced[0]
        reply.route_note = turn.route_note if turn.route_note is not None else announced[1]
        if len(reply.deltas) > prior_deltas:
            if turn.calls or turn.deltas:
                raise ModelStreamError()
            return reply
        if on_meta is not None and (reply.model is not None or reply.route_note is not None):
            await on_meta(reply.model, reply.route_note)
        if not turn.calls:
            # 可能涉及事实的请求只发布服务端检索或已授权工具的结果。
            # 模型用于选择和串联工具，这类轮次从未获得直接发送 delta 的回调。
            if not small_talk:
                return await finish_without_model_text(summaries)
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
        stop = False
        for call, call_id in zip(turn.calls, ids):
            result, summary = await execute(call)
            if result is None:
                stop = True
            else:
                summaries.append(summary or ("查询结果见卡片。" if reply.cards else "工具已完成处理。"))
                messages.append(_tool_message(result, call_id))
        if stop:
            for summary in dict.fromkeys(summaries):
                reply.say(summary)
            return reply
        # 业务结果可能带企业台账或未公开公文，下一轮统一由网关走本地路由。
        classification = "confidential"
    reply.say("已达到本轮工具调用上限，请缩小请求范围后重试。")
    return reply

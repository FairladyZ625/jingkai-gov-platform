"""OpenAI 兼容消息与流式分片解析，仅透出平台约定字段。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import partial
from threading import Event
from typing import Callable

from anyio import create_task_group, sleep
from anyio.lowlevel import checkpoint

from .errors import AIError, transport_error


def _object(value):
    if not isinstance(value, dict):
        raise ValueError("必须是 JSON 对象。")
    return value


def _list(value):
    if not isinstance(value, list):
        raise ValueError("必须是 JSON 数组。")
    return value


def _text(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("必须是文本。")
    value.encode("utf-8")
    return value


def _tool_call(function, names):
    name = _text(function["name"])
    if not name.strip():
        raise ValueError("工具名称不能为空。")
    arguments = _object(json.loads(_text(function["arguments"])))
    # SSE 和 JSON 响应都以 UTF-8 编码。直接拒绝无法编码的值及非有限数。
    json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return {"name": names.get(name, name), "arguments": arguments}


def normalize_message(message, names):
    message = _object(message)
    content = _text(message.get("content"))
    raw_calls = message.get("tool_calls")
    calls = [] if raw_calls is None else _list(raw_calls)
    tool_calls = []
    for call in calls:
        call = _object(call)
        if call.get("type", "function") != "function":
            raise ValueError("工具调用类型无效。")
        tool_calls.append(_tool_call(_object(call["function"]), names))
    if not content.strip() and not tool_calls:
        raise ValueError("模型消息为空。")
    return {"content": content, "tool_calls": tool_calls}


def normalize_usage(usage):
    usage = usage if isinstance(usage, dict) else {}
    result = {}
    for key, source in (("input", "prompt_tokens"), ("output", "completion_tokens")):
        value = usage.get(source)
        result[key] = value if type(value) is int and value >= 0 else None
    return result


@dataclass
class ConversationStream:
    on_event: Callable[[str, str, str, dict], None]
    cancelled: Event
    started: bool = False

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise AIError("timeout", "本轮已中断。")

    def send(self, provider_id, model, kind, data):
        self.check_cancelled()
        # Gateway._attempt 读取 started，防止把其他候选的回答接在已发事件后面。
        self.started = True
        self.on_event(provider_id, model, kind, data)

    async def run(self, operation, *args):
        self.check_cancelled()
        error = None
        async with create_task_group() as group:
            group.start_soon(self._watch_cancellation, group.cancel_scope)
            try:
                result = await operation(*args)
            except Exception as exc:
                error = exc
            finally:
                group.cancel_scope.cancel()
        self.check_cancelled()
        if error is not None:
            raise error
        return result

    async def _watch_cancellation(self, scope):
        while not self.cancelled.is_set():
            await sleep(0.1)
        scope.cancel()


async def sse_chunks(response):
    """按空行提交完整 SSE 帧，EOF 时丢弃未闭合的帧。"""
    response.encoding = "utf-8-sig"
    pending = []
    async for line in response.aiter_lines():
        await checkpoint()
        if not line:
            if pending:
                data = "\n".join(pending)
                pending.clear()
                yield "[DONE]" if data.strip() == "[DONE]" else json.loads(data)
        elif line == "data" or line.startswith("data:"):
            pending.append(line.partition(":")[2].removeprefix(" "))


class _MessageParts:
    def __init__(self, names):
        self.names = names
        self.text = []
        self.fragments = {}
        self.tool_calls = []
        self.finished = False

    def add(self, delta):
        text = _text(delta.get("content"))
        if text:
            self.text.append(text)
        fragments = delta.get("tool_calls")
        if fragments is not None:
            for fragment in _list(fragments):
                self._add_tool(_object(fragment))
        return text

    def _add_tool(self, fragment):
        index = fragment["index"]
        if type(index) is not int or index < 0 or fragment.get("type") not in (None, "function"):
            raise ValueError("工具分片格式无效。")
        function = fragment.get("function")
        function = {} if function is None else _object(function)
        parts = self.fragments.setdefault(index, {"name": [], "arguments": []})
        for field in ("name", "arguments"):
            piece = _text(function.get(field))
            if piece:
                parts[field].append(piece)

    def finish(self, emit):
        if self.finished:
            return
        self.tool_calls = [
            _tool_call({field: "".join(pieces) for field, pieces in fragments.items()}, self.names)
            for _, fragments in sorted(self.fragments.items())
        ]
        self.finished = True
        for call in self.tool_calls:
            emit("tool", {"tool": call["name"], "args": call["arguments"]})


async def read_chunks(chunks, stream, provider_id, model, names, *, usage=None):
    parts = _MessageParts(names)
    emit = partial(stream.send, provider_id, model)
    usage = normalize_usage(None) if usage is None else usage
    try:
        async for chunk in chunks:
            await checkpoint()
            stream.check_cancelled()
            if chunk == "[DONE]":
                parts.finish(emit)
                stream.check_cancelled()
                content = "".join(parts.text)
                if not content.strip() and not parts.tool_calls:
                    raise ValueError("模型消息为空。")
                return {"content": content, "tool_calls": parts.tool_calls, "usage": usage}
            chunk = _object(chunk)
            if "error" in chunk:
                raise ValueError("模型报告流式错误。")
            if chunk.get("usage") is not None:
                usage = normalize_usage(chunk["usage"])
            for choice in _list(chunk["choices"]):
                choice = _object(choice)
                index = choice.get("index", 0)
                if type(index) is not int or index < 0:
                    raise ValueError("消息分片序号无效。")
                if index != 0:
                    continue
                if parts.finished:
                    raise ValueError("结束后仍收到对话分片。")
                delta = choice.get("delta")
                text = parts.add(_object(delta) if delta is not None else {})
                if text:
                    emit("delta", {"text": text})
                if _text(choice.get("finish_reason")):
                    parts.finish(emit)
    except (KeyError, TypeError, ValueError, RecursionError):
        raise AIError("provider_error", "模型服务商流式响应格式无效。") from None
    stream.check_cancelled()
    raise transport_error("模型流在完成前中断，已收到的进展已保留。")

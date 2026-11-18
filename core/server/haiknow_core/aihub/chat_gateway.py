"""完整消息入口，沿用平台网关的路由和结算。"""
from __future__ import annotations

import re

import httpx
from anyio import fail_after

from .chat_stream import (
    ConversationStream,
    normalize_message,
    normalize_usage,
    read_chunks,
    sse_chunks,
)
from .errors import AIError, TRANSPORT_ERRORS, transport_error
from .providers.jkq_chat import ChatGateway, ProviderRejected


FUNCTION_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
STREAM_TIMEOUT = 25


def _named_functions(request):
    for tool in request.get("tools", []):
        yield tool["function"]
    for message in request["messages"]:
        if message.get("role") in ("tool", "function") and "name" in message:
            yield message
        for call in message.get("tool_calls") or []:
            yield call["function"]


def _provider_payload(payload, model, streaming):
    # 只复制会改写名称的容器。消息内容、参数和 JSON Schema 原样透传。
    request = {"model": model, "stream": streaming, "messages": []}
    for message in payload["messages"]:
        copy = dict(message)
        if message.get("tool_calls") is not None:
            copy["tool_calls"] = [
                {**call, "function": dict(call["function"])} for call in message["tool_calls"]
            ]
        request["messages"].append(copy)
    if payload.get("tools") is not None:
        request["tools"] = [
            {**tool, "function": dict(tool["function"])} for tool in payload["tools"]
        ]
    if payload.get("temperature") is not None:
        request["temperature"] = payload["temperature"]

    functions = list(_named_functions(request))
    names = dict.fromkeys(function["name"] for function in functions)
    used = {name for name in names if FUNCTION_NAME.fullmatch(name)}
    aliases = {}
    index = 0
    for name in names:
        if name in used:
            continue
        index += 1
        while f"tool_{index}" in used:
            index += 1
        alias = f"tool_{index}"
        aliases[name] = alias
        used.add(alias)
    for function in functions:
        name = function["name"]
        function["name"] = aliases.get(name, name)
    return request, {alias: name for name, alias in aliases.items()}


def _check_status(response):
    if response.status_code >= 500:
        raise AIError("provider_error", "模型服务商暂时不可用。")
    if not response.is_success:
        raise ProviderRejected("模型服务商拒绝了请求。")


async def _request(provider, model, payload, timeout, transport, stream):
    try:
        request, names = _provider_payload(payload, model, stream is not None)
    except (KeyError, TypeError, ValueError):
        raise AIError("bad_input", "对话工具定义或历史调用格式无效。") from None

    api_key = provider.get("api_key")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = provider["base_url"] + "/chat/completions"
    async with httpx.AsyncClient(
        timeout=timeout, transport=transport, trust_env=False, follow_redirects=False,
    ) as client:
        if stream is not None:
            async with client.stream("POST", url, headers=headers, json=request) as response:
                _check_status(response)
                return await read_chunks(sse_chunks(response), stream, provider["id"], model, names)

        response = await client.post(url, headers=headers, json=request)
        _check_status(response)
        try:
            body = response.json()
            message = normalize_message(body["choices"][0]["message"], names)
        except (KeyError, IndexError, TypeError, ValueError, RecursionError):
            raise ProviderRejected("模型服务商返回的消息格式无效。") from None
        return {**message, "usage": normalize_usage(body.get("usage"))}


async def _mock_chunks(chunks):
    for chunk in chunks:
        yield chunk


class ConversationGateway(ChatGateway):
    """提供完整消息和结构化增量，兼容现有候选与审计入口。"""

    def __init__(self, settings, audit, candidates, record_attempt, transport=None):
        def audit_gateway(app_id, actor, action, detail):
            # 新版 core 也会记成功摘要。模型尝试由 record_attempt 统一记录。
            if action != "ai.chat":
                audit(app_id, actor, action, detail)

        super().__init__(
            settings, audit_gateway if audit is not None else None, candidates, record_attempt, transport,
        )

    def call_message(self, app_id, payload, *, principal, timeout=50):
        return self._call_message(app_id, payload, principal, timeout)

    def chat_message(self, app_id, payload, *, principal, timeout=50):
        result = self.call_message(app_id, payload, principal=principal, timeout=timeout)["result"]
        return {"content": result["content"], "tool_calls": result["tool_calls"]}

    def stream_message(self, app_id, payload, *, principal, on_event, cancelled, timeout=STREAM_TIMEOUT):
        stream = ConversationStream(on_event, cancelled)
        return self._call_message(app_id, payload, principal, timeout, stream)

    def _call_message(self, app_id, payload, principal, timeout, stream=None):
        try:
            return self.call(app_id, "chat", payload, timeout, principal=principal, _stream=stream)
        except ProviderRejected as error:
            raise AIError("provider_error", str(error)) from None

    async def _attempt(self, candidates, capability, payload, file, timeout, legacy,
                       decoded_audio=None, stream=None):
        if stream is not None:
            timeout = min(timeout, STREAM_TIMEOUT)
        return await super()._attempt(
            candidates, capability, payload, file, timeout, legacy, decoded_audio, stream,
        )

    async def _invoke(self, provider, model, capability, payload, file, timeout, deadline,
                      decoded_audio=None, stream=None):
        attempt_timeout = min(12, timeout / (len(self.candidates) + 1))
        status = "interrupted"
        usage = normalize_usage(None)
        mock = provider["kind"] == "mock"
        try:
            with fail_after(attempt_timeout):
                if mock:
                    result = await self._mock_message(provider, model, capability, payload, file, stream)
                elif stream is None:
                    result = await _request(provider, model, payload, attempt_timeout, self.transport, None)
                else:
                    result = await stream.run(
                        _request, provider, model, payload, attempt_timeout, self.transport, stream,
                    )
            status = "success"
            usage = result["usage"]
            return {**result, "mock": mock}
        except ProviderRejected:
            status = "provider_error"
            raise
        except (TimeoutError, httpx.TimeoutException):
            status = "timeout"
            raise AIError("timeout", "模型调用超时。") from None
        except (httpx.TransportError, *TRANSPORT_ERRORS):
            status = "provider_error"
            raise transport_error("模型服务连接中断。") from None
        except (httpx.DecodingError, httpx.InvalidURL):
            status = "provider_error"
            raise ProviderRejected("模型服务商接入地址或响应编码无效。") from None
        except AIError as error:
            status = error.kind
            raise
        finally:
            self.record_attempt(provider["id"], model, status, usage)

    async def _mock_message(self, provider, model, capability, payload, file, stream):
        usage = {"input": 0, "output": 0}
        script = provider.get("mock_script")
        if stream is not None:
            stream.check_cancelled()
            if script is not None:
                if not isinstance(script, dict) or not isinstance(script.get("chunks"), list):
                    raise AIError("provider_error", "模拟模型的流式脚本格式无效。")
                return await read_chunks(
                    _mock_chunks(script["chunks"]), stream, provider["id"], model, {}, usage=usage,
                )

        if script is None:
            message = {"content": self._mock(provider, capability, payload, file, model), "tool_calls": []}
        else:
            try:
                message = normalize_message(script["message"], {})
            except (KeyError, TypeError, ValueError, RecursionError):
                raise ProviderRejected("模拟模型的消息脚本格式无效。") from None
        if stream is not None:
            stream.send(provider["id"], model, "delta", {"text": message["content"]})
            stream.check_cancelled()
        return {**message, "usage": usage}

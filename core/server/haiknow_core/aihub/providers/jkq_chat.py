"""经开区文本对话 provider，供实例网关和本地冒烟共用。"""

import ipaddress
import math
import os
import re
from pathlib import Path
from threading import BoundedSemaphore
from time import monotonic
from typing import Annotated, Literal, Optional

import httpx
import yaml
from anyio import create_task_group, fail_after, run, sleep
from pydantic import BaseModel, ConfigDict, StrictBool, StringConstraints

from .. import codex, streaming
from ..errors import AIError, TRANSPORT_ERRORS, transport_error
from ..gateway import Gateway, allowed_outbound


DEFAULT_CONFIG = Path(__file__).resolve().parents[5] / "config/models.yaml"
SMOKE_PROMPT = "这是公开的模型连接测试。只回复四个字：冒烟通过。"


class ProviderRejected(RuntimeError):
    """永久拒绝或无效文本，让 Gateway 停止回退。"""


class ProviderDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    kind: Literal["openai", "deepseek", "mock", "codex-cli"]
    group: Literal["推荐", "国产云端", "本地部署", "海外模型（默认关闭）"]
    provider: str
    env: Optional[str] = None
    name: Optional[str] = None
    enabled: StrictBool = True


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    models: list[ProviderDefinition]
    confidential_providers: set[str]


def load_config(path=DEFAULT_CONFIG):
    config = ModelConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    ids = {model.id for model in config.models}
    if any(model.kind == "mock" and not (model.name or "").strip() for model in config.models):
        raise ValueError("模拟模型必须配置展示名称。")
    if "auto" in ids or len(ids) != len(config.models):
        raise ValueError("模型配置含重复或保留的模型标识。")
    local_ids = {model.id for model in config.models
                 if model.group == "本地部署" and model.kind in ("openai", "deepseek")}
    if not config.confidential_providers <= local_ids:
        raise ValueError("敏感资料白名单只可登记本地部署的服务商。")
    return config


def _approval_endpoint(value):
    """仅接受无歧义的审批地址；使用与发送相同的 HTTPX 端口和主机规范化。"""
    # 在 HTTPX 处理点段、转义和空查询等语法之前检查原文。
    match = re.fullmatch(
        r"(https?)://(\[[0-9a-f:.]+\]|[a-z0-9-]+(?:\.[a-z0-9-]+)*)"
        r"(?::([0-9]+))?((?:/[a-z0-9._~-]+)*/?)", value, re.ASCII | re.IGNORECASE,
    )
    if not match or any(part in {".", ".."} for part in match[4].split("/")):
        return None
    try:
        url = httpx.URL(value.rstrip("/"))
        if match[3] and not 1 <= int(match[3]) <= 65535:
            return None
        # 系统解析器可能把简写、十六进制或前导零的数字主机解释为 IPv4。
        if re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*", match[2], re.I):
            ipaddress.IPv4Address(match[2])
        port = url.port or (443 if url.scheme == "https" else 80)
        return url.scheme, url.raw_host, port, url.raw_path
    except (httpx.InvalidURL, ValueError):
        return None


def provider_from_environment(definition, confidential=False):
    if definition.kind == "mock":
        return {
            "id": definition.id, "kind": "mock", "model": definition.name,
            "allow_outbound": "internal",
        }
    if not definition.env:
        return None
    if definition.kind == "codex-cli":
        return _codex_provider(definition)
    configured_url = os.getenv(f"{definition.env}_BASE_URL", "")
    base_url = configured_url.strip().rstrip("/")
    model = os.getenv(f"{definition.env}_NAME", "").strip() or definition.name
    api_key = os.getenv(f"{definition.env}_API_KEY", "").strip()
    local = definition.group == "本地部署"
    if not base_url or not model or (not local and not api_key):
        return None
    try:
        url = httpx.URL(base_url)
    except (httpx.InvalidURL, ValueError):
        raise ValueError(f"模型 {definition.id} 的接入地址无效。") from None
    if (
        url.scheme not in ({"http", "https"} if local else {"https"})
        or not url.host or url.userinfo or url.query or url.fragment
    ):
        raise ValueError(f"模型 {definition.id} 的接入地址无效。")
    approved = None
    if confidential:
        approved = _approval_endpoint(os.getenv(f"{definition.env}_CONFIDENTIAL_BASE_URL", ""))
    allows_confidential = approved is not None and approved == _approval_endpoint(configured_url)
    return {
        "id": definition.id, "kind": definition.kind, "model": model,
        "base_url": base_url, "api_key": api_key,
        "allow_outbound": "confidential" if allows_confidential else "internal",
    }


def _codex_provider(definition):
    prefix = definition.env
    if os.getenv(f"{prefix}_ENABLED") != "1":
        return None
    model = os.getenv(f"{prefix}_NAME", "").strip()
    if not model:
        raise ValueError(f"启用 Codex CLI 时必须设置 {prefix}_NAME。")
    try:
        timeout = float(os.getenv(f"{prefix}_TIMEOUT", "30"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except ValueError:
        raise ValueError(f"{prefix}_TIMEOUT 必须是有限的正数（秒）。") from None
    try:
        concurrency = int(os.getenv(f"{prefix}_MAX_CONCURRENCY", "2"))
        if concurrency <= 0:
            raise ValueError
    except ValueError:
        raise ValueError(f"{prefix}_MAX_CONCURRENCY 必须是正整数。") from None
    return {
        "id": definition.id, "kind": definition.kind, "model": model, "allow_outbound": "public",
        # 每个实例服务解析配置一次。请求各用独立 AnyIO portal，共享此线程信号量。
        "timeout": timeout, "slots": BoundedSemaphore(concurrency),
    }


async def openai_chat(base_url, api_key, model, payload, timeout, *, transport=None, message=False):
    """云端和内网均使用 OpenAI 兼容协议。"""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        with fail_after(timeout):
            async with httpx.AsyncClient(
                timeout=timeout, transport=transport, trust_env=False, follow_redirects=False,
            ) as client:
                response = await client.post(
                    base_url + "/chat/completions",
                    headers=headers,
                    json={**payload, "model": model},
                )
        if response.status_code >= 500:
            raise AIError("provider_error", "模型服务商暂时不可用。")
        if not response.is_success:
            raise ProviderRejected("模型服务商拒绝了请求。")
        body = response.json()
        reply = body["choices"][0]["message"]
        if message:
            result = streaming.chat_message(reply)
        else:
            result = reply["content"]
            if not isinstance(result, str) or not result.strip():
                raise ValueError("模型返回空文本。")
        return result, streaming.chat_usage(body.get("usage"))
    except (TimeoutError, httpx.TimeoutException):
        raise AIError("timeout", "模型调用超时。") from None
    except (httpx.TransportError, *TRANSPORT_ERRORS):
        raise transport_error("模型服务连接中断。") from None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        kind = "对话" if message else "文本"
        raise ProviderRejected(f"模型服务商返回的{kind}格式无效。") from None


class ChatGateway(Gateway):
    """沿用卫华 Gateway 的出站检查、调用顺序、配额与结算。"""

    def __init__(self, settings, audit, candidates, record_attempt, transport=None):
        super().__init__(settings, audit=audit)
        self.candidates = candidates
        self.record_attempt = record_attempt
        self.transport = transport

    def _route_candidates(self, capability, model=None):
        # 空候选也交给 Gateway.call，使 confidential 走统一的拒绝与审计路径。
        return self.candidates

    def _stream_route_note(self, provider, classification):
        first = next(p for p, _ in self.candidates if allowed_outbound(p, classification))
        notes = []
        if first != self.candidates[0][0]:
            notes.append("按密级切换到白名单模型")
        if provider != first:
            notes.append("主模型调用失败，已回退")
        if provider["kind"] == "mock":
            notes.append("使用模拟模型")
        return "，".join(notes)

    def _codex_timeout(self, provider, classification, deadline, attempt_timeout):
        remaining = deadline - monotonic()
        index = next(i for i, (candidate, _) in enumerate(self.candidates) if candidate is provider)
        if any(allowed_outbound(p, classification) for p, _ in self.candidates[index + 1:]):
            remaining -= min(attempt_timeout, remaining / 2)
        return min(provider["timeout"], remaining)

    async def _invoke(self, provider, model, capability, payload, file, timeout, deadline,
                      decoded_audio=None, stream=None):
        # 独立的尝试时限保留回退预算，避免主服务占完整个请求时限。
        attempt_timeout = min(12, timeout / (len(self.candidates) + 1))
        status = "interrupted"
        usage = {"input": None, "output": None}
        structured = isinstance(payload, streaming.ChatRequest)
        mock = provider["kind"] == "mock"
        try:
            if provider["kind"] == "codex-cli":
                classification = payload["classification"]
                with fail_after(self._codex_timeout(provider, classification, deadline, attempt_timeout)):
                    result = await _codex_reply(provider, model, payload, structured, stream)
                if stream is not None:
                    route_note = self._stream_route_note(provider, classification)
                    _emit_codex_reply(stream, model, route_note, result)
            elif structured and stream is not None:
                with fail_after(attempt_timeout):
                    result = await streaming.chat_events(
                        provider, model, payload, attempt_timeout, stream,
                        route_note=self._stream_route_note(provider, payload["classification"]),
                        transport=self.transport, trust_env=False,
                    )
                usage = result["usage"]
            elif mock:
                message = streaming.mock_message(provider) if structured else {"content": streaming.MOCK_CONTENT}
                result = streaming.chat_message(message) if structured else message
                usage = {"input": 0, "output": 0}
            else:
                request = {key: value for key, value in payload.items() if key != "classification"}
                reply, usage = await openai_chat(
                    provider["base_url"], provider["api_key"], model, request,
                    attempt_timeout, transport=self.transport, message=structured,
                )
                result = reply if structured else {"content": reply}
            status = "success"
            return {**result, "usage": usage, "mock": mock}
        except TimeoutError:
            status = "timeout"
            raise AIError("timeout", "模型调用超时。") from None
        except codex.InvalidToolReply as error:
            status = "provider_error"
            raise ProviderRejected(str(error)) from None
        except ProviderRejected:
            status = "provider_error"
            raise
        except AIError as error:
            status = error.kind
            raise
        finally:
            self.record_attempt(provider["id"], model, status, usage)


async def _cancel_codex_on_disconnect(cancelled, scope):
    while not cancelled.is_set():
        await sleep(0.1)
    scope.cancel()


async def _codex_reply(provider, model, payload, structured, stream):
    if stream is not None and stream.cancelled.is_set():
        raise AIError("timeout", "本轮已中断。")
    slots = provider["slots"]
    if not slots.acquire(blocking=False):
        raise AIError("quota_exceeded", "Codex CLI 并发已达上限，请稍后重试。")

    async def invoke():
        if structured:
            return await codex.chat_message(model, payload)
        return {"content": await codex.chat(model, payload)}

    try:
        if stream is None:
            return await invoke()
        failure = None
        async with create_task_group() as group:
            group.start_soon(_cancel_codex_on_disconnect, stream.cancelled, group.cancel_scope)
            try:
                result = await invoke()
            except Exception as error:
                failure = error
            finally:
                group.cancel_scope.cancel()
        if stream.cancelled.is_set():
            raise AIError("timeout", "本轮已中断。")
        if failure is not None:
            raise failure
        return result
    finally:
        slots.release()


def _emit_codex_reply(stream, model, route_note, reply):
    if stream.cancelled.is_set():
        raise AIError("timeout", "本轮已中断。")
    stream.send(("meta", {"model": model, "routeNote": route_note}))
    text = reply["content"] or ""
    for offset in range(0, len(text), 128):
        stream.send(("delta", {"text": text[offset:offset + 128]}))
    for call in reply["tool_calls"]:
        stream.send(("tool", call))


def codex_smoke(model=None):
    """仅用于本机固定公开文本冒烟，CLI 自行复用登录。"""
    async def invoke():
        with fail_after(90):
            return await codex.chat(model, {"messages": [{"role": "user", "content": SMOKE_PROMPT}]})

    try:
        return run(invoke)
    except TimeoutError:
        raise AIError("timeout", "Codex CLI 调用超时。") from None

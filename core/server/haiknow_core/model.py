"""应用的兼容模型接口。平台运行时将已配置路由交给能力网关。"""
from __future__ import annotations

import base64
import binascii
import math
import threading
from collections import Counter
from typing import Any

import httpx
from anyio import fail_after
from anyio.from_thread import start_blocking_portal

from haiknow_sdk import Files, ModelError

from .aihub import codex
from .aihub.config import ModelEnvironment, auth_headers, provider_available
from .aihub.errors import AIError

TOTAL_TIMEOUT = 50.0
ATTEMPT_TIMEOUT = 25.0


def _image_url(image: str, files: Files | None) -> str:
    if image.startswith("data:image/"):
        return image
    try:
        data = base64.b64decode(image, validate=True)
    except (ValueError, binascii.Error):
        if files is None:
            raise FileNotFoundError(image) from None
        data = files.read(image)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        mime = "image/gif"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ValueError("images 仅支持 PNG、JPEG、GIF 或 WebP 图片")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _with_images(messages: list[dict], images: list[str], files: Files | None) -> list[dict]:
    """给最后一条用户消息追加图片，不修改调用方持有的消息。"""
    result = list(messages)
    for index in range(len(result) - 1, -1, -1):
        message = result[index]
        if message.get("role") == "user":
            content = message["content"]
            parts = [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
            parts += [{"type": "image_url", "image_url": {"url": _image_url(img, files)}} for img in images]
            result[index] = {**message, "content": parts}
            return result
    raise ValueError("images 需要至少一条 user 消息")


class ModelGateway:
    def __init__(self) -> None:
        self.environment = ModelEnvironment.read()
        self._usage: dict[str, Counter] = {}
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        if hasattr(self, 'aihub') and self.aihub.settings.route('chat'):
            return self.chat_route() is not None
        return self.environment.ready()

    def chat_route(self):
        settings = self.aihub.settings
        route = settings.route('chat')
        if route:
            for provider_id, model in ((route['provider'], route['model']),
                                       (route['fallback_provider'], route['fallback_model'])):
                provider = settings.provider(provider_id)
                if provider_available(provider, model):
                    return provider, model
        return None

    def for_app(self, app_id: str, files: Files | None = None, principal=None) -> "AppModel":
        gateway = _BoundModelGateway(self, principal) if principal is not None else self
        return AppModel(gateway, app_id, files, principal)

    @property
    def calls(self) -> dict[str, int]:
        return {app_id: counts["total"] for app_id, counts in self.usage().items()}

    def usage(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {app_id: {key: counts[key] for key in ("total", "success", "failure", "mock")}
                    for app_id, counts in self._usage.items()}

    def _record(self, app_id: str, *, success: bool, mock: bool = False) -> None:
        with self._lock:
            counts = self._usage.setdefault(app_id, Counter())
            counts["total"] += 1
            counts["success" if success else "failure"] += 1
            counts["mock"] += int(mock)

    def chat(
        self, app_id: str, messages: list[dict], timeout: float = TOTAL_TIMEOUT, *,
        model: str | None = None, images: list[str] | None = None,
        _files: Files | None = None, _principal=None, **kw: Any,
    ) -> str:
        if hasattr(self, "aihub") and self.aihub.settings.route("chat"):
            try:
                if images:
                    messages = _with_images(messages, images, _files)
                result = self.aihub.call(app_id, "chat", {"messages": messages, **kw}, timeout,
                                         override_model=model, legacy=True, principal=_principal)["result"]
                self._record(app_id, success=True)
                return result
            except AIError as error:
                self._record(app_id, success=False)
                raise ModelError(getattr(error, "legacy_kind", error.kind), str(error), getattr(error, "status_code", None)) from None
            except Exception:
                self._record(app_id, success=False)
                raise
        config = self.environment
        mock = config.mode == 'mock'
        try:
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("timeout 必须是正的有限秒数")
            name = model if model and not config.explicit else config.model
            if not mock and not config.ready(name):
                raise ModelError("not_configured", "模型配置不完整，请联系管理员检查 HAIKNOW_MODEL_*。")
            if images:
                messages = _with_images(messages, images, _files)
            if mock:
                last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
                result = f"[模拟模型] 已收到 {len(str(last))} 字输入。配置 HAIKNOW_MODEL_* 后返回真实结果。"
            else:
                from .aihub.gateway import CLASSIFICATIONS, DEFAULT_CLASSIFICATION, allowed_outbound
                classification = kw.get('classification', DEFAULT_CLASSIFICATION)
                if classification not in CLASSIFICATIONS:
                    raise ModelError('bad_input', 'classification 只能是 public、internal 或 confidential。')
                provider = config.provider()
                if not allowed_outbound(provider, classification):
                    if hasattr(self, "aihub"):
                        self.aihub._deny(app_id, _principal, 'chat', classification)
                    raise ModelError('outbound_denied', '没有允许向外出站此分类资料的服务商。')
                # 独立事件循环可取消慢响应，且兼容同步与异步路由里的同步 chat 调用。
                with start_blocking_portal() as portal:
                    options = {key: value for key, value in kw.items() if key != 'classification'}
                    result = portal.call(self._request, provider, messages, name, min(timeout, TOTAL_TIMEOUT), options)
        except AIError as error:
            self._record(app_id, success=False)
            raise ModelError(error.kind, str(error)) from None
        except Exception:
            self._record(app_id, success=False)
            raise
        self._record(app_id, success=True, mock=mock)
        return result

    async def _request(self, provider, messages: list[dict], name: str, timeout: float, kw: dict) -> str:
        try:
            with fail_after(timeout):  # 覆盖建连、读写、慢速分块和重试的总预算
                if provider['kind'] == 'codex-cli':
                    return await codex.chat(name, {**kw, 'messages': messages})
                async with httpx.AsyncClient(trust_env=provider['kind'] != 'local') as client:
                    for attempt in range(2):
                        try:
                            with fail_after(ATTEMPT_TIMEOUT):
                                r = await client.post(
                                    provider['base_url'] + '/chat/completions',
                                    headers=auth_headers(provider),
                                    json={**kw, "model": name, "messages": messages},
                                    timeout=ATTEMPT_TIMEOUT,
                                )
                            r.raise_for_status()
                        except (httpx.TimeoutException, TimeoutError):
                            if attempt == 0:
                                continue
                            raise ModelError("timeout", "模型调用超时，请稍后重试。") from None
                        except httpx.ConnectError:
                            if attempt == 0:
                                continue
                            raise ModelError("http", "无法连接模型服务，请检查网络或联系管理员。") from None
                        except httpx.HTTPStatusError as e:
                            status = e.response.status_code
                            if 500 <= status < 600 and attempt == 0:
                                continue
                            raise ModelError("http", f"模型服务返回 HTTP {status}，请联系管理员。", status) from None
                        except httpx.RequestError:
                            raise ModelError("http", "模型请求传输失败，请检查网络或联系管理员。") from None
                        except OSError:
                            # 原生 TLS/连接异常（含 ssl.SSLError）不保证被 httpx 包装成 RequestError。
                            if attempt == 0:
                                continue
                            raise ModelError("http", "模型服务连接中断，请稍后重试。") from None
                        try:
                            content = r.json()["choices"][0]["message"]["content"]
                        except (ValueError, KeyError, IndexError, TypeError):
                            raise ModelError("bad_response", "模型响应格式异常，未收到文本结果。") from None
                        if not isinstance(content, str):
                            raise ModelError("bad_response", "模型响应格式异常，未收到文本结果。")
                        return content
        except TimeoutError:
            raise ModelError("timeout", "模型调用超时，请稍后重试。") from None


class _BoundAIHub:
    """给冻结 SDK 的 AI 句柄绑定当前请求用户，避免共享网关丢失审计主体。"""

    def __init__(self, gateway, principal):
        self._gateway = gateway
        self._principal = principal

    def call(self, app_id, capability, payload, timeout=50, **kwargs):
        kwargs['principal'] = self._principal
        return self._gateway.call(app_id, capability, payload, timeout, **kwargs)

    def __getattr__(self, name):
        return getattr(self._gateway, name)


class _BoundModelGateway:
    """按应用上下文代理模型网关，保留旧接口并把 AI 调用绑定到请求用户。"""

    def __init__(self, gateway, principal):
        self._gateway = gateway
        self._principal = principal
        if hasattr(gateway, 'aihub'):
            self.aihub = _BoundAIHub(gateway.aihub, principal)

    def chat(self, *args, _principal=None, **kwargs):
        return self._gateway.chat(*args, _principal=_principal or self._principal, **kwargs)

    def __getattr__(self, name):
        return getattr(self._gateway, name)


class AppModel:
    def __init__(self, gw: ModelGateway | _BoundModelGateway, app_id: str, files: Files | None = None, principal=None):
        self._gw, self._app, self._principal = gw, app_id, principal
        self._files = files

    @property
    def available(self) -> bool:
        return self._gw.configured

    def chat(
        self, messages: list[dict], *, model: str | None = None,
        images: list[str] | None = None, **kw: Any,
    ) -> str:
        return self._gw.chat(self._app, messages, model=model, images=images,
                             _files=self._files, _principal=self._principal, **kw)

"""经开区模型目录、个人偏好和文本对话路由。"""

import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

from haiknow_core.aihub.errors import AIError
from haiknow_core.aihub.gateway import CLASSIFICATIONS, DEFAULT_CLASSIFICATION, allowed_outbound
from haiknow_core.aihub.providers.jkq_chat import (
    DEFAULT_CONFIG, ChatGateway, ProviderRejected, load_config, provider_from_environment,
)
from haiknow_core.main import current_user
from haiknow_core.model import ModelGateway
from haiknow_sdk import ModelError

SETTINGS_NAMESPACE = "jkq.models"
PLATFORM_APP = "platform"
MODEL_KINDS = {"本地部署": "local", "海外模型（默认关闭）": "overseas", "推荐": "local"}
ModelId = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class ModelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: ModelId


class ModelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant", "developer"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=200_000)]


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: ModelId | None = None
    messages: list[Message] = Field(min_length=1, max_length=100)
    classification: Literal["public", "internal", "confidential"] = "internal"
    temperature: float | None = Field(default=None, ge=0, le=2)
    stream: Literal[False] = False


class ModelService:
    def __init__(self, platform, config, *, transport=None):
        self.store = platform.store
        self.settings = platform.model.aihub.settings
        self.models = {model.id: model for model in config.models}
        self.providers = {
            model.id: provider_from_environment(model, model.id in config.confidential_providers)
            for model in config.models
        }
        self.primary = os.getenv("JKQ_MODEL_PROVIDER", "").strip()
        if self.primary and self.primary not in self.models:
            raise ValueError("JKQ_MODEL_PROVIDER 未在模型配置中登记。")
        self.transport = transport

    def items(self):
        overrides = self.store.kv_list(SETTINGS_NAMESPACE, "enabled:")
        items = {
            model.id: {
                "id": model.id,
                "name": (self.providers[model.id] or {}).get("model") or model.name or model.provider,
                "provider": model.provider,
                "group": model.group,
                "kind": MODEL_KINDS.get(model.group, "cloud"),
                "desc": "",
                "tags": [],
                "enabled": bool(self.providers[model.id]) and overrides.get(f"enabled:{model.id}", model.enabled),
            }
            for model in self.models.values()
        }
        return {
            "auto": {
                "id": "auto", "name": "自动选择", "provider": "模型网关", "group": "推荐",
                "kind": "route", "desc": "按可用性与密级选择模型", "tags": [],
                "enabled": any(item["enabled"] for item in items.values()),
            },
            **items,
        }

    def current(self, user_id, items=None):
        items = self.items() if items is None else items
        chosen = self.store.kv_get(SETTINGS_NAMESPACE, f"current:{user_id}", "auto")
        return chosen if chosen in items and items[chosen]["enabled"] else "auto"

    def select(self, user_id, model_id):
        self._require_enabled(self.items(), model_id)
        self.store.kv_put(SETTINGS_NAMESPACE, f"current:{user_id}", model_id)
        self.store.audit(PLATFORM_APP, user_id, "model.select", {"model": model_id})
        return model_id

    def set_enabled(self, user_id, model_id, enabled):
        if model_id not in self.models:
            raise AIError("not_found", "没有可修改的模型。")
        if enabled and not self.providers[model_id]:
            raise AIError("model_disabled", "模型缺少部署配置，无法启用。")
        self.store.kv_put(SETTINGS_NAMESPACE, f"enabled:{model_id}", enabled)
        self.store.audit(PLATFORM_APP, user_id, "model.enable", {"model": model_id, "enabled": enabled})
        return self.items()[model_id]

    @staticmethod
    def _require_enabled(items, model_id):
        if model_id not in items:
            raise AIError("not_found", "模型不存在。")
        if not items[model_id]["enabled"]:
            raise AIError("model_disabled", "模型当前未启用。")

    def _candidates(self, items, preferred):
        model_ids = sorted(self.models, key=lambda ident: ident != preferred)
        return [
            (self.providers[ident], items[ident]["name"])
            for ident in model_ids if items[ident]["enabled"]
        ]

    def configured_route(self):
        return next((pair for pair in self._candidates(self.items(), self.primary)
                     if pair[0]["kind"] != "mock"), None)

    def _sdk_model_id(self, name):
        # 旧 SDK 接受供应商模型名。只解析已登记且不歧义的名称。
        if name is None or name in self.models or name == "auto":
            return name
        matches = [ident for ident, provider in self.providers.items()
                   if name == ((provider or {}).get("model") or self.models[ident].name)]
        return matches[0] if len(matches) == 1 else name

    def call(self, user, payload, *, model=None, app_id=PLATFORM_APP, timeout=50):
        items = self.items()
        classification = payload["classification"]
        user_id = getattr(user, "id", None) or "system"
        selected = model or self.current(user_id, items)
        confidential = classification == "confidential"
        if selected != "auto":
            if selected not in items:
                raise AIError("not_found", "模型不存在。")
            if not confidential:
                self._require_enabled(items, selected)
        preferred = self.primary if selected == "auto" else selected
        candidates = self._candidates(items, preferred)
        if not candidates and not confidential:
            raise AIError("not_configured", "没有已启用的模型。")

        def record_attempt(provider_id, model, status, usage):
            self.store.audit(app_id, user_id, "ai.chat", {
                "provider": provider_id, "model": model, "status": status, "usage": usage,
            })

        def record_outbound(app_id, user_id, action, detail):
            # 新版 core 也有成功汇总；逐次审计已经包含模型与 token。
            if action == "ai.outbound_denied":
                self.store.audit(app_id, user_id, action, detail)

        gateway = ChatGateway(self.settings, record_outbound, candidates, record_attempt, transport=self.transport)
        try:
            result = gateway.call(app_id, "chat", payload, timeout=timeout, principal=user)
        except ProviderRejected as error:
            raise AIError("provider_error", str(error)) from None

        notes = []
        first_allowed = next(provider["id"] for provider, _ in candidates
                             if allowed_outbound(provider, classification))
        if first_allowed != candidates[0][0]["id"] or (selected != "auto" and not items[selected]["enabled"]):
            notes.append("按密级切换到白名单模型")
        if result["provider"] != first_allowed:
            notes.append("主模型调用失败，已回退")
        if result["result"]["mock"]:
            notes.append("使用模拟模型")
        return result, "，".join(notes)

    def chat(self, user, body, *, app_id=PLATFORM_APP, timeout=50):
        payload = body.model_dump(exclude={"model", "stream"}, exclude_none=True)
        result, note = self.call(user, payload, model=body.model, app_id=app_id, timeout=timeout)
        return {"model": result["model"], "routeNote": note, **result["result"]}


SDK_TEXT_OPTIONS = {
    "messages", "classification", "model", "stream", "temperature", "top_p", "max_tokens",
    "max_completion_tokens", "stop", "frequency_penalty", "presence_penalty", "seed", "response_format",
    "n", "logit_bias", "logprobs", "top_logprobs", "user",
}


def _classification(payload):
    value = payload.get("classification")
    value = DEFAULT_CLASSIFICATION if value is None else value
    if value not in CLASSIFICATIONS:
        raise AIError("bad_input", "classification 只能是 public、internal 或 confidential。")
    return value


def _parts(messages):
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict) and isinstance(message.get("content"), list):
                yield from message["content"]


def _has_media(messages):
    return any(isinstance(part, dict) and part.get("type") in ("image_url", "input_audio", "file")
               for part in _parts(messages))


def _text_payload(payload, classification):
    if payload.keys() - SDK_TEXT_OPTIONS or payload.get("stream", False) is not False:
        raise AIError("bad_input", "应用文本对话仅支持非流式文本及生成参数。")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise AIError("bad_input", "对话消息不能为空。")
    for message in messages:
        if (not isinstance(message, dict) or message.keys() - {"role", "content", "name"}
                or message.get("role") not in ("system", "user", "assistant", "developer")
                or not isinstance(message.get("content"), (str, list))):
            raise AIError("bad_input", "应用对话消息必须包含角色与文本。")
    if any(not isinstance(part, dict) or part.keys() != {"type", "text"}
           or part["type"] != "text" or not isinstance(part["text"], str) for part in _parts(messages)):
        raise AIError("bad_input", "应用文本对话只接受文本内容片段。")
    return {**payload, "classification": classification}


def _check_media(classification):
    if classification == "confidential":
        raise AIError("bad_input", "应用机密对话仅支持文本。")


class _SDKAIHub:
    def __init__(self, legacy, service):
        self._legacy, self._service = legacy, service

    def __getattr__(self, name):
        return getattr(self._legacy, name)

    def _text_chat(self, app_id, payload, timeout, principal):
        payload = _text_payload(payload, _classification(payload))
        model = payload.pop("model", None)
        if model is not None and (not isinstance(model, str) or not model):
            raise AIError("bad_input", "模型标识必须是非空字符串。")
        try:
            result, _ = self._service.call(
                principal, payload, model=self._service._sdk_model_id(model), app_id=app_id, timeout=timeout,
            )
        except AIError as error:
            if error.kind == "model_disabled":
                # core 的 SDK 异常处理器以 not_configured 表示没有可用模型。
                raise AIError("not_configured", str(error)) from None
            raise
        return result

    def call(self, app_id, capability, payload, timeout=50, *, principal=None, **options):
        if capability == "chat" and not _has_media(payload.get("messages")):
            result = self._text_chat(app_id, payload, timeout, principal)
            return {**result, "result": result["result"]["content"]}
        if capability == "chat":
            _check_media(_classification(payload))
        return self._legacy.call(app_id, capability, payload, timeout, principal=principal, **options)


class _SDKModelGateway:
    # 复用 core 对应用、文件和当前请求主体的绑定。
    for_app = ModelGateway.for_app

    def __init__(self, legacy, service):
        self._legacy, self._service = legacy, service
        self.aihub = _SDKAIHub(legacy.aihub, service)

    def __getattr__(self, name):
        return getattr(self._legacy, name)

    @property
    def configured(self):
        return self.chat_route() is not None

    def chat_route(self):
        return self._service.configured_route()

    def chat(self, app_id, messages, timeout=50, *, model=None, images=None, _files=None, _principal=None, **options):
        media = bool(images) or _has_media(messages)
        try:
            if media:
                _check_media(_classification(options))
            else:
                result = self.aihub._text_chat(
                    app_id, {"messages": messages, "model": model, **options}, timeout, _principal,
                )["result"]
        except AIError as error:
            self._legacy._record(app_id, success=False)
            raise ModelError(getattr(error, "legacy_kind", error.kind), str(error),
                             getattr(error, "status_code", None)) from None
        except Exception:
            self._legacy._record(app_id, success=False)
            raise
        if media:
            # 保留旧的图片文件转换、网关和调用计数。
            return self._legacy.chat(app_id, messages, timeout, model=model, images=images,
                                     _files=_files, _principal=_principal, **options)
        self._legacy._record(app_id, success=True, mock=result["mock"])
        return result["content"]


def _response_error(status, code, message):
    return JSONResponse({"error": {"code": code, "message": message, "details": {}}}, status_code=status)


def _gateway_error(error):
    status = {
        "bad_input": 400, "model_disabled": 403, "outbound_denied": 403, "not_found": 404,
        "quota_exceeded": 429, "provider_error": 502,
        "not_configured": 503, "timeout": 504,
    }[error.kind]
    return _response_error(status, error.kind.upper(), str(error))


@asynccontextmanager
async def _lifespan(app):
    platform = app.state.platform
    path = platform.config_dir / "models.yaml"
    service = ModelService(platform, load_config(path if path.exists() else DEFAULT_CONFIG))
    original = platform.model
    platform.model = _SDKModelGateway(original, service)
    app.state.jkq_models = service
    try:
        yield
    finally:
        platform.model = original
        del app.state.jkq_models


router = APIRouter(prefix="/api/v1", lifespan=_lifespan)


def _service(request: Request):
    return request.app.state.jkq_models


def current_model(request: Request, user_id: str):
    """供 /me 读取与 /models/current 同一份偏好。"""
    return _service(request).current(user_id)


@router.get("/models")
def models(service=Depends(_service), user=Depends(current_user)):
    items = service.items()
    return {
        "items": list(items.values()), "current": service.current(user.id, items),
        "capabilities": [{"id": "chat", "name": "对话", "route": "auto" if items["auto"]["enabled"] else None}],
    }


@router.put("/models/current")
def put_current(body: ModelSelection, service=Depends(_service), user=Depends(current_user)):
    try:
        return {"current": service.select(user.id, body.model)}
    except AIError as error:
        return _gateway_error(error)


@router.patch("/models/{model_id}")
def patch_model(model_id: str, body: ModelPatch, request: Request,
                service=Depends(_service), user=Depends(current_user)):
    platform = request.app.state.platform
    if "admin" not in platform.rbac.actions(user, "*"):
        platform.store.audit(PLATFORM_APP, user.id, "model.forbidden", {"need": "admin"})
        return _response_error(403, "FORBIDDEN", "没有管理模型的权限。")
    try:
        return {"item": service.set_enabled(user.id, model_id, body.enabled)}
    except AIError as error:
        return _gateway_error(error)


@router.post("/ai/chat")
def chat(body: ChatBody, service=Depends(_service), user=Depends(current_user)):
    try:
        return service.chat(user, body)
    except AIError as error:
        return _gateway_error(error)

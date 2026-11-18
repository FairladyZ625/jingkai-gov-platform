"""经开区模型目录、个人偏好和文本对话路由。"""

import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

from haiknow_core.aihub.errors import AIError
from haiknow_core.aihub.gateway import allowed_outbound
from haiknow_core.aihub.providers.jkq_chat import (
    DEFAULT_CONFIG, ChatGateway, ProviderRejected, load_config, provider_from_environment,
)
from haiknow_core.main import current_user

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

    def chat(self, user, body, *, app_id=PLATFORM_APP, timeout=50):
        items = self.items()
        selected = body.model or self.current(user.id, items)
        if selected != "auto":
            self._require_enabled(items, selected)
        preferred = self.primary if selected == "auto" else selected
        model_ids = sorted(self.models, key=lambda ident: ident != preferred)
        candidates = [
            (self.providers[ident], items[ident]["name"])
            for ident in model_ids if items[ident]["enabled"]
        ]
        allowed = [provider for provider, _ in candidates if allowed_outbound(provider, body.classification)]
        if not candidates and body.classification != "confidential":
            raise AIError("not_configured", "没有已启用的模型。")

        def record_attempt(provider_id, model, status, usage):
            self.store.audit(app_id, user.id, "ai.chat", {
                "provider": provider_id, "model": model, "status": status, "usage": usage,
            })

        gateway = ChatGateway(
            self.settings, self.store.audit, candidates, record_attempt, transport=self.transport,
        )
        payload = body.model_dump(exclude={"model", "stream"}, exclude_none=True)
        try:
            result = gateway.call(app_id, "chat", payload, timeout=timeout, principal=user)
        except ProviderRejected as error:
            raise AIError("provider_error", str(error)) from None

        notes = []
        if allowed[0]["id"] != candidates[0][0]["id"]:
            notes.append("按密级切换到白名单模型")
        if result["provider"] != allowed[0]["id"]:
            notes.append("主模型调用失败，已回退")
        if result["result"]["mock"]:
            notes.append("使用模拟模型")
        return {"model": result["model"], "routeNote": "，".join(notes), **result["result"]}


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
    app.state.jkq_models = ModelService(platform, load_config(path if path.exists() else DEFAULT_CONFIG))
    yield


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

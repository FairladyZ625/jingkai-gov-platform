"""HAiKnow 平台 SDK（Python）。

小应用的后端只能通过本模块使用平台能力：当前用户、权限、文件、键值存储、留痕、模型。
不得 import haiknow_core 或其他应用，不得直接读环境变量或连数据库（scripts/check.py 会拦）。

用法：

    from fastapi import APIRouter, Depends
    from haiknow_sdk import AppContext, app_context, require

    router = APIRouter()

    @router.post("/approve/{rid}")
    def approve(rid: str, ctx: AppContext = Depends(require("approve"))):
        ctx.audit("approve", {"record": rid})
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from fastapi import Request

from .ai import AI
from .resources import DataError, DataFiles, Records, Reviews, Artifacts, Notifications

ACTIONS = ("view", "operate", "approve", "admin")
SDK_VERSION = "1.0.0"

__all__ = ["ACTIONS", "SDK_VERSION", "AppContext", "User", "app_context", "require", "PermissionDenied", "ModelError", "DataError"]


@dataclass(frozen=True)
class User:
    id: str
    name: str
    roles: tuple[str, ...] = field(default_factory=tuple)
    projects: tuple[str, ...] = field(default_factory=tuple)


class PermissionDenied(Exception):
    def __init__(self, app_id: str, action: str):
        super().__init__(f"无权限：{app_id} 的 {action}")
        self.app_id = app_id
        self.action = action


class ModelError(RuntimeError):
    """模型失败；kind 为 not_configured / timeout / http / bad_response。

    status_code 只记录上游 HTTP 状态，不包含密钥、请求内容或响应正文。
    """

    def __init__(self, kind: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


class _Runtime(Protocol):
    """由平台在启动时注入。应用代码不直接使用。"""

    def resolve(self, request: Any) -> "AppContext": ...


_runtime: _Runtime | None = None


def _install_runtime(rt: _Runtime) -> None:  # 平台内部调用
    global _runtime
    _runtime = rt


class Files(Protocol):
    def save(self, name: str, data: bytes) -> str: ...
    def read(self, file_id: str) -> bytes: ...
    def list(self) -> list[dict]: ...


class KV(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...
    def put(self, key: str, value: Any) -> None: ...
    def list(self, prefix: str = "") -> dict[str, Any]: ...


class Model(Protocol):
    @property
    def available(self) -> bool: ...
    def chat(
        self, messages: list[dict], *, model: str | None = None,
        images: list[str] | None = None, **kw: Any,
    ) -> str: ...


@dataclass
class AppContext:
    app_id: str
    user: User
    actions: frozenset[str]
    files: Files
    kv: KV
    model: Model
    _audit: Callable[[str, dict], None]

    records: Records | None = None
    data_files: DataFiles | None = None
    reviews: Reviews | None = None
    artifacts: Artifacts | None = None
    notifications: Notifications | None = None

    @property
    def ai(self) -> AI:
        """按能力调用 AI（对话、生图、语音、向量），服务商由平台系统配置决定。"""
        return AI(self.model)

    @property
    def preview(self):
        """实验能力，不属于 SDK 1.x 兼容承诺。"""
        from .preview.datasets import Preview
        return Preview(self)

    def can(self, action: str) -> bool:
        return action in self.actions

    def audit(self, action: str, detail: dict | None = None) -> None:
        """记一条留痕：谁、在哪个应用、做了什么。"""
        self._audit(action, detail or {})


def app_context(request: Request) -> AppContext:
    """FastAPI 依赖：要求已登录且对当前应用有 view 权限，返回 AppContext。"""
    if _runtime is None:
        raise RuntimeError("平台运行时未初始化")
    return _runtime.resolve(request)


def require(action: str) -> Callable[[Request], AppContext]:
    """FastAPI 依赖：要求当前用户在当前应用上有 action 权限，返回 AppContext。"""
    if action not in ACTIONS:
        raise ValueError(f"未知动作 {action}，只能是 {ACTIONS}")

    def dep(request: Request) -> AppContext:
        ctx = app_context(request)
        if action not in ctx.actions:
            raise PermissionDenied(ctx.app_id, action)
        return ctx

    return dep

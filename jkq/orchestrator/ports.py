"""上游接线契约。T15 负责模型配置、权限与出域，T16 负责工具授权与执行。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from fastapi import Request
    from haiknow_sdk import User


@dataclass(frozen=True)
class ToolCall:
    tool: str
    args: dict = field(default_factory=dict)
    id: str | None = None

    @property
    def app(self) -> str:
        return self.tool.partition(".")[0]


@dataclass(frozen=True)
class ModelTurn:
    """网关的一轮结果。带工具调用的轮次暂存其文本，避免提前发送结论。"""

    deltas: tuple[str, ...] = ()
    calls: tuple[ToolCall, ...] = ()
    model: str | None = None
    route_note: str | None = None


DeltaSink = Callable[[str], Awaitable[None]]


class ModelGateway(Protocol):
    async def __call__(
        self, request: Request, *, messages: list[dict], tools: list[str],
        model: str | None, classification: str, on_delta: DeltaSink | None = None,
    ) -> ModelTurn:
        """on_delta 只接收可直接展示的最终文本。调用后不得返回工具调用或重放增量。"""
        ...


class ToolBridge(Protocol):
    def tools(self, user: User) -> dict: ...

    async def call_from_chat(self, request: Request, app_id: str, tool: str, args: dict) -> dict:
        """T16 对写工具检查 operate 和业务预检，持久化 Review 后返回 pending 与 reviewId。"""
        ...

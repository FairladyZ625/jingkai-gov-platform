"""上游接线契约。T15 负责模型配置、权限与出域，T16 负责工具授权与执行。"""

from __future__ import annotations

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


class ModelGateway(Protocol):
    async def __call__(
        self, request: Request, *, messages: list[dict], tools: list[str],
        model: str | None, classification: str,
    ) -> ModelTurn: ...


class ToolBridge(Protocol):
    def tools(self, user: User) -> dict: ...

    async def call_from_chat(self, request: Request, app_id: str, tool: str, args: dict) -> dict: ...

"""上游接线契约。T15 负责模型配置、权限与出域，T16 负责工具授权与执行。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from .classification import Classification

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
MetaSink = Callable[[str | None, str | None], Awaitable[None]]


class ModelGateway(Protocol):
    async def __call__(
        self, request: Request, *, messages: list[dict], tools: list[str],
        model: str | None, classification: Classification, on_delta: DeltaSink | None = None,
        on_meta: MetaSink | None = None,
    ) -> ModelTurn:
        """已知模型、路由时先调用 on_meta。on_delta 只接收可直接展示的最终文本。

        调用 on_delta 后不得返回工具调用或重放增量；仅在该轮允许发布时传入此回调。
        """
        ...


class ToolBridge(Protocol):
    def tools(self, user: User) -> dict: ...

    async def call_from_chat(self, request: Request, app_id: str, tool: str, args: dict) -> dict:
        """T16 对写工具检查 operate 和业务预检，持久化 Review 后返回 pending 与 reviewId。"""
        ...

    async def ask_from_chat(self, request: Request, question: str, *, classification: Classification) -> dict:
        """沿用请求身份和知识库授权。密级是服务端上限计算的输入，只能按检索片段升级。

        返回知识结果，outcome 为 answered、no_match 或 unavailable。answered 使用知识库
        验证过的逐句摘录和编号引用。no_match 使用 confidence=none 与空 citations。
        """
        ...

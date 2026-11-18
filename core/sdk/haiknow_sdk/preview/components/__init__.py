"""C01 / C02 / C03 / C04 / C06 / C07 共用组件（纯函数库）。

组件不拥有数据、不判权限、不调模型：应用把字段、规则、模板交给组件，
组件返回普通 JSON；保存、确认、审计仍由应用路由调用 SDK 的 ctx 完成。

用法：

    from haiknow_sdk.preview.components import c01

    schema = c01.Schema(fields=(c01.Field("batch", "批次", required=True),))
    draft = schema.draft({"batch": "B-001"})
    if not draft.ok:
        return JSONResponse(c01.error_body(draft.errors), status_code=422)

版本：各组件模块导出自己的 VERSION，Python 与前端模块同号。
"""
from __future__ import annotations

from .common import Issue, error_body

__all__ = ["Issue", "error_body"]
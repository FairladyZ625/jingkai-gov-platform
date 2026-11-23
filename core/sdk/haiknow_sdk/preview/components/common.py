"""C01 / C03 / C06 共用的小工具：问题条目、统一错误信封、键与数字归一。

组件是纯函数库：不读环境变量、不连数据库、不 import 平台核心，只接收普通 dict 并返回普通 dict。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

VERSION = "1.0.0"

# float 能精确表示整数的上界；超过它的整数不转 float，避免静默改值。
MAX_EXACT_FLOAT_INT = 2 ** 53
_INT_RE = re.compile(r"[+-]?\d+")

__all__ = ["VERSION", "MAX_EXACT_FLOAT_INT", "Issue", "error_body", "is_missing", "normalize_key", "as_number"]


@dataclass(frozen=True)
class Issue:
    """一条可定位的问题；用户可纠正的问题用返回值表达，不抛异常。"""

    code: str
    message: str
    field: str = ""
    row: int | None = None
    column: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "row": self.row,
            "column": self.column,
        }


def error_body(issues: Iterable[Issue | Mapping[str, Any]]) -> dict[str, Any]:
    """把问题列表包成平台 v1 风格的错误信封，供应用路由直接返回 422。"""
    items = [i.to_dict() if isinstance(i, Issue) else dict(i) for i in issues]
    return {
        "error": {
            "code": "INVALID_REQUEST",
            "message": "请求字段或数据不正确",
            "retryable": False,
            "issues": items,
        }
    }


def is_missing(value: Any) -> bool:
    """空字符串、空白字符串、None 和空容器都算未填；0 与 False 不算。"""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def normalize_key(value: Any) -> str:
    """匹配键归一：去首尾空白、连续空白压成一个空格、大小写不敏感。"""
    if value is None:
        return ""
    return " ".join(str(value).strip().split()).casefold()


def as_number(value: Any) -> int | float | None:
    """把数字或数字字符串转成精确的 int/float；无法无损表示时返回 None。

    - 整数保持 int（任意精度），不先转 float，避免大整数静默改值。
    - 十进制字符串用 Decimal 校验：float 往返不一致（精度损失）或溢出/下溢时返回 None。
    - 布尔、空值和非法数字返回 None。
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        if value.is_integer() and abs(value) <= MAX_EXACT_FLOAT_INT:
            return int(value)
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if _INT_RE.fullmatch(text):
            try:
                return int(text)
            except ValueError:
                # Python 对超长整数字符串有位数上限；明确拒绝，不让接口 500。
                return None
        try:
            parsed = Decimal(text)
        except InvalidOperation:
            return None
        if not parsed.is_finite():
            return None
        try:
            number = float(parsed)
        except (OverflowError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        # 无法无损转成 float 的十进制输入明确拒绝，不能成功但悄悄改值。
        if Decimal(str(number)) != parsed:
            return None
        if number.is_integer() and abs(number) <= MAX_EXACT_FLOAT_INT:
            return int(number)
        return number
    return None

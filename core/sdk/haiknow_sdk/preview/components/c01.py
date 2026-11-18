"""C01 采集填表：字段定义 → 校验草稿 → 缺项与逐字段错误。

应用只声明字段（标签、类型、必填、单位、选项、范围、格式）；抽取函数由应用提供，
组件只做校验、来源整理和缺项统计，不调模型、不存数据。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Mapping

from . import common
from .common import Issue, error_body, is_missing

VERSION = "1.0.0"

TYPES = ("text", "number", "date", "enum", "file", "photo")

__all__ = ["VERSION", "TYPES", "Field", "Schema", "Draft", "Issue", "error_body"]


@dataclass(frozen=True)
class Field:
    """一个采集字段。未知类型、空 key、枚举无选项、非法正则在构造时抛 ValueError。"""

    key: str
    label: str = ""
    type: str = "text"
    required: bool = False
    unit: str = ""
    options: tuple[str, ...] = ()
    pattern: str = ""
    min: float | None = None
    max: float | None = None
    help: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key.strip():
            raise ValueError("字段 key 不能为空")
        if self.type not in TYPES:
            raise ValueError(f"未知字段类型 {self.type}，只能是 {TYPES}")
        object.__setattr__(self, "options", tuple(self.options or ()))
        if self.type == "enum" and not self.options:
            raise ValueError(f"枚举字段 {self.key} 必须提供 options")
        if self.pattern:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"字段 {self.key} 的 pattern 不是合法正则：{exc}") from exc
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"字段 {self.key} 的 min 不能大于 max")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "unit": self.unit,
            "options": list(self.options),
            "pattern": self.pattern,
            "min": self.min,
            "max": self.max,
            "help": self.help,
        }


@dataclass
class Schema:
    """一组字段定义。version 随字段含义变化递增，供应用记录草稿对应的字段版本。"""

    fields: tuple[Field, ...]
    version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", tuple(self.fields))
        seen: set[str] = set()
        for item in self.fields:
            if not isinstance(item, Field):
                raise TypeError("fields 里只能是 Field")
            if item.key in seen:
                raise ValueError(f"字段 key 重复：{item.key}")
            seen.add(item.key)

    @property
    def by_key(self) -> dict[str, Field]:
        return {field.key: field for field in self.fields}

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "fields": [field.to_dict() for field in self.fields]}

    def draft(
        self,
        values: Mapping[str, Any] | None = None,
        *,
        sources: Mapping[str, Mapping[str, str]] | None = None,
    ) -> "Draft":
        """按字段定义校验一组值，返回草稿；未知键不写进草稿，只报错。"""
        given = dict(values or {})
        known = self.by_key
        out_values: dict[str, Any] = {}
        out_sources: dict[str, dict[str, str]] = {}
        missing: list[str] = []
        errors: list[Issue] = []

        for key in given:
            if key not in known:
                errors.append(Issue("unknown_field", f"未声明的字段：{key}", field=str(key)))

        for field in self.fields:
            raw = given.get(field.key)
            if is_missing(raw):
                out_values[field.key] = ""
                if field.required:
                    errors.append(Issue("required", f"{field.label or field.key}不能为空", field=field.key))
                    missing.append(field.key)
                continue
            value, issue = _check(field, raw)
            out_values[field.key] = "" if value is None else value
            if issue is not None:
                errors.append(issue)

        for key, source in (sources or {}).items():
            if key not in known or not isinstance(source, Mapping):
                continue
            clean = {str(k): str(v) for k, v in source.items() if v not in (None, "")}
            if clean:
                out_sources[key] = clean

        return Draft(ok=not errors, values=out_values, sources=out_sources, missing=missing, errors=errors)

    def from_text(self, text: str, extractor: Callable[[str], Mapping[str, Any]]) -> "Draft":
        """用应用自己的抽取函数得到值，再走同一套校验；抽取函数抛错原样上抛。"""
        if not callable(extractor):
            raise TypeError("extractor 必须可调用")
        found = extractor(text)
        if not isinstance(found, Mapping):
            raise TypeError("extractor 必须返回 dict")
        values: dict[str, Any] = {}
        sources: dict[str, dict[str, str]] = {}
        for key, item in found.items():
            if isinstance(item, Mapping) and "value" in item:
                values[key] = item.get("value")
                source = {str(k): str(v) for k, v in item.items() if k != "value" and v not in (None, "")}
                if source:
                    sources[key] = source
            else:
                values[key] = item
        return self.draft(values, sources=sources)


@dataclass
class Draft:
    ok: bool
    values: dict[str, Any]
    sources: dict[str, dict[str, str]]
    missing: list[str]
    errors: list[Issue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "values": self.values,
            "sources": self.sources,
            "missing": list(self.missing),
            "errors": [issue.to_dict() for issue in self.errors],
        }


def _check(field: Field, raw: Any) -> tuple[Any, Issue | None]:
    """返回 (归一后的值, 问题)。值尽量保留，便于前端回显后让用户修正。"""
    if field.type == "text":
        if isinstance(raw, (Mapping, list, tuple, set)):
            return None, Issue("type", f"{field.label or field.key}应为文本", field=field.key)
        text = str(raw)
        if field.pattern and not re.fullmatch(field.pattern, text):
            return text, Issue("pattern", f"{field.label or field.key}格式不正确", field=field.key)
        return text, None

    if field.type == "number":
        number = common.as_number(raw)
        if number is None:
            return None, Issue(
                "type", f"{field.label or field.key}应为有限数字，或精度超出可表示范围", field=field.key
            )
        if field.min is not None and number < field.min:
            return number, Issue("range", f"{field.label or field.key}不能小于 {field.min}", field=field.key)
        if field.max is not None and number > field.max:
            return number, Issue("range", f"{field.label or field.key}不能大于 {field.max}", field=field.key)
        return number, None

    if field.type == "date":
        text = str(raw).strip()
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            return text, Issue("type", f"{field.label or field.key}应为 YYYY-MM-DD", field=field.key)
        return parsed.isoformat(), None

    if field.type == "enum":
        text = str(raw).strip()
        if text not in field.options:
            return text, Issue(
                "option", f"{field.label or field.key}只能是：{'、'.join(field.options)}", field=field.key
            )
        return text, None

    # file / photo：只收 fileId，文件是否存在由平台文件层判断。
    if isinstance(raw, Mapping):
        file_id = raw.get("fileId") or raw.get("file_id") or ""
        if not str(file_id).strip():
            return None, Issue("type", f"{field.label or field.key}缺少 fileId", field=field.key)
        return str(file_id).strip(), None
    if isinstance(raw, str):
        return raw.strip(), None
    return None, Issue("type", f"{field.label or field.key}应为文件 ID", field=field.key)
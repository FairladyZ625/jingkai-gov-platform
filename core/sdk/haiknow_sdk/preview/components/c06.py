"""C06 资料汇编：槽位 + {{key}} 模板 → HTML/CSV，缺件与引用改版可见。

应用只写槽位（报告目录）和 HTML 模板；组件负责填值、转义、查缺件、比对引用版本。
组件不把文件二进制嵌进资料包，也不替应用判断权限。
"""
from __future__ import annotations

import csv
import html
import io
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import common

VERSION = "1.0.0"

PLACEHOLDER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

__all__ = ["VERSION", "TemplateError", "Citation", "Slot", "Book", "Render"]


class TemplateError(ValueError):
    """模板写错是程序错误，应用应在测试或启动时暴露，而不是等用户填完才报。"""

    def __init__(self, code: str, field: str = "", message: str = ""):
        self.code = code
        self.field = field
        self.message = message or f"模板占位符 {field} 未在槽位中声明"
        super().__init__(self.message)


@dataclass
class Citation:
    """引用元数据，字段与平台 v1 记录形状对齐；不是授权凭证。"""

    app_id: str = ""
    record_id: str = ""
    version: int | None = None
    file_id: str = ""
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "appId": self.app_id,
            "recordId": self.record_id,
            "version": self.version,
            "fileId": self.file_id,
            "label": self.label,
        }


@dataclass(frozen=True)
class Slot:
    """报告目录里的一个槽位。required 默认 True；可选槽位缺件不阻断出稿。"""

    key: str
    label: str = ""
    required: bool = True
    source: str = ""
    unit: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key.strip():
            raise ValueError("槽位 key 不能为空")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "required": self.required,
            "source": self.source,
            "unit": self.unit,
        }


@dataclass
class Book:
    slots: tuple[Slot, ...] = ()
    title: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "slots", tuple(self.slots))
        seen: set[str] = set()
        for slot in self.slots:
            if not isinstance(slot, Slot):
                raise TypeError("slots 里只能是 Slot")
            if slot.key in seen:
                raise ValueError(f"槽位 key 重复：{slot.key}")
            seen.add(slot.key)

    def to_dict(self) -> dict[str, Any]:
        return {"version": 1, "title": self.title, "slots": [slot.to_dict() for slot in self.slots]}

    def render(
        self,
        template: str,
        data: Mapping[str, Any],
        *,
        citations: Mapping[str, Citation | Mapping[str, Any]] | None = None,
        current_versions: Mapping[str, int] | None = None,
    ) -> "Render":
        if not isinstance(template, str):
            raise TypeError("模板必须是字符串")
        values = dict(data or {})
        citation_map = dict(citations or {})
        current = dict(current_versions or {})
        known = {slot.key: slot for slot in self.slots}

        for match in PLACEHOLDER.finditer(template):
            key = match.group(1)
            if key not in known:
                raise TemplateError("unknown_placeholder", key)

        missing: list[str] = []
        stale_: list[dict[str, Any]] = []
        rendered: dict[str, str] = {}
        rows: list[dict[str, Any]] = []
        normalized: dict[str, dict[str, Any]] = {}

        for slot in self.slots:
            raw = values.get(slot.key)
            if common.is_missing(raw):
                if slot.required:
                    missing.append(slot.key)
                    text = f"【待补：{slot.label or slot.key}】"
                else:
                    text = ""
                plain = ""
            else:
                plain = _plain(raw)
                text = html.escape(plain, quote=True)
            rendered[slot.key] = text

            citation = _citation(citation_map.get(slot.key))
            if citation is not None:
                normalized[slot.key] = citation
                cited = citation.get("version")
                current_version = current.get(slot.key)
                if cited is not None and current_version is not None and cited != _version(current_version):
                    stale_.append({"key": slot.key, "cited": cited, "current": current_version})
            rows.append({"slot": slot.key, "label": slot.label, "value": plain, "citation": citation or {}})

        out_html = PLACEHOLDER.sub(lambda match: rendered[match.group(1)], template)
        complete = not missing
        return Render(
            html=out_html,
            complete=complete,
            formal_ready=complete and not stale_,
            missing=missing,
            stale=stale_,
            citations=normalized,
            rows=rows,
            citation_html=_citation_table(rows),
        )


@dataclass
class Render:
    html: str
    complete: bool
    formal_ready: bool
    missing: list[str]
    stale: list[dict[str, Any]]
    citations: dict[str, dict[str, Any]]
    rows: list[dict[str, Any]]
    citation_html: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "html": self.html,
            "complete": self.complete,
            "formal_ready": self.formal_ready,
            "missing": list(self.missing),
            "stale": [dict(item) for item in self.stale],
            "citations": self.citations,
            "rows": self.rows,
            "citation_html": self.citation_html,
        }

    def csv(self) -> str:
        """带 BOM 的 UTF-8 CSV，列为：槽位,值,来源应用,记录号,版本,文件号。"""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["槽位", "值", "来源应用", "记录号", "版本", "文件号"])
        for row in self.rows:
            citation = row.get("citation") or {}
            writer.writerow([
                row["slot"],
                row.get("value", ""),
                citation.get("appId", ""),
                citation.get("recordId", ""),
                "" if citation.get("version") is None else citation.get("version"),
                citation.get("fileId", ""),
            ])
        return "\ufeff" + buffer.getvalue()


def _version(value: Any) -> Any:
    """版本号允许 int 或数字字符串；其他值原样比较。"""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
        return text
    return value


def _plain(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (list, tuple)):
        return "、".join(_plain(item) for item in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _citation(value: Citation | Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Citation):
        data = value.to_dict()
    elif isinstance(value, Mapping):
        data = {
            "appId": value.get("appId", value.get("app_id", "")),
            "recordId": value.get("recordId", value.get("record_id", "")),
            "version": value.get("version"),
            "fileId": value.get("fileId", value.get("file_id", "")),
            "label": value.get("label", ""),
        }
        known = {"appId", "recordId", "version", "fileId", "label", "app_id", "record_id", "file_id"}
        for key, item in value.items():
            if key not in known:
                data[key] = item
    else:
        raise TypeError("citation 必须是 Citation 或 dict")
    data["version"] = _version(data.get("version"))
    return data


def _citation_table(rows: Sequence[Mapping[str, Any]]) -> str:
    head = ("槽位", "值", "来源应用", "记录号", "版本", "文件号")
    lines = [
        "<table>",
        "<thead><tr>" + "".join(f"<th>{html.escape(name)}</th>" for name in head) + "</tr></thead>",
        "<tbody>",
    ]
    for row in rows:
        citation = row.get("citation") or {}
        cells = [
            str(row.get("label") or row.get("slot", "")),
            str(row.get("value", "")),
            str(citation.get("appId", "")),
            str(citation.get("recordId", "")),
            "" if citation.get("version") is None else str(citation.get("version")),
            str(citation.get("fileId", "")),
        ]
        lines.append("<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in cells) + "</tr>")
    lines += ["</tbody>", "</table>"]
    return "\n".join(lines)
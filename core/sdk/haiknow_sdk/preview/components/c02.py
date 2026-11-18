"""C02 文档审查：规则集 × 条款 → 带原文与定位的提示，人工采纳、改判、驳回留痕。

应用只写审查规则（id、条件描述、风险等级、依据出处、建议）和条款来源（文本或 #37 parse
结果的区块）；组件负责匹配、原文定位、有无依据的状态与人工处理记录。模型辅助是可选的注入
函数：应用把 `ctx.ai.chat` 包装成 `judge(rule, clause)` 传进来，不传就是关闭；组件本身不调模型、
不读环境变量、不存数据。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, Mapping, Sequence

from .common import Issue, error_body

VERSION = "1.0.0"

RISKS = ("高", "中", "低")
STATUSES = ("待审", "采纳", "改判", "驳回", "无依据")
DECISIONS = ("采纳", "改判", "驳回")
JUDGE = Callable[["Rule", "Clause"], Mapping[str, Any]]

__all__ = [
    "VERSION", "RISKS", "STATUSES", "DECISIONS", "Rule", "Clause", "Hint", "Review",
    "Decision", "review", "decide", "from_text", "from_parse", "Issue", "error_body",
]


@dataclass(frozen=True)
class Rule:
    """一条审查规则。keywords / pattern 是确定性匹配条件，二者都为空时需要模型辅助。"""

    id: str
    condition: str
    risk: str = "中"
    basis: str = ""
    suggestion: str = ""
    keywords: tuple[str, ...] = ()
    pattern: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("规则 id 不能为空")
        if not isinstance(self.condition, str) or not self.condition.strip():
            raise ValueError(f"规则 {self.id} 的条件描述不能为空")
        if self.risk not in RISKS:
            raise ValueError(f"未知风险等级 {self.risk}，只能是 {RISKS}")
        if not isinstance(self.basis, str):
            raise ValueError("依据出处必须是字符串")
        object.__setattr__(self, "keywords", tuple(str(item).strip() for item in (self.keywords or ()) if str(item).strip()))
        if self.pattern:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"规则 {self.id} 的 pattern 不是合法正则：{exc}") from exc

    @property
    def deterministic(self) -> bool:
        return bool(self.keywords or self.pattern)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "condition": self.condition,
            "risk": self.risk,
            "basis": self.basis,
            "suggestion": self.suggestion,
            "keywords": list(self.keywords),
            "pattern": self.pattern,
        }


@dataclass(frozen=True)
class Clause:
    """一条待审条款；locator / page / bbox 是回到原文的定位信息。"""

    id: str
    text: str
    locator: str = ""
    page: int | None = None
    bbox: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("条款 id 不能为空")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError(f"条款 {self.id} 的原文不能为空")
        if self.page is not None and (not isinstance(self.page, int) or isinstance(self.page, bool) or self.page < 1):
            raise ValueError("条款页码必须是正整数或空")
        if self.bbox is not None:
            try:
                object.__setattr__(self, "bbox", tuple(float(item) for item in self.bbox))
            except (TypeError, ValueError) as exc:
                raise ValueError("条款 bbox 必须是数字列表") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "locator": self.locator,
            "page": self.page,
            "bbox": list(self.bbox) if self.bbox is not None else None,
        }


@dataclass(frozen=True)
class Hint:
    """一条提示：规则、条款原文与定位、建议、等级、状态与人工处理记录。"""

    id: str
    rule: str
    condition: str
    clause: str
    text: str
    locator: str
    risk: str
    basis: str
    suggestion: str
    status: str
    page: int | None = None
    bbox: tuple[float, ...] | None = None
    reviewer: str = ""
    reason: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rule": self.rule,
            "condition": self.condition,
            "clause": self.clause,
            "text": self.text,
            "locator": self.locator,
            "page": self.page,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "risk": self.risk,
            "basis": self.basis,
            "suggestion": self.suggestion,
            "status": self.status,
            "reviewer": self.reviewer,
            "reason": self.reason,
            "note": self.note,
        }


@dataclass
class Review:
    hints: list[Hint]
    skipped: list[dict[str, Any]]
    errors: list[Issue]

    @property
    def ok(self) -> bool:
        return not self.errors

    def by_status(self) -> dict[str, int]:
        counts = {name: 0 for name in STATUSES}
        for hint in self.hints:
            counts[hint.status] = counts.get(hint.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "hints": [hint.to_dict() for hint in self.hints],
            "skipped": [dict(item) for item in self.skipped],
            "byStatus": self.by_status(),
            "errors": [issue.to_dict() for issue in self.errors],
        }


@dataclass
class Decision:
    ok: bool
    hints: list[Hint]
    errors: list[Issue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "hints": [hint.to_dict() for hint in self.hints],
            "errors": [issue.to_dict() for issue in self.errors],
        }


def review(
    rules: Sequence[Rule],
    clauses: Sequence[Clause],
    *,
    judge: JUDGE | None = None,
) -> Review:
    """按规则逐条对照条款，返回提示清单；同一规则同一线索只出一次。

    规则命中方式：`keywords` 任一出现（归一后包含）或 `pattern` 搜索命中。两者都为空的规则
    需要 `judge` 判断是否命中；没传 `judge` 时该规则记入 `skipped`，不生成结论。
    规则没有依据出处时提示状态为「无依据」，不生成风险等级和建议。
    """
    if judge is not None and not callable(judge):
        raise TypeError("judge 必须可调用")
    items = tuple(clauses or ())
    for clause in items:
        if not isinstance(clause, Clause):
            raise TypeError("clauses 里只能是 Clause")

    errors: list[Issue] = []
    skipped: list[dict[str, Any]] = []
    hints: list[Hint] = []
    seen_rules: set[str] = set()
    seen_hints: set[str] = set()

    for rule in rules or ():
        if not isinstance(rule, Rule):
            raise TypeError("rules 里只能是 Rule")
        if rule.id in seen_rules:
            errors.append(Issue("duplicate_rule", f"规则 id 重复：{rule.id}", field=rule.id))
            continue
        seen_rules.add(rule.id)
        pattern = re.compile(rule.pattern, re.IGNORECASE | re.MULTILINE) if rule.pattern else None
        keywords = tuple(_normalize(item) for item in rule.keywords)
        if not rule.deterministic and judge is None:
            skipped.append({"rule": rule.id, "reason": "规则没有可匹配条件，未启用模型辅助"})
            continue
        for clause in items:
            hit, extra = _match(rule, clause, keywords, pattern, judge)
            if not hit:
                continue
            hint_id = f"{rule.id}@{clause.id}"
            if hint_id in seen_hints:
                continue
            seen_hints.add(hint_id)
            has_basis = bool(rule.basis.strip())
            status = "待审" if has_basis else "无依据"
            hints.append(Hint(
                id=hint_id,
                rule=rule.id,
                condition=rule.condition,
                clause=clause.id,
                text=clause.text,
                locator=clause.locator,
                page=clause.page,
                bbox=clause.bbox,
                risk=rule.risk if has_basis else "",
                basis=rule.basis,
                suggestion=(str(extra.get("suggestion") or "") or rule.suggestion) if has_basis else "",
                status=status,
                note="" if has_basis else "缺少依据出处，仅提示待确认",
            ))

    return Review(hints=hints, skipped=skipped, errors=errors)


def decide(
    hints: Iterable[Hint],
    hint_id: str,
    status: str,
    *,
    reviewer: str,
    reason: str = "",
    risk: str | None = None,
) -> Decision:
    """记录人工处理：采纳 / 改判 / 驳回。改判要给出新等级，改判和驳回要写理由。"""
    if status not in DECISIONS:
        raise ValueError(f"未知处理状态 {status}，只能是 {DECISIONS}")
    items = list(hints or ())
    index = next((position for position, hint in enumerate(items) if hint.id == hint_id), None)
    if index is None:
        return Decision(False, items, [Issue("hint_not_found", f"没有 id 为 {hint_id} 的提示", field=str(hint_id))])
    hint = items[index]
    errors: list[Issue] = []
    if not str(reviewer or "").strip():
        errors.append(Issue("reviewer_required", "需要填写处理人", field=hint_id))
    if status in ("改判", "驳回") and not str(reason or "").strip():
        errors.append(Issue("reason_required", f"{status}必须填写理由", field=hint_id))
    if status == "改判" and not risk:
        errors.append(Issue("risk_required", "改判必须给出新的风险等级", field=hint_id))
    if risk and risk not in RISKS:
        errors.append(Issue("unknown_risk", f"未知风险等级 {risk}，只能是 {RISKS}", field=hint_id))
    if hint.status == "无依据" and status == "采纳":
        errors.append(Issue("no_basis", "无依据的提示不能采纳，请改判或驳回", field=hint_id))
    if errors:
        return Decision(False, items, errors)
    items[index] = replace(
        hint,
        status=status,
        reviewer=str(reviewer).strip(),
        reason=str(reason or "").strip(),
        # 只有改判会换等级；采纳/驳回保持规则原等级。
        risk=risk if status == "改判" else hint.risk,
        note="",
    )
    return Decision(True, items, [])


def from_text(text: str, *, prefix: str = "c", locator_prefix: str = "第") -> tuple[Clause, ...]:
    """把一段文本按空行拆成条款；每段的定位是「第 N 段」。"""
    if not isinstance(text, str):
        raise TypeError("text 必须是字符串")
    parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return tuple(
        Clause(f"{prefix}{index + 1}", part, locator=f"{locator_prefix} {index + 1} 段")
        for index, part in enumerate(parts)
    )


def from_parse(result: Mapping[str, Any]) -> tuple[Clause, ...]:
    """把 #37 `ctx.preview.ai_tools.parse` 的结果转成条款。

    接受完整信封（含 `result`）或结果本身；按区块顺序保留页码与 bbox，表格按行拼成文本。
    没有正文的区块（如图片）跳过，不凭空生成条款。
    """
    if not isinstance(result, Mapping):
        raise TypeError("parse 结果必须是 dict")
    data = result.get("result", result)
    if not isinstance(data, Mapping):
        raise TypeError("parse 结果的 result 必须是 dict")
    blocks = data.get("blocks") or ()
    clauses: list[Clause] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, Mapping):
            raise TypeError("parse 结果的 blocks 里只能是 dict")
        text = _block_text(block)
        if not text:
            continue
        page = block.get("page")
        page = page if isinstance(page, int) and not isinstance(page, bool) and page >= 1 else None
        bbox = block.get("bbox")
        clauses.append(Clause(
            id=str(block.get("id") or f"b{index}"),
            text=text,
            locator=str(block.get("locator") or (f"第 {page} 页" if page else f"第 {index + 1} 块")),
            page=page,
            bbox=tuple(bbox) if isinstance(bbox, (list, tuple)) and bbox else None,
        ))
    return tuple(clauses)


def _match(
    rule: Rule,
    clause: Clause,
    keywords: tuple[str, ...],
    pattern: re.Pattern[str] | None,
    judge: JUDGE | None,
) -> tuple[bool, Mapping[str, Any]]:
    if rule.deterministic:
        text = _normalize(clause.text)
        hit = any(item in text for item in keywords) or bool(pattern and pattern.search(clause.text))
        return hit, {}
    assert judge is not None  # 没有确定性条件且没有 judge 的规则在 review 里已记入 skipped
    found = judge(rule, clause)
    if not isinstance(found, Mapping):
        raise TypeError("judge 必须返回 dict")
    hit = found.get("hit")
    if not isinstance(hit, bool):
        raise ValueError(f"judge 对规则 {rule.id} / 条款 {clause.id} 的返回缺少布尔 hit")
    suggestion = found.get("suggestion")
    if suggestion is not None and not isinstance(suggestion, str):
        raise ValueError("judge 返回的 suggestion 必须是字符串")
    return hit, found


def _block_text(block: Mapping[str, Any]) -> str:
    text = block.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    table = block.get("table")
    if isinstance(table, str):
        return table.strip()
    if isinstance(table, (list, tuple)):
        rows = []
        for row in table:
            if isinstance(row, (list, tuple)):
                rows.append("\t".join(str(cell).strip() for cell in row))
            elif row is not None:
                rows.append(str(row).strip())
        return "\n".join(item for item in rows if item)
    return ""


def _normalize(value: Any) -> str:
    return " ".join(str(value).strip().split()).casefold()
"""C03 对表和计算：读 CSV、按键匹配、单位换算、逐列差异、受限公式留痕。

应用只写匹配键、别名、换算表、比较列和公式；组件不猜业务上该怎么合并行，
需要同时用两侧列时由应用先合并再调用 calculate。
"""
from __future__ import annotations

import ast
import csv
import io
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, Overflow as DecimalOverflow, localcontext
from typing import Any, Iterable, Mapping, Sequence

from . import common
from .common import Issue, error_body, is_missing

VERSION = "1.0.0"

SEP = "\x1f"
_NUM_UNIT = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(.*?)\s*$")
_ALLOWED_FUNCS = ("round", "min", "max", "abs")

__all__ = [
    "VERSION", "Table", "Compare", "Formula", "Diff", "Match", "Reconcile",
    "Trace", "Calc", "read_csv", "reconcile", "calculate", "Issue", "error_body",
]


def _num(value: Any) -> int | float | None:
    """数字归一：整数保持 int，小数不做显示舍入，过滤 NaN/Inf 与精度损失。"""
    return common.as_number(value)


@dataclass
class Table:
    rows: list[dict[str, str]]
    columns: list[str]
    errors: list[Issue]
    row_numbers: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "columns": list(self.columns),
            "rows": self.rows,
            "errors": [issue.to_dict() for issue in self.errors],
        }


@dataclass(frozen=True)
class Compare:
    column: str
    unit: str = ""
    tolerance: float = 0.0

    def __post_init__(self) -> None:
        if not self.column:
            raise ValueError("比较列不能为空")
        if self.tolerance < 0:
            raise ValueError("tolerance 不能为负")


@dataclass(frozen=True)
class Formula:
    name: str
    expr: str
    unit: str = ""

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise ValueError(f"公式名 {self.name!r} 不是合法标识符")
        if not str(self.expr).strip():
            raise ValueError("公式表达式不能为空")


@dataclass
class Diff:
    column: str
    left: int | float | None
    right: int | float | None
    delta: int | float | None
    unit: str
    status: str  # same | diff | error

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "left": self.left,
            "right": self.right,
            "delta": self.delta,
            "unit": self.unit,
            "status": self.status,
        }


@dataclass
class Match:
    key: str
    left: dict[str, str]
    right: dict[str, str]
    diffs: list[Diff]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "left": self.left,
            "right": self.right,
            "diffs": [diff.to_dict() for diff in self.diffs],
        }


@dataclass
class Reconcile:
    ok: bool
    matches: list[Match]
    only_left: list[dict[str, str]]
    only_right: list[dict[str, str]]
    duplicates: dict[str, list[str]]
    errors: list[Issue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "matches": [match.to_dict() for match in self.matches],
            "only_left": self.only_left,
            "only_right": self.only_right,
            "duplicates": {"left": list(self.duplicates.get("left", [])), "right": list(self.duplicates.get("right", []))},
            "errors": [issue.to_dict() for issue in self.errors],
        }


@dataclass
class Trace:
    row: int
    name: str
    expr: str
    result: int | float
    unit: str
    inputs: dict[str, int | float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "name": self.name,
            "expr": self.expr,
            "result": self.result,
            "unit": self.unit,
            "inputs": self.inputs,
        }


@dataclass
class Calc:
    ok: bool
    rows: list[dict[str, Any]]
    traces: list[Trace]
    errors: list[Issue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "rows": self.rows,
            "traces": [trace.to_dict() for trace in self.traces],
            "errors": [issue.to_dict() for issue in self.errors],
        }


def read_csv(text: str, *, delimiter: str = ",") -> Table:
    """读 CSV 文本：首行表头，单元格去首尾空白，空行跳过，列数不齐报行号。

    严格解析：未闭合引号、超长单元格、NUL 等 `csv.Error` 转成带行号的 Table 错误，
    不让损坏文件继续产出成功结果。
    """
    if text is None or not str(text).strip():
        return Table(rows=[], columns=[], errors=[Issue("empty_table", "表格没有内容")])

    reader = csv.reader(io.StringIO(str(text).lstrip("\ufeff")), delimiter=delimiter, strict=True)
    indexed: list[tuple[int, list[str]]] = []
    last_line = 0
    try:
        for last_line, row in enumerate(reader, start=1):
            indexed.append((last_line, [str(cell).strip() for cell in row]))
    except csv.Error as exc:
        return Table(
            rows=[],
            columns=[],
            errors=[Issue("csv_error", f"CSV 解析失败：{exc}", row=last_line + 1)],
        )
    records = [(line, cells) for line, cells in indexed if any(cells)]
    if not records:
        return Table(rows=[], columns=[], errors=[Issue("empty_table", "表格没有内容")])

    header_line, header = records[0]
    errors: list[Issue] = []
    if not header or any(not name for name in header):
        errors.append(Issue("bad_header", "表头有空列名", row=header_line))
    if len(set(header)) != len(header):
        errors.append(Issue("bad_header", "表头有重复列名", row=header_line))
    if len(records) == 1:
        errors.append(Issue("empty_table", "表格只有表头，没有数据行"))
        return Table(rows=[], columns=header, errors=errors)

    rows: list[dict[str, str]] = []
    row_numbers: list[int] = []
    for line, cells in records[1:]:
        if len(cells) != len(header):
            errors.append(Issue(
                "row_columns", f"第 {line} 行有 {len(cells)} 列，表头 {len(header)} 列", row=line
            ))
            continue
        rows.append(dict(zip(header, cells)))
        row_numbers.append(line)
    return Table(rows=rows, columns=header, errors=errors, row_numbers=row_numbers)


def _source_rows(source: Any) -> tuple[list[dict[str, Any]], list[int], list[Issue]]:
    """接受 Table 或行对象序列；返回行、行号和表级错误。"""
    if isinstance(source, Table):
        numbers = source.row_numbers or list(range(1, len(source.rows) + 1))
        return list(source.rows), list(numbers), list(source.errors)
    if isinstance(source, Mapping):
        source = source.get("rows", [])
    rows = [dict(row) for row in source]
    return rows, list(range(1, len(rows) + 1)), []


def _display(row: Mapping[str, Any], keys: Sequence[str]) -> str:
    return " / ".join(str(row.get(key, "")).strip() for key in keys)


def _index_rows(
    rows: Sequence[Mapping[str, Any]],
    numbers: Sequence[int],
    keys: Sequence[str],
    aliases: Mapping[str, str],
    side: str,
    errors: list[Issue],
) -> tuple[dict[str, tuple[int, Mapping[str, Any]]], list[str]]:
    seen: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
    for number, row in zip(numbers, rows):
        parts: list[str] = []
        empty_column = ""
        for key in keys:
            part = common.normalize_key(row.get(key))
            part = aliases.get(part, part)
            if not part and not empty_column:
                empty_column = str(key)
            parts.append(part)
        if empty_column:
            errors.append(Issue(
                "empty_key", f"{side}表匹配键为空：{empty_column}", row=number, column=empty_column
            ))
            continue
        seen.setdefault(SEP.join(parts), []).append((number, row))

    index: dict[str, tuple[int, Mapping[str, Any]]] = {}
    duplicates: list[str] = []
    for key, entries in seen.items():
        if len(entries) > 1:
            number, row = entries[0]
            duplicates.append(_display(row, keys))
            errors.append(Issue(
                "duplicate_key", f"{side}表匹配键重复：{_display(row, keys)}", row=number, column=str(keys[0])
            ))
            continue
        index[key] = entries[0]
    return index, duplicates


def _scale(
    number: int | float, factor: Any, column: str, row: int
) -> tuple[int | float | None, Issue | None]:
    """按换算系数做十进制精确换算；无法无损表示为 int/float 时明确报错。

    不能先把大整数乘成 float 再检查：那一步已经丢掉差异，后续只能看到相同的浮点值。
    """
    if factor == 1:
        return number, None
    try:
        left = Decimal(number) if isinstance(number, int) else Decimal(str(number))
        right = Decimal(str(factor))
    except (InvalidOperation, ValueError):
        return None, Issue("not_number", f"{column} 换算系数不合法", row=row, column=column)
    precision = len(left.as_tuple().digits) + len(right.as_tuple().digits) + 2
    try:
        with localcontext() as ctx:
            ctx.prec = max(28, precision)
            scaled = left * right
    except (DecimalOverflow, InvalidOperation):
        return None, Issue("not_number", f"{column} 换算后超出范围", row=row, column=column)
    if not scaled.is_finite():
        return None, Issue("not_number", f"{column} 换算后超出范围", row=row, column=column)
    if scaled == scaled.to_integral_value():
        return int(scaled), None
    try:
        value = float(scaled)
    except (OverflowError, ValueError):
        return None, Issue("not_number", f"{column} 换算后超出范围", row=row, column=column)
    if not math.isfinite(value) or Decimal(str(value)) != scaled:
        return None, Issue("not_number", f"{column} 换算后精度超出范围", row=row, column=column)
    return value, None


def _quantity(
    value: Any, units: Mapping[str, float] | None, column: str, row: int
) -> tuple[int | float | None, Issue | None]:
    """把单元格换成基准单位的数字；带单位但换算表没有时报 unit_unknown。

    溢出、无法无损表示的数字返回 not_number，不能返回 None 让调用方做减法时抛 500。
    """
    if is_missing(value):
        return None, Issue("empty_value", f"{column} 为空", row=row, column=column)
    if isinstance(value, bool):
        return None, Issue("not_number", f"{column} 不是数字", row=row, column=column)
    if isinstance(value, (int, float)):
        number = _num(value)
        if number is None:
            return None, Issue("not_number", f"{column} 不是有限数字或精度超出范围", row=row, column=column)
        return number, None

    text = str(value).strip()
    match = _NUM_UNIT.match(text)
    if not match:
        return None, Issue("not_number", f"{column} 不是数字：{text}", row=row, column=column)
    number = _num(match.group(1))
    if number is None:
        return None, Issue(
            "not_number", f"{column} 不是有限数字或精度超出范围：{match.group(1)}",
            row=row, column=column,
        )
    unit = (match.group(2) or "").strip()
    if unit:
        if not units or unit not in units:
            return None, Issue(
                "unit_unknown", f"{column} 的单位 {unit} 不在换算表", row=row, column=column
            )
        return _scale(number, units[unit], column, row)
    return number, None


def reconcile(
    left: Any,
    right: Any,
    *,
    on: str | Sequence[str],
    aliases: Mapping[str, str] | None = None,
    compare: Sequence[Compare] = (),
    units: Mapping[str, float] | None = None,
) -> Reconcile:
    """按匹配键对齐两张表，输出匹配、仅左、仅右、重复键与逐列差异。"""
    keys = [on] if isinstance(on, str) else list(on)
    if not keys:
        raise ValueError("on 不能为空")
    alias_map = {common.normalize_key(k): common.normalize_key(v) for k, v in (aliases or {}).items()}
    compares = tuple(compare)

    left_rows, left_numbers, left_errors = _source_rows(left)
    right_rows, right_numbers, right_errors = _source_rows(right)
    if left_errors or right_errors:
        return Reconcile(
            ok=False, matches=[], only_left=[], only_right=[],
            duplicates={"left": [], "right": []}, errors=list(left_errors) + list(right_errors),
        )

    errors: list[Issue] = []
    left_index, left_duplicates = _index_rows(left_rows, left_numbers, keys, alias_map, "左", errors)
    right_index, right_duplicates = _index_rows(right_rows, right_numbers, keys, alias_map, "右", errors)

    matches: list[Match] = []
    for key, (left_line, left_row) in left_index.items():
        if key not in right_index:
            continue
        right_line, right_row = right_index[key]
        diffs: list[Diff] = []
        for item in compares:
            if item.column not in left_row or item.column not in right_row:
                errors.append(Issue(
                    "no_column", f"列 {item.column} 不在一侧", row=left_line, column=item.column
                ))
                continue
            left_value, left_issue = _quantity(left_row.get(item.column), units, item.column, left_line)
            right_value, right_issue = _quantity(right_row.get(item.column), units, item.column, right_line)
            if left_issue is not None:
                errors.append(left_issue)
            if right_issue is not None:
                errors.append(right_issue)
            if left_issue is not None or right_issue is not None:
                diffs.append(Diff(item.column, left_value, right_value, None, item.unit, "error"))
                continue
            try:
                raw_delta = right_value - left_value
            except OverflowError:
                # 极大整数与浮点混算可能溢出；值本身有效，只把 delta 留空并判为差异。
                raw_delta = None
            if raw_delta is None:
                diffs.append(Diff(item.column, left_value, right_value, None, item.unit, "diff"))
                continue
            delta = _num(raw_delta)
            status = "same" if abs(raw_delta) <= item.tolerance + 1e-12 else "diff"
            diffs.append(Diff(item.column, left_value, right_value, delta, item.unit, status))
        matches.append(Match(_display(left_row, keys), left_row, right_row, diffs))

    only_left = [dict(row) for key, (_, row) in left_index.items() if key not in right_index]
    only_right = [dict(row) for key, (_, row) in right_index.items() if key not in left_index]
    return Reconcile(
        ok=not errors,
        matches=matches,
        only_left=only_left,
        only_right=only_right,
        duplicates={"left": left_duplicates, "right": right_duplicates},
        errors=errors,
    )


class _Stop(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _collect_names(tree: ast.AST) -> list[str]:
    func_names = {
        id(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and id(node) not in func_names:
            if node.id not in names:
                names.append(node.id)
    return names


def _eval_node(node: ast.AST, env: Mapping[str, Any]) -> int | float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise _Stop("formula_error", "公式只能包含数字")
        return node.value

    if isinstance(node, ast.Name):
        if node.id not in env:
            raise _Stop("unknown_name", f"变量 {node.id} 取不到")
        if env[node.id] is None:
            raise _Stop("not_number", f"变量 {node.id} 不是数字")
        return env[node.id]

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand, env)
        return value if isinstance(node.op, ast.UAdd) else -value

    if isinstance(node, ast.BinOp) and isinstance(
        node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
    ):
        left = _eval_node(node.left, env)
        right = _eval_node(node.right, env)
        try:
            if isinstance(node.op, ast.Pow):
                if (abs(right) > 1000 and abs(left) > 1) or (abs(left) > 1e6 and abs(right) > 100):
                    raise _Stop("formula_error", "公式结果过大")
                return left ** right
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise _Stop("divide_by_zero", "公式除以零")
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            return left % right
        except ZeroDivisionError as exc:
            raise _Stop("divide_by_zero", "公式除以零") from exc
        except OverflowError as exc:
            raise _Stop("formula_error", "公式结果不是有限数") from exc

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise _Stop("formula_error", "公式只能调用 round/min/max/abs")
        if node.keywords or any(isinstance(arg, ast.Starred) for arg in node.args):
            raise _Stop("formula_error", "公式函数不支持关键字或展开参数")
        args = [_eval_node(arg, env) for arg in node.args]
        functions = {"round": round, "min": min, "max": max, "abs": abs}
        try:
            return functions[node.func.id](*args)
        except (TypeError, ValueError) as exc:
            raise _Stop("formula_error", f"函数 {node.func.id} 参数不正确") from exc

    raise _Stop("formula_error", f"不支持的公式语法：{type(node).__name__}")


def _eval_formula(formula: Formula, env: Mapping[str, Any]) -> tuple[int | float, dict[str, int | float]]:
    try:
        tree = ast.parse(formula.expr, mode="eval")
    except SyntaxError as exc:
        raise _Stop("formula_error", f"公式语法错误：{exc.msg}") from exc

    inputs: dict[str, int | float] = {}
    for name in _collect_names(tree):
        if name not in env:
            raise _Stop("unknown_name", f"变量 {name} 取不到")
        if env[name] is None:
            raise _Stop("not_number", f"变量 {name} 不是数字")
        inputs[name] = env[name]
    number = _num(_eval_node(tree.body, env))
    if number is None:
        raise _Stop("formula_error", "公式结果不是有限数")
    return number, inputs


def calculate(
    rows: Any,
    formulas: Sequence[Formula],
    *,
    units: Mapping[str, float] | None = None,
) -> Calc:
    """逐行顺序执行公式；后面的公式可以引用前面的结果，失败的行记错误并停在该行。"""
    source_rows, numbers, source_errors = _source_rows(rows)
    items = tuple(formulas)
    names = [item.name for item in items]
    if len(set(names)) != len(names):
        raise ValueError("公式名重复")

    if source_errors:
        return Calc(ok=False, rows=[], traces=[], errors=list(source_errors))

    out_rows: list[dict[str, Any]] = [dict(row) for row in source_rows]
    traces: list[Trace] = []
    errors: list[Issue] = []
    for index, (number, row) in enumerate(zip(numbers, source_rows)):
        env: dict[str, Any] = {}
        for column, value in row.items():
            quantity, _ = _quantity(value, units, str(column), number)
            env[str(column)] = quantity
        for formula in items:
            try:
                result, inputs = _eval_formula(formula, env)
            except _Stop as stop:
                errors.append(Issue(stop.code, stop.message, row=number, column=formula.name))
                break
            env[formula.name] = result
            out_rows[index][formula.name] = result
            traces.append(Trace(number, formula.name, formula.expr, result, formula.unit, inputs))
    return Calc(ok=not errors, rows=out_rows, traces=traces, errors=errors)
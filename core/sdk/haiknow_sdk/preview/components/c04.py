"""C04 进度和提醒：节点状态、逾期规则、提醒去重与投递记录。

应用只写业务节点、责任人和逾期/升级办法；组件负责算状态、找出该提醒谁、
按历史去重、在改期后重算，并把「谁在什么时候提醒过、失败几次」变成可读记录。
发送动作由应用完成：把 `Reminder.to_dict()` 交给 `ctx.preview.jobs.submit`
（或平台后续的 v1 通知接口），再把结果用 `record` 写回历史。组件不连队列、不读环境变量。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from .common import Issue

VERSION = "1.0.0"

STATUSES = ("未到期", "受阻", "逾期", "按期完成", "逾期完成")
LEVELS = ("提醒", "升级", "严重")
CHANNELS = ("notification", "job")

__all__ = [
    "VERSION", "STATUSES", "LEVELS", "CHANNELS", "Node", "Escalation", "Policy",
    "Reminder", "State", "Plan", "Delivery", "plan", "record", "retryable", "Issue",
]


@dataclass(frozen=True)
class Node:
    """一个业务节点。planned / actual 接受 date、datetime 或 ISO 字符串。"""

    id: str
    name: str = ""
    owner: str = ""
    planned: Any = None
    actual: Any = None
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("节点 id 不能为空")
        object.__setattr__(self, "depends_on", tuple(self.depends_on or ()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "owner": self.owner,
            "planned": _raw_text(self.planned),
            "actual": _raw_text(self.actual),
            "dependsOn": list(self.depends_on),
        }


@dataclass(frozen=True)
class Escalation:
    """逾期到 N 天后追加的提醒对象；level 用于前端分级显示。"""

    after_days: int
    targets: tuple[str, ...]
    level: str = "升级"

    def __post_init__(self) -> None:
        if not isinstance(self.after_days, int) or isinstance(self.after_days, bool) or self.after_days < 0:
            raise ValueError("升级天数必须是非负整数")
        targets = tuple(str(item).strip() for item in (self.targets or ()) if str(item).strip())
        if not targets:
            raise ValueError("升级对象不能为空")
        if self.level not in LEVELS:
            raise ValueError(f"未知提醒等级 {self.level}，只能是 {LEVELS}")
        object.__setattr__(self, "targets", targets)

    def to_dict(self) -> dict[str, Any]:
        return {"afterDays": self.after_days, "targets": list(self.targets), "level": self.level}


@dataclass(frozen=True)
class Policy:
    """逾期规则与提醒办法。repeat_after_days 为空表示同一事件同一对象只提醒一次。"""

    grace_days: int = 0
    repeat_after_days: int | None = None
    escalations: tuple[Escalation, ...] = ()
    channel: str = "job"
    operation: str = "remind"

    def __post_init__(self) -> None:
        if not isinstance(self.grace_days, int) or isinstance(self.grace_days, bool) or self.grace_days < 0:
            raise ValueError("宽限天数必须是非负整数")
        if self.repeat_after_days is not None and (
            not isinstance(self.repeat_after_days, int)
            or isinstance(self.repeat_after_days, bool)
            or self.repeat_after_days < 0
        ):
            raise ValueError("重提间隔必须是非负整数或空")
        if self.channel not in CHANNELS:
            raise ValueError(f"未知提醒通道 {self.channel}，只能是 {CHANNELS}")
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise ValueError("提醒操作名不能为空")
        object.__setattr__(self, "escalations", tuple(self.escalations or ()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "graceDays": self.grace_days,
            "repeatAfterDays": self.repeat_after_days,
            "escalations": [item.to_dict() for item in self.escalations],
            "channel": self.channel,
            "operation": self.operation,
        }


@dataclass(frozen=True)
class Reminder:
    id: str
    event: str
    node: str
    name: str
    owner: str
    target: str
    level: str
    planned: str
    days_late: int
    attempt: int
    channel: str
    operation: str
    message: str
    kind: str = "overdue"

    @property
    def idempotency_key(self) -> str:
        return self.id

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "idempotencyKey": self.idempotency_key,
            "event": self.event,
            "node": self.node,
            "name": self.name,
            "owner": self.owner,
            "target": self.target,
            "level": self.level,
            "kind": self.kind,
            "planned": self.planned,
            "daysLate": self.days_late,
            "attempt": self.attempt,
            "channel": self.channel,
            "operation": self.operation,
            "message": self.message,
        }


@dataclass(frozen=True)
class State:
    id: str
    name: str
    owner: str
    planned: str
    actual: str
    status: str
    days_late: int
    blocked_by: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "owner": self.owner,
            "planned": self.planned,
            "actual": self.actual,
            "status": self.status,
            "daysLate": self.days_late,
            "blockedBy": list(self.blocked_by),
        }


@dataclass
class Plan:
    states: list[State]
    reminders: list[Reminder]
    skipped: list[dict[str, Any]]
    errors: list[Issue]
    history: list[dict[str, Any]]

    @property
    def ok(self) -> bool:
        return not self.errors

    def by_status(self) -> dict[str, int]:
        counts = {name: 0 for name in STATUSES}
        for state in self.states:
            counts[state.status] = counts.get(state.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "states": [state.to_dict() for state in self.states],
            "reminders": [reminder.to_dict() for reminder in self.reminders],
            "skipped": [dict(item) for item in self.skipped],
            "byStatus": self.by_status(),
            "errors": [issue.to_dict() for issue in self.errors],
        }


# 投递历史就是普通 dict 列表，应用直接存进 ctx.kv / records。
Delivery = dict[str, Any]

_MISSING = object()


def plan(
    nodes: Sequence[Node],
    policy: Policy | None = None,
    *,
    now: Any,
    history: Iterable[Mapping[str, Any]] | None = None,
) -> Plan:
    """计算节点状态并给出本轮该发的提醒；已发过的同一事件同一对象按历史去重。"""
    rule = policy or Policy()
    current = _as_datetime(now, "now", None)
    if current is None:
        raise ValueError("now 必须是合法的 ISO 日期或时间")
    entries = [dict(item) for item in (history or ())]

    items = tuple(nodes or ())
    errors: list[Issue] = []
    by_id: dict[str, Node] = {}
    for node in items:
        if not isinstance(node, Node):
            raise TypeError("nodes 里只能是 Node")
        if node.id in by_id:
            errors.append(Issue("duplicate_node", f"节点 id 重复：{node.id}", field=node.id))
            continue
        by_id[node.id] = node

    parsed: dict[str, tuple[datetime | None, datetime | None, list[str]]] = {}
    for node in items:
        if node.id in parsed:
            continue  # 重复 id 已在 errors 里报告，只按第一个算
        planned = _as_datetime(node.planned, "planned", node.id, errors)
        actual = _as_datetime(node.actual, "actual", node.id, errors)
        unknown = [dep for dep in node.depends_on if dep not in by_id]
        for dep in unknown:
            errors.append(Issue("unknown_dependency", f"节点 {node.id} 依赖不存在的节点 {dep}", field=node.id))
        parsed[node.id] = (planned, actual, unknown)

    states: list[State] = []
    reminders: list[Reminder] = []
    skipped: list[dict[str, Any]] = []
    latest = _latest_deliveries(entries)

    for node in items:
        if by_id.get(node.id) is not node:
            continue  # 重复 id 已在 errors 里报告，只按第一个算
        planned, actual, unknown_deps = parsed[node.id]
        blocked_by = unknown_deps + [
            dep for dep in node.depends_on
            if dep in by_id and parsed.get(dep, (None, None, []))[1] is None
        ]
        if planned is None:
            if node.planned in (None, ""):
                errors.append(Issue("no_planned", f"节点 {node.name or node.id} 没有计划时间", field=node.id))
            states.append(State(node.id, node.name, node.owner, "", _text(actual), "未到期", 0, tuple(blocked_by)))
            continue

        if actual is not None:
            late = _days(actual - planned)
            status = "逾期完成" if actual > planned else "按期完成"
            states.append(State(node.id, node.name, node.owner, _text(planned), _text(actual), status, max(late, 0), tuple(blocked_by)))
            continue

        overdue = current > planned + _days_delta(rule.grace_days)
        days_late = max(_days(current - planned), 0)
        if overdue:
            status = "逾期"
        elif blocked_by:
            status = "受阻"
        else:
            status = "未到期"
        states.append(State(node.id, node.name, node.owner, _text(planned), "", status, days_late, tuple(blocked_by)))
        if not overdue:
            continue

        if not node.owner.strip():
            errors.append(Issue("no_owner", f"节点 {node.name or node.id} 没有责任人，无法提醒", field=node.id))
            continue

        targets: list[str] = [node.owner.strip()]
        levels: dict[str, str] = {node.owner.strip(): "提醒"}
        for step in sorted(rule.escalations, key=lambda item: item.after_days):
            if days_late < step.after_days:
                continue
            for target in step.targets:
                if target not in levels or levels[target] != "严重":
                    levels[target] = step.level
            targets.extend(step.targets)
        seen: set[str] = set()
        event = f"{node.id}:overdue:{_text(planned)}"
        for target in targets:
            if target in seen:
                continue
            seen.add(target)
            reminder_id = f"{event}@{target}"
            previous = latest.get((event, target))
            if previous and previous.get("status") == "sent":
                if rule.repeat_after_days is None:
                    skipped.append({"event": event, "target": target, "reason": "同一事件同一对象已提醒"})
                    continue
                sent_at = _as_datetime(previous.get("sentAt") or previous.get("at"), "sentAt", None)
                if sent_at is not None and current - sent_at < _days_delta(rule.repeat_after_days):
                    skipped.append({"event": event, "target": target, "reason": "未到重提间隔"})
                    continue
            attempt = 1
            if previous is not None:
                attempt = _positive_int(previous.get("attempts")) + 1
            reminders.append(Reminder(
                id=reminder_id,
                event=event,
                node=node.id,
                name=node.name,
                owner=node.owner,
                target=target,
                level=levels.get(target, "提醒"),
                planned=_text(planned),
                days_late=days_late,
                attempt=attempt,
                channel=rule.channel,
                operation=rule.operation,
                message=f"{node.name or node.id} 逾期 {days_late} 天（计划 {_text(planned)}），请 {target} 跟进",
            ))

    return Plan(states=states, reminders=reminders, skipped=skipped, errors=errors, history=entries)


def record(
    history: Iterable[Mapping[str, Any]] | None,
    reminder: Reminder,
    status: str,
    *,
    error: str = "",
    at: Any = "",
) -> list[Delivery]:
    """追加一条投递结果。sent 才会挡住下次提醒；failed 会在下一轮自动重排。"""
    if status not in ("sent", "failed"):
        raise ValueError("投递状态只能是 sent 或 failed")
    entries = [dict(item) for item in (history or ())]
    entry: Delivery = {
        "id": reminder.id,
        "event": reminder.event,
        "target": reminder.target,
        "status": status,
        "attempts": reminder.attempt,
        "lastError": "" if status == "sent" else str(error or ""),
        "at": _raw_text(at),
    }
    if status == "sent":
        entry["sentAt"] = entry["at"] or _raw_text(datetime.now(timezone.utc).replace(tzinfo=None))
    entries.append(entry)
    return entries


def retryable(history: Iterable[Mapping[str, Any]] | None) -> list[Delivery]:
    """返回每个事件/对象最新一次是 failed 的投递，供应用重试或显示失败原因。"""
    latest = _latest_deliveries(history or ())
    out = [dict(item) for item in latest.values() if item.get("status") == "failed"]
    out.sort(key=lambda item: (str(item.get("event", "")), str(item.get("target", ""))))
    return out


def _latest_deliveries(entries: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], Delivery]:
    latest: dict[tuple[str, str], Delivery] = {}
    for item in entries:
        key = (str(item.get("event", "")), str(item.get("target", "")))
        latest[key] = dict(item)
    return latest


def _positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _as_datetime(value: Any, label: str, node_id: str | None, errors: list[Issue] | None = None) -> datetime | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            parsed = None
    if parsed is None:
        if errors is not None:
            errors.append(Issue("bad_date", f"{label} 不是合法日期：{_raw_text(value)}", field=node_id or ""))
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _text(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.time() == datetime.min.time():
        return value.date().isoformat()
    return value.isoformat(timespec="minutes")


def _raw_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return _text(value if isinstance(value, datetime) else datetime(value.year, value.month, value.day))
    return str(value)


def _days(delta: Any) -> int:
    """整日差；不足一天按 0 天，负值不在这里裁剪。"""
    return math.floor(delta.total_seconds() / 86400) if delta.total_seconds() >= 0 else -math.ceil(-delta.total_seconds() / 86400)


def _days_delta(days: int) -> timedelta:
    return timedelta(days=days)
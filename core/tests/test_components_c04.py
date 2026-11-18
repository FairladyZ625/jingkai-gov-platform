"""C04 进度提醒：状态、逾期/升级、去重、改期重算与投递重试。"""
import pytest

from haiknow_sdk.preview.components import c04

NOW = "2026-11-08"


def codes(result):
    return [issue.code for issue in result.errors]


def nodes():
    return (
        c04.Node("n1", "立项", "张三", "2026-11-01", "2026-10-30"),
        c04.Node("n2", "设计", "李四", "2026-11-05", depends_on=("n1",)),
        c04.Node("n3", "评审", "王五", "2026-11-10"),
        c04.Node("n4", "归档", "赵六", "2026-11-03", "2026-11-06"),
        c04.Node("n5", "打样", "钱七", "2026-11-12", depends_on=("n2",)),
    )


def policy(**overrides):
    data = {"grace_days": 0, "repeat_after_days": None}
    data.update(overrides)
    return c04.Policy(**data)


def by_id(plan):
    return {state.id: state for state in plan.states}


def test_normal_states_and_dependencies():
    plan = c04.plan(nodes(), policy(), now=NOW)
    states = by_id(plan)

    assert plan.ok is True
    assert states["n1"].status == "按期完成"
    assert states["n2"].status == "逾期"
    assert states["n2"].days_late == 3
    assert states["n3"].status == "未到期"
    assert states["n4"].status == "逾期完成"
    assert states["n4"].days_late == 3
    # n5 计划未到但前置 n2 未完成 → 受阻
    assert states["n5"].status == "受阻"
    assert states["n5"].blocked_by == ("n2",)
    assert plan.by_status()["逾期"] == 1


def test_grace_days_keeps_node_not_overdue():
    plan = c04.plan(nodes(), policy(grace_days=3), now="2026-11-07")
    state = by_id(plan)["n2"]

    assert state.status == "未到期"
    assert plan.reminders == []


def test_overdue_reminds_owner_and_escalates_by_target():
    rule = policy(escalations=(
        c04.Escalation(0, ("经理",)),
        c04.Escalation(3, ("总监",), "严重"),
    ))
    plan = c04.plan(nodes(), rule, now=NOW)
    reminder = next(item for item in plan.reminders if item.node == "n2")

    targets = [(item.target, item.level) for item in plan.reminders if item.node == "n2"]
    assert targets == [("李四", "提醒"), ("经理", "升级"), ("总监", "严重")]
    assert reminder.days_late == 3
    assert reminder.channel == "job" and reminder.operation == "remind"
    assert reminder.id == "n2:overdue:2026-11-05@李四"
    assert reminder.idempotency_key == reminder.id
    assert "逾期 3 天" in reminder.message


def test_same_event_same_target_is_not_reminded_twice():
    first = c04.plan(nodes(), policy(), now=NOW)
    sent = []
    for reminder in first.reminders:
        if reminder.node == "n2":
            sent = c04.record(sent, reminder, "sent", at=NOW)

    again = c04.plan(nodes(), policy(), now="2026-11-09", history=sent)

    assert all(item.node != "n2" for item in again.reminders)
    assert any(item["reason"] == "同一事件同一对象已提醒" for item in again.skipped)


def test_repeat_interval_controls_resend_and_attempt():
    first = c04.plan(nodes(), policy(repeat_after_days=2), now=NOW)
    sent = c04.record([], first.reminders[0], "sent", at=NOW)

    too_soon = c04.plan(nodes(), policy(repeat_after_days=2), now="2026-11-09", history=sent)
    assert too_soon.reminders == []

    on_time = c04.plan(nodes(), policy(repeat_after_days=2), now="2026-11-10", history=sent)
    assert on_time.reminders[0].attempt == 2


def test_revised_planned_date_recalculates_and_creates_new_event():
    first = c04.plan(nodes(), policy(), now=NOW)
    sent = c04.record([], first.reminders[0], "sent", at=NOW)

    revised = tuple(
        c04.Node(node.id, node.name, node.owner, "2026-11-20" if node.id == "n2" else node.planned,
                 node.actual, node.depends_on)
        for node in nodes()
    )
    plan = c04.plan(revised, policy(), now=NOW)

    assert by_id(plan)["n2"].status == "未到期"
    assert all(item.node != "n2" for item in plan.reminders)

    pushed_again = tuple(
        c04.Node(node.id, node.name, node.owner, "2026-11-06" if node.id == "n2" else node.planned,
                 node.actual, node.depends_on)
        for node in nodes()
    )
    again = c04.plan(pushed_again, policy(), now=NOW, history=sent)
    reminder = next(item for item in again.reminders if item.node == "n2" and item.target == "李四")
    # 计划日期变了就是新事件，旧事件的已发送记录不能把它挡掉。
    assert reminder.event == "n2:overdue:2026-11-06"
    assert reminder.id.endswith("@李四")


def test_failed_delivery_is_retryable_with_next_attempt():
    first = c04.plan(nodes(), policy(), now=NOW)
    failed = c04.record([], first.reminders[0], "failed", error="队列暂时不可用", at=NOW)

    pending = c04.retryable(failed)
    assert [item["target"] for item in pending] == ["李四"]
    assert pending[0]["lastError"] == "队列暂时不可用"

    again = c04.plan(nodes(), policy(), now=NOW, history=failed)
    retry = next(item for item in again.reminders if item.id == first.reminders[0].id)
    assert retry.attempt == 2


def test_newer_sent_delivery_wins_over_older_failure():
    first = c04.plan(nodes(), policy(), now=NOW)
    history = c04.record([], first.reminders[0], "failed", error="x", at=NOW)
    history = c04.record(history, first.reminders[0], "sent", at="2026-11-08")

    again = c04.plan(nodes(), policy(), now="2026-11-09", history=history)
    assert all(item.id != first.reminders[0].id for item in again.reminders)
    assert c04.retryable(history) == []


def test_bad_node_data_returns_business_errors():
    plan = c04.plan((
        c04.Node("a", "坏日期", "张三", "不是日期"),
        c04.Node("b", "无责任人", "", "2026-11-01"),
        c04.Node("c", "缺计划", "李四"),
        c04.Node("d", "坏依赖", "王五", "2026-11-01", depends_on=("missing",)),
        c04.Node("e", "重复", "赵六", "2026-11-01"),
        c04.Node("e", "重复", "赵六", "2026-11-01"),
    ), policy(), now=NOW)

    assert set(codes(plan)) == {"bad_date", "no_owner", "no_planned", "unknown_dependency", "duplicate_node"}
    # 重复 id 只保留第一个节点的状态
    assert len(plan.states) == 5


def test_contract_errors_are_program_errors():
    with pytest.raises(ValueError, match="节点 id"):
        c04.Node(" ")
    with pytest.raises(ValueError, match="升级天数"):
        c04.Escalation(-1, ("经理",))
    with pytest.raises(ValueError, match="升级对象"):
        c04.Escalation(1, ())
    with pytest.raises(ValueError, match="未知提醒等级"):
        c04.Escalation(1, ("经理",), "最高")
    with pytest.raises(ValueError, match="宽限天数"):
        c04.Policy(grace_days=-1)
    with pytest.raises(ValueError, match="重提间隔"):
        c04.Policy(repeat_after_days=-1)
    with pytest.raises(ValueError, match="未知提醒通道"):
        c04.Policy(channel="sms")
    with pytest.raises(ValueError, match="now"):
        c04.plan(nodes(), policy(), now="not-a-date")
    with pytest.raises(ValueError, match="投递状态"):
        c04.record([], c04.plan(nodes(), policy(), now=NOW).reminders[0], "unknown")


def test_to_dict_uses_camel_case_and_counts():
    plan = c04.plan(nodes(), policy(), now=NOW)
    data = plan.to_dict()

    assert data["ok"] is True
    assert data["states"][1]["daysLate"] == 3
    assert data["reminders"][0]["idempotencyKey"] == data["reminders"][0]["id"]
    assert data["byStatus"]["逾期完成"] == 1


def test_datetime_and_date_inputs_are_accepted():
    plan = c04.plan((
        c04.Node("a", "日期对象", "张三", __import__("datetime").date(2026, 11, 1)),
        c04.Node("b", "时间对象", "李四", __import__("datetime").datetime(2026, 11, 1, 9, 0)),
    ), policy(), now="2026-11-08T10:00:00")

    assert [state.status for state in plan.states] == ["逾期", "逾期"]
    assert plan.states[1].planned == "2026-11-01T09:00"
import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from jkq.admin import usage


def test_blocked_only_does_not_create_usage_breakdowns():
    now = datetime(2026, 11, 23, 8, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    with sqlite3.connect(":memory:") as db:
        db.execute("create table audit(ts, app_id, action, detail)")
        db.execute("insert into audit values (?,?,?,?)", (now.timestamp(), "skills", "ai.outbound_denied", '{"capability":"chat"}'))
        assert usage.usage_summary(db, now=now) == {
            "today": 0, "week": 0, "blockedToday": 1, "blockedWeek": 1,
            "byApp": [], "byModel": [], "localShare": None,
        }


def test_weekly_model_attempts_and_outbound_denials_use_different_counts():
    beijing = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 11, 25, 8, 30, tzinfo=beijing)
    model = {"model": "测试本地模型", "providerKind": "local"}
    with sqlite3.connect(":memory:") as db:
        db.execute("create table audit(ts, app_id, action, detail)")
        for day, app, action, detail in (
            (22, "platform", "ai.chat", model),  # 上一周
            (23, "skills", "ai.chat", model),
            (25, "skills", "ai.chat", {"model": "测试在线模型", "providerKind": "cloud", "status": "provider_error"}),
            (25, "skills", "ai.outbound_denied", {"capability": "chat"}),
            (25, "platform", "ai.outbound_denied", {"capability": "parse"}),
            (25, "skills", "job.failed", {}),
            (26, "platform", "ai.chat", model),  # 未来时间戳
        ):
            stamp = now.replace(day=day, hour=8, minute=0).timestamp()
            db.execute("insert into audit values (?,?,?,?)", (stamp, app, action, json.dumps(detail)))
        summary = usage.usage_summary(db, now=now)
        assert summary["today"] == 1 and summary["week"] == 2
        assert summary["blockedToday"] == summary["blockedWeek"] == 1
        assert summary["byApp"] == [{"name": "skills", "calls": 2}]
        assert sum(row["calls"] for row in summary["byModel"]) == 2
        assert summary["localShare"] == 50
        db.execute("insert into audit values (?,?,?,?)", (now.timestamp(), "skills", "ai.chat", '{"model":"旧记录"}'))
        assert usage.usage_summary(db, now=now)["localShare"] is None

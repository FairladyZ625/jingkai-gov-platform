"""定时调度：声明加载、绑定身份、假时钟触发与最近一次补跑。"""
from datetime import datetime, timezone
import json
import time
from types import SimpleNamespace

import pytest

from conftest import ROOT
from test_platform import login


ROUTER = '''
from haiknow_sdk import AppContext, app_context
from haiknow_sdk.preview.jobs import operation
from haiknow_sdk.preview.schedules import schedule
from fastapi import APIRouter, Depends

router = APIRouter()

@operation("remind", version="1")
@schedule("daily", operation="remind", projects=("sample-project",), at=("09:00", "14:00"))
def remind(job, body):
    job.context.kv.put("fired", job.context.kv.get("fired", 0) + 1)
    return {"ok": True}

@router.get("/fired")
def fired(ctx: AppContext = Depends(app_context)):
    return {"value": ctx.kv.get("fired", 0)}
'''


@pytest.fixture(autouse=True)
def schedule_clock(monkeypatch):
    from haiknow_core.schedules import service

    enabled_at = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(service, "time", SimpleNamespace(time=lambda: enabled_at))


def _client(make_client, tmp_path):
    apps = tmp_path / "apps"
    manifest = json.loads((ROOT / "tests/fixtures/platform-app/app.json").read_text())
    path = apps / "sched-a"
    (path / "api").mkdir(parents=True)
    (path / "app.json").write_text(json.dumps({**manifest, "id": "sched-a"}))
    (path / "api/router.py").write_text(ROUTER)
    return make_client(apps)


def _wait(client, job_id):
    for _ in range(300):
        row = client.get(f"/api/v1/jobs/{job_id}").json()
        if row.get("status") in {"done", "failed", "cancelled"}:
            return row
        time.sleep(.01)
    raise AssertionError(row)


def test_schedule_tick_submits_and_is_idempotent(make_client, tmp_path):
    client = _client(make_client, tmp_path)
    with client:
        login(client, "sampleadmin")
        listed = client.get("/api/v1/schedules?app=sched-a")
        assert listed.status_code == 200, listed.text
        assert listed.json()["items"][0]["name"] == "daily"
        enabled = client.post("/api/v1/schedules/sched-a/daily/enable?project=sample-project")
        assert enabled.status_code == 200, enabled.text
        service = client.app.state.platform.schedules
        now = datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc)  # Asia/Shanghai 14:00
        runs = service.tick(now)
        assert len(runs) == 1 and runs[0]["status"] == "submitted"
        assert _wait(client, runs[0]["jobId"])["status"] == "done"
        assert service.tick(now) == []
        assert client.get("/api/apps/sched-a/fired").json()["value"] == 1


def test_restart_only_catches_latest_missed_occurrence(make_client, tmp_path):
    client = _client(make_client, tmp_path)
    login(client, "sampleoperator")
    assert client.post("/api/v1/schedules/sched-a/daily/enable?project=sample-project").status_code == 200
    service = client.app.state.platform.schedules
    # 15:00 Shanghai missed both 09:00 and 14:00; startup policy submits only 14:00.
    runs = service.tick(datetime(2026, 11, 10, 7, 0, tzinfo=timezone.utc), startup=True)
    assert len(runs) == 1
    assert runs[0]["slot"] == "2026-11-10T06:00:00+00:00"


def test_lost_submitter_records_skipped_without_new_job(make_client, tmp_path):
    client = _client(make_client, tmp_path)
    login(client, "sampleoperator")
    assert client.post("/api/v1/schedules/sched-a/daily/enable?project=sample-project").status_code == 200
    client.app.state.platform.store._db.execute("update users set status='disabled' where id='sampleoperator'")
    client.app.state.platform.store._db.commit()
    run = client.app.state.platform.schedules.tick(datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc))[0]
    assert run["status"] == "skipped" and run["reason"] == "submitter_unavailable"


def test_pause_and_run_now_require_admin(make_client, tmp_path):
    client = _client(make_client, tmp_path)
    login(client, "sampleoperator")
    assert client.post("/api/v1/schedules/sched-a/daily/enable?project=sample-project").status_code == 200
    assert client.post("/api/v1/schedules/sched-a/daily/pause?project=sample-project").status_code == 403
    login(client, "sampleadmin")
    assert client.post("/api/v1/schedules/sched-a/daily/pause?project=sample-project").status_code == 200
    assert client.post("/api/v1/schedules/sched-a/daily/resume?project=sample-project").status_code == 200
    login(client, "sampleoperator")
    assert client.post("/api/v1/schedules/sched-a/daily/pause?project=sample-project").status_code == 403
    login(client, "sampleadmin")
    assert client.post("/api/v1/schedules/sched-a/daily/pause?project=sample-project").status_code == 200
    assert client.post("/api/v1/schedules/sched-a/daily/run?project=sample-project").status_code == 409

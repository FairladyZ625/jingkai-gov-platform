"""企业诉求及到期提醒，使用隔离的真实 core、消息收件箱和调度。"""
import json
import shutil
import sys
import time
from datetime import date, timedelta
from importlib.util import find_spec
from pathlib import Path

import pytest

APP = "/api/apps/enterprise"
ISSUES = APP + "/issues"
START = date(2026, 11, 18)


@pytest.fixture
def site(isolated_platform, make_client, tmp_path, monkeypatch):
    config, apps = isolated_platform
    directory = apps / "enterprise"
    shutil.copytree(Path(__file__).resolve().parents[1] / "api", directory / "api")
    manifest = json.loads((apps / "sample-app/app.json").read_text())
    manifest.update(id="enterprise", defaultRoles={"partner": ["view", "operate"]})
    (directory / "app.json").write_text(json.dumps(manifest))
    (config / "projects.yaml").write_text(json.dumps({"companies": [
        {"id": "demo", "name": "虚构机构", "projects": [{"id": "jkq", "name": "测试"}]}]}))
    users = json.loads((config / "users.yaml").read_text())
    users["users"].append({"id": "partner", "name": "协作", "roles": ["partner"], "projects": ["jkq"]})
    (config / "users.yaml").write_text(json.dumps(users))
    monkeypatch.setenv("JKQ_ENTERPRISE_PRIVATE_DB", str(tmp_path.parent / (tmp_path.name + ".sqlite")))
    client = make_client()
    if find_spec("jkq.inbox"):
        from jkq.inbox import router
        client.app.include_router(router)
    with client:
        clock = [START]
        monkeypatch.setattr(sys.modules["haiknow_apps.enterprise.requests"], "today", lambda: clock[0])
        assert client.post("/api/auth/login", json={"user_id": "sampleadmin"}).is_success
        yield client, clock


def create_company(c, **fields):
    res = c.post(APP + "/companies", json={"name": "演示企业", **fields})
    assert res.is_success, res.text
    return res.json()["item"]["id"]


def create_issue(c, company, **fields):
    res = c.post(ISSUES, json={"entId": company, "title": "演示诉求详情", **fields})
    assert res.is_success, res.text
    return res.json()["item"]


def test_issue_lifecycle(site):
    c, _ = site
    ent = create_company(c)
    item = create_issue(c, ent)
    url = ISSUES + "/" + item["id"]
    res = c.patch(url, json={"status": "待补材料", "note": "已联系", "next": "等待补件"})
    updated = res.json()["item"]
    assert updated["steps"] == [*item["steps"], [START.isoformat(),
        "状态：办理中 → 待补材料 · 下一步：未填写 → 等待补件 · 备注：已联系 · 操作人：样例管理员"]]
    assert c.patch(url, json={"status": "待补材料"}).json()["item"]["steps"] == updated["steps"]
    listing = c.get(ISSUES, params={"entId": ent, "status": "待补材料", "owner": item["owner"]}).json()
    assert listing["items"] == [{**updated, "entName": "演示企业"}]
    assert c.get(ISSUES, params={"status": "已办结"}).json()["items"] == []
    assert c.post("/api/auth/login", json={"user_id": "partner"}).is_success
    assert "演示诉求详情" not in c.get(ISSUES).text
    assert "已联系" not in c.get(ISSUES).text
    assert c.patch(url, json={"status": "已办结"}).status_code == 403


def test_policy_issue_source_round_trip(site):
    client, _ = site
    company = create_company(client)
    body = {"entId": company, "title": "咨询公开政策", "from": "政策咨询"}
    created = client.post(ISSUES, json=body)
    assert created.status_code == 200
    item = created.json()["item"]
    assert item["from"] == body["from"]
    invalid = client.post(ISSUES, json={**body, "from": "未知来源"})
    assert (invalid.status_code, invalid.json()["error"]["code"]) == (400, "INVALID_REQUEST")
    listing = client.get(ISSUES, params={"entId": company})
    assert listing.status_code == 200
    assert listing.json()["items"] == [{**item, "entName": "演示企业"}]


def test_invalid_requests(site):
    c, _ = site
    for body, status, code in [
        ({"title": "演示"}, 400, "INVALID_REQUEST"),
        ({"entId": "missing", "title": "演示"}, 404, "NOT_FOUND"),
    ]:
        res = c.post(ISSUES, json=body)
        assert (res.status_code, res.json()["error"]["code"]) == (status, code)
    ent = create_company(c)
    issue = create_issue(c, ent)
    for patch in [{"due": "2026-02-30"}, {"status": "已丢弃"}, {"entId": "x"}]:
        assert c.patch(ISSUES + "/" + issue["id"], json=patch).status_code == 400
    assert c.patch(ISSUES + "/" + ent, json={"status": "已办结"}).status_code == 404


def wait_job(c, job_id):
    for _ in range(300):
        job = c.get("/api/v1/jobs/" + job_id).json()
        if job["status"] in ("done", "failed", "cancelled"):
            assert job["status"] == "done", job
            return
        time.sleep(.01)
    pytest.fail(f"扫描未完成 {job_id}")


def scan(c, key):
    res = c.post("/api/v1/jobs", json={"appId": "enterprise", "project": "jkq",
                 "operation": "enterprise.reminders", "input": {}, "idempotencyKey": key})
    assert res.status_code == 202, res.text
    wait_job(c, res.json()["id"])


def test_daily_reminders_and_reschedule(site):
    c, clock = site
    ent = create_company(c)
    overdue = create_issue(c, ent, due="2026-11-17")
    due_today = create_issue(c, ent, due="2026-11-18")
    closed = create_issue(c, ent, due="2026-11-17")
    c.patch(ISSUES + "/" + closed["id"], json={"status": "已办结"}).raise_for_status()

    def alerts():
        return {a["issueId"] for a in c.get(APP + "/alerts").json()["items"]}

    def inbox():
        items = c.get("/api/v1/messages").json()["items"]
        if find_spec("jkq.inbox"):
            rows = c.get("/api/v1/inbox", params={"box": "todo"}).json()["items"]
            assert {m["id"] for m in items} == {r["id"] for r in rows if r["kind"] == "notice"}
        return [m["source"]["recordId"] for m in items]

    assert alerts() == {overdue["id"]}
    base = "/api/v1/schedules/enterprise/enterprise.daily"
    assert c.post(base + "/enable?project=jkq").is_success
    run = c.post(base + "/run?project=jkq").json()["items"][0]
    wait_job(c, run["jobId"])
    scan(c, "second-scan")
    assert inbox() == [overdue["id"]]
    clock[0] += timedelta(days=1)
    scan(c, "tomorrow")
    assert sorted(inbox()) == sorted([overdue["id"], overdue["id"], due_today["id"]])
    c.patch(ISSUES + "/" + overdue["id"], json={"due": "2026-12-01"}).raise_for_status()
    assert alerts() == {due_today["id"]}
    scan(c, "after-patch")
    assert len(inbox()) == 3


def test_qualification_window(site):
    c, _ = site
    ent = create_company(c, qualifications=[
        {"name": f"资质{i}", "validTo": (START + timedelta(days=i)).isoformat()}
        for i in (-1, 0, 30, 31)] + [{"name": "无截止日期"}])
    alerts = c.get(APP + "/alerts").json()["items"]
    assert [(a["entId"], a["kind"], a["text"]) for a in alerts] == [
        (ent, "资质到期", f"资质{i} 将于 {START + timedelta(days=i)} 到期") for i in (0, 30)]
    scan(c, "first")
    scan(c, "again")
    assert len(c.get("/api/v1/messages").json()["items"]) == 2


def test_explicit_unassigned_owner_and_legacy_default(site):
    client, _ = site
    company = create_company(client)
    unassigned = create_issue(client, company, owner="", due="", next="")
    assert (unassigned["owner"], unassigned["status"], unassigned["due"]) == ("", "待分派", "")
    legacy = create_issue(client, company)
    assert (legacy["owner"], legacy["status"]) == ("sampleadmin", "办理中")


def test_issue_updates_log_each_changed_field_and_clear_values(site):
    client, _ = site
    company = create_company(client)
    item = create_issue(client, company, owner="", due="", next="")
    url = ISSUES + "/" + item["id"]
    update = {"owner": "办理员甲", "due": "2026-12-01", "next": "联系企业", "note": "企业来电确认", "status": "办理中"}
    response = client.patch(url, json=update)
    assert response.is_success, response.text
    row = response.json()["item"]
    assert row["steps"][-1] == [START.isoformat(),
        "状态：待分派 → 办理中 · 负责人：未分派 → 办理员甲 · 截止日期：未设置 → 2026-12-01 · 下一步：未填写 → 联系企业 · 备注：企业来电确认 · 操作人：样例管理员"]
    same = client.patch(url, json={k: v for k, v in update.items() if k != "note"}).json()["item"]
    assert same["steps"] == row["steps"]
    cleared = client.patch(url, json={"owner": "", "due": "", "next": ""}).json()["item"]
    assert [cleared[k] for k in ("owner", "due", "next")] == ["", "", ""]
    assert cleared["steps"][-1] == [START.isoformat(),
        "负责人：办理员甲 → 未分派 · 截止日期：2026-12-01 → 未设置 · 下一步：联系企业 → 未填写 · 操作人：样例管理员"]


def test_company_detail_reuses_issue_content_without_exposing_private_fields(site):
    client, _ = site
    company = create_company(client)
    item = create_issue(client, company, owner="办理员甲", due="2026-12-01", next="准备材料")
    changed = client.patch(ISSUES + "/" + item["id"], json={"note": "企业确认办理计划"}).json()["item"]
    listing = client.get(ISSUES, params={"entId": company}).json()["items"]
    detail = client.get(APP + "/companies/" + company).json()["issues"]
    assert detail == listing == [{**changed, "entName": "演示企业"}]
    assert client.post("/api/auth/login", json={"user_id": "partner"}).is_success
    for response in [client.get(ISSUES), client.get(APP + "/companies/" + company)]:
        assert response.is_success, response.text
        for text in ("演示诉求详情", "办理员甲", "准备材料", "企业确认办理计划"):
            assert text not in response.text
    assert client.post(ISSUES, json={"entId": company, "title": "禁止创建", "owner": ""}).status_code == 403


def test_readonly_issue_projection_also_masks_legacy_records(site):
    client, _ = site
    company = create_company(client)
    legacy = {"entId": company, "status": "办理中", "title": "旧版诉求原文", "owner": "旧版经办人",
              "next": "旧版后续安排", "steps": [["2026-11-01", "旧版办理备注"]]}
    response = client.post("/api/v1/apps/enterprise/records", json={
        "project": "jkq", "type": "enterprise.issue", "data": {"item": legacy}})
    assert response.is_success, response.text
    assert client.post("/api/auth/login", json={"user_id": "partner"}).is_success
    listing = client.get(ISSUES)
    assert listing.is_success, listing.text
    assert all(text not in listing.text for text in ("旧版诉求原文", "旧版经办人", "旧版后续安排", "旧版办理备注"))
    assert client.get(ISSUES, params={"owner": "旧版经办人"}).json()["items"] == []

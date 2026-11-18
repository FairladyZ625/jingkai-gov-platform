"""按 demo-script.js 顺序验证 HTTP 动作；显示层走查由 #51 负责。"""

import re
import time
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

SCRIPT = Path(__file__).resolve().parents[2] / "prototype/v4/config/demo-script.js"
TITLES = re.findall(r"\{ title: '([^']+)', steps:", SCRIPT.read_text(encoding="utf-8"))
assert len(TITLES) == 12

# 只对尚未挂载的上游接口跳过。路由已接入时，业务错误直接使该段失败。
DEPENDENCIES = {
    "企业走访": {"/api/apps/enterprise/companies/{company_id}/visits": "#116 走访确认"},
    "公文协作": {"/api/apps/document/compare": "#111 版本比对",
                 "/api/apps/document/drafts/{identity}/submit": "#112 公文送审",
                 "/api/v1/operator/plan": "#126 操作员计划"},
    "技能中心": {"/api/v1/skills/draft": "#109 一句话起草",
                 "/api/v1/skills/{sid}/share": "#118 技能分享"},
}


def data(response):
    response.raise_for_status()
    return response.json()


def login(c, username, password):
    return data(c.post("/api/v1/auth/login", json={"username": username, "password": password}))


@pytest.mark.parametrize("title", TITLES, ids=TITLES)
def test_segment(server, title):
    url, password = server.url, server.password
    with httpx.Client(base_url=url, trust_env=False) as c:
        me = login(c, "wangmin", password)
        if title in DEPENDENCIES:
            paths = data(c.get("/openapi.json"))["paths"]
            missing = [reason for path, reason in DEPENDENCIES[title].items() if path not in paths]
            if missing:
                pytest.skip("等待上游接口：" + "、".join(missing))
        if title == "开场":
            assert me["role"]["id"] == "member"
            assert data(c.get("/api/v1/me"))["user"]["username"] == "wangmin"
        elif title == "政策兑现":
            chat = data(c.post("/api/v1/ai/chat", json={"messages": [
                {"role": "user", "content": "帮我查一下示例企业能申报哪些政策"},
            ]}))
            assert "预置结果" in chat["content"] and "规则意图优先" in chat["routeNote"]
            response = c.post("/api/apps/policy/match", json={"entId": "E001"})
            if response.status_code == 404 and "/api/apps/policy/match" not in data(c.get("/openapi.json"))["paths"]:
                pytest.skip("PR #127 挂载政策匹配路由")
            assert data(response)["results"]
        elif title == "企业走访":
            base = "/api/apps/enterprise"
            company = data(c.post(base + "/companies", json={"name": "走访演示企业", "employees": 4}))["item"]
            path = base + "/companies/" + company["id"]
            visit = data(c.post(path + "/visits", json={"notes": "职工现有5人。"}))
            assert data(c.get(path))["item"]["employees"] == 4
            proposal = next(p for p in visit["proposals"] if p["field"] == "employees")
            data(c.post(base + "/proposals/" + proposal["id"] + "/decision", json={"decision": "accept"}))
            assert data(c.get(path))["item"]["employees"] == 5
        elif title == "公文协作":
            plan = data(c.post("/api/v1/operator/plan", json={"text": "起草一份数据券申报延期通知"}))
            assert plan["intent"] and plan["steps"]
            base = "/api/apps/document"
            draft = data(c.post(base + "/drafts", json={"templateId": "T06", "inputs": {
                "orig": "公开演示申报通知", "oldEnd": "2026-11-20", "newEnd": "2026-11-25",
            }}))["item"]
            ref = draft["id"]
            path = base + "/drafts/" + ref
            content = dict(draft["versions"][-1]["content"], title="关于延长示例材料受理期限的通知")
            data(c.put(path, json={"content": content}))
            diff = data(c.post(base + "/compare", json={"a": {"id": ref, "v": 0}, "b": {"id": ref, "v": 1}}))
            assert diff["stats"]["add"] > 0
            review = data(c.post(path + "/submit", json={"assignee": "u-liyang"}))
            assert review["item"]["status"] == "审签中"
        elif title == "技能中心":
            base = "/api/v1/skills"
            draft = data(c.post(base + "/draft", json={"text": "核对数据券申报材料齐不齐"}))["draft"]
            skill = data(c.post(base, json={key: draft[key] for key in ("name", "spec", "summary")}))["item"]
            path = base + "/" + skill["id"]
            data(c.post(path + "/share", json={"scope": "people", "people": ["u-liyang"], "perm": "use"}))
            login(c, "liyang", password)
            assert data(c.get(path))["item"]["name"] == draft["name"]
        elif title == "会议纪要":
            base = "/api/apps/meeting/meetings"
            audio = SCRIPT.parents[3] / "apps/meeting/samples/demo.webm"
            with audio.open("rb") as stream:
                item = data(c.post(base, data={"title": "演示例会"},
                                   files={"file": ("演示录音.webm", stream, "audio/webm")}))["item"]
            path = base + "/" + item["id"]
            job = data(c.post(path + "/transcribe", json={}))["job"]
            deadline = time.monotonic() + 30
            while job["status"] != "done":
                assert job["status"] not in {"failed", "cancelled"} and time.monotonic() < deadline
                time.sleep(0.1)
                job = data(c.get("/api/v1/jobs/" + job["id"]))["job"]
            minutes = data(c.get(path))["minutes"]
            assert minutes["body"][0]["sources"]
            todo = minutes["todos"][0]["id"]
            data(c.patch(path, json={"todo": {"id": todo, "owner": "u-liyang", "due": "周五"}}))
            assert data(c.post(path + "/todos/commit", json={"ids": [todo]}))["committed"] == [todo]
        elif title == "知识库":
            hits = data(c.post("/api/v1/kb/search", json={"q": "算力券 封顶", "space": "policy"}))["hits"]
            assert hits
            assert data(c.get("/api/v1/kb/docs/" + hits[0]["id"]))["item"]["id"] == hits[0]["id"]
            missing = data(c.post("/api/v1/kb/ask", json={"q": "火星基地XYZ999"}))
            assert missing["notFound"] and not missing["citations"]
            answer = data(c.post("/api/v1/kb/ask", json={"q": "数据券补贴最高能拿多少？", "space": "policy"}))
            assert answer["citations"] and "最高100万元" in answer["answer"]
            imported = data(c.post("/api/v1/kb/import", json={
                "url": "https://example.invalid/demo-notice", "space": "policy",
            }))
            assert imported["chunks"] and imported["docs"][0]["source"]["url"].endswith("/demo-notice")
        elif title == "电脑操作":
            pytest.importorskip("playwright.async_api", reason="专用 HTTP job 安装 Chromium")
            runs = "/api/apps/computer/runs"
            run = data(c.post(runs, json={"task": "apply", "ent": "E001"}))["item"]
            url = runs + "/" + run["id"]
            for kind in ("otp", "submit"):
                deadline = time.monotonic() + 20
                while True:
                    state = data(c.get(url))["item"]
                    if state["status"] == "waiting" and state["pending"]["kind"] == kind:
                        break
                    assert state["status"] not in ("failed", "stopped", "done") and time.monotonic() < deadline
                    time.sleep(0.1)
                assert state["result"] is None
                data(c.post(url + "/confirm", json={"kind": kind, "decision": "approve" if kind == "otp" else "decline"}))
            assert data(c.get(url))["item"]["status"] == "stopped"
        elif title == "审签":
            record = data(c.post("/api/v1/apps/document/records", json={
                "project": "jkq", "type": "report", "data": {"title": "演示通知"},
            }))
            review = data(c.post("/api/v1/reviews", json={"appId": "document", "recordId": record["id"],
                          "version": 1, "assignee": "u-liyang"}))
            login(c, "liyang", password)
            assert review["id"] in [item["id"] for item in data(c.get("/api/v1/reviews"))["items"]]
            decided = data(c.post(f"/api/v1/reviews/{review['id']}/decisions",
                                  json={"version": 1, "decision": "approve"}))
            assert decided["item"]["status"] == "done"
        elif title == "外部协作者":
            path = "/api/apps/enterprise/companies"
            item = data(c.post(path, json={"name": "纸鹿二号智驾示例", "phone": "13900001111"}))["item"]
            assert item["phone"] == "139****1111"
            me = login(c, "hejun", password)
            assert me["grants"]["enterprise"] == ["view"]
            summary = data(c.get(path + "/" + item["id"]))["item"]
            assert summary["id"] == item["id"] and "phone" not in summary and "revenue" not in summary
        elif title == "管理后台":
            admin = login(c, "admin", password)
            assert "admin" in admin["grants"]["*"]
            assert any(user["username"] == "admin" for user in data(c.get("/api/v1/admin/users"))["items"])
            assert data(c.get("/api/v1/admin/grants"))["grants"]
            assert data(c.get("/api/v1/models"))["items"]
            assert data(c.get("/api/v1/audit"))["items"]
        elif title == "浅色主题":
            for theme in ("light", "dark"):
                data(c.patch("/api/v1/me/prefs", json={"theme": theme}))
                assert data(c.get("/api/v1/me"))["prefs"]["theme"] == theme
        else:
            pytest.fail(f"未登记演示段落 {title}")


def test_reset_checks_real_session_before_host(server):
    url, password = server.url, server.password
    path = "/api/v1/demo/reset"
    with httpx.Client(base_url=url, trust_env=False) as c:
        anonymous = c.post(path)
        assert (anonymous.status_code, anonymous.json()["error"]["code"]) == (401, "UNAUTHENTICATED")
        login(c, "hejun", password)
        denied = c.post(path)
        assert (denied.status_code, denied.json()["error"]["code"]) == (403, "FORBIDDEN")
        try:
            data(c.put("/api/v1/me/role", json={"role": "admin"}))
            denied = c.post(path)
            assert (denied.status_code, denied.json()["error"]["code"]) == (403, "FORBIDDEN")
        finally:
            data(c.put("/api/v1/me/role", json={"role": "partner"}))
        login(c, "admin", password)
        unavailable = c.post(path)
        assert unavailable.status_code == 503 and unavailable.json()["error"]["code"] == "RESET_UNAVAILABLE"

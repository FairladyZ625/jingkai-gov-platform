"""以临时清单挂载实际路由、core 记录服务和独立原值库。"""
import csv
import io
import json
import shutil
import sqlite3
from pathlib import Path
from time import perf_counter

import pytest

PREFIX = "/api/apps/enterprise"
COMPANIES = PREFIX + "/companies"


@pytest.fixture
def client(isolated_platform, make_client, tmp_path, monkeypatch):
    config, apps = isolated_platform
    directory = apps / "enterprise"
    shutil.copytree(Path(__file__).resolve().parents[1] / "api", directory / "api")
    manifest = json.loads((apps / "sample-app/app.json").read_text())
    manifest.update(id="enterprise", defaultRoles={"partner": ["view", "operate"]})
    (directory / "app.json").write_text(json.dumps(manifest))
    (directory / "api/router.py").write_text("from .ledger import router\n")
    (config / "projects.yaml").write_text(json.dumps({"companies": [
        {"id": "sample-company", "name": "样例", "projects": [{"id": "jkq", "name": "经开区"}]}]}))
    users = json.loads((config / "users.yaml").read_text())
    users["users"].append({"id": "partner", "name": "协作", "roles": ["partner"], "projects": ["jkq"]})
    (config / "users.yaml").write_text(json.dumps(users))
    monkeypatch.setenv("JKQ_ENTERPRISE_PRIVATE_DB", str(tmp_path.parent / (tmp_path.name + ".sqlite")))
    with make_client() as c:
        assert c.post("/api/auth/login", json={"user_id": "sampleadmin"}).is_success
        yield c


def create(c, **row):
    response = c.post(COMPANIES, json=row)
    assert response.is_success, response.text
    return response.json()["item"]


def test_filters_and_sorts(client):
    a = create(client, name="B示例", formerNames=["旧称"], tags=["重点"], industry="制造 · 汽车",
               servicer="甲", scale="中型", lastVisitDays=91, revenue={"value": 9})
    b = create(client, name="A示例", tags=["其它"], industry="软件", servicer="乙",
               scale="微型", lastVisitDays=1, revenue={"value": 20})
    for key, value in dict(q="旧称", tag="重点", industry="制造", servicer="甲", scale="中型", alert="1").items():
        result = client.get(COMPANIES, params={key: value}).json()
        assert result == {"items": [a], "total": 1,
                          "facets": {"tags": ["重点"], "industries": ["制造"], "servicers": ["甲"]}}
    for sort, expected in [("name", [b, a]), ("lastVisit", [a, b]), ("revenue", [b, a])]:
        assert client.get(COMPANIES, params={"sort": sort}).json()["items"] == expected


def test_revisions_and_projection(client, tmp_path):
    assert client.post(COMPANIES, json={"scale": "中型"}).status_code == 400
    a = create(client, name="演示一", phone="13900001111", revenue={"value": 12345})
    assert a["phone"] == "139****1111"
    duplicate = client.post(COMPANIES, json={"name": "演示一"})
    assert (duplicate.status_code, duplicate.json()["error"]["code"]) == (409, "DUPLICATE")
    missing = client.get(COMPANIES + "/absent")
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "NOT_FOUND")
    url = COMPANIES + "/" + a["id"]
    assert client.patch(url, json={"servicer": "甲"}).is_success
    assert client.patch(url, json={"servicer": "乙"}).is_success
    assert client.patch(url, json={"phone": "13900002222"}).is_success
    response = client.get(url).json()
    assert set(response) == {"item", "visits", "issues", "files", "proposals", "history"}
    history = response["history"]
    assert len(history) == 3
    assert (history[1]["field"], history[1]["old"], history[1]["new"]) == ("servicer", "甲", "乙")
    assert (history[0]["old"], history[0]["new"]) == ("139****1111", "139****2222")
    with sqlite3.connect(tmp_path.parent / (tmp_path.name + ".sqlite")) as conn:
        raw = json.loads(conn.execute("select body from snapshots order by rowid desc").fetchone()[0])
        assert raw["phone"] == "13900002222" and raw["revenue"]["value"] == 12345
    platform = client.app.state.platform
    versions = platform.store._db.execute("select document from v1_versions").fetchall()
    assert versions and all("1390000" not in r[0] and "12345" not in r[0] for r in versions)
    assert client.post("/api/auth/login", json={"user_id": "partner"}).is_success
    for method, path, body in [("patch", url, {"phone": "x"}), ("post", PREFIX + "/import", {"rows": []}),
                               ("post", COMPANIES, {"name": "越权"})]:
        denied = client.request(method, path, json=body)
        assert (denied.status_code, denied.json()["error"]["code"]) == (403, "FORBIDDEN")
    for path in [url, COMPANIES, PREFIX + "/export"]:
        res = client.get(path)
        assert res.is_success and "139****2222" in res.text and "1390000" not in res.text


def test_csv(client):
    fields = ["name", "industry", "products", "servicer"]
    row = ['演示,"甲"', "机器人", "第一行\n第二行", "甲"]
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerows([fields, row, ["", "错误", "", ""], ["B", "=1", "+2", "-3"], ["@C", "", "", ""]])
    result = client.post(PREFIX + "/import", json={"csv": buf.getvalue()}).json()
    assert result["added"] == 3 and result["errors"][0]["row"] == 4 and result["errors"][0]["reason"]
    exported = client.get(PREFIX + "/export").json()["csv"]
    by_name = {r["name"]: r for r in csv.DictReader(io.StringIO(exported, newline=""))}
    assert [by_name[row[0]][f] for f in fields] == row
    assert [by_name["B"][f] for f in fields[1:]] == ["'=1", "'+2", "'-3"]
    assert "'@C" in by_name
    selected = client.get(PREFIX + "/export", params={"ids": result["items"][0]["id"]}).json()["csv"]
    assert len(list(csv.DictReader(io.StringIO(selected)))) == 1


def test_bulk(client):
    start = perf_counter()
    result = client.post(PREFIX + "/import", json={"rows": [{"name": f"样例{i}"} for i in range(1000)]}).json()
    elapsed = perf_counter() - start
    assert result["added"] == 1000 and not result["errors"]
    print(f"1000 行 HTTP 导入耗时 {elapsed:.3f} 秒")
    assert elapsed < 10


def test_related_records_and_rename(client):
    a = create(client, name="档案甲")
    b = create(client, name="档案乙")
    url = COMPANIES + "/" + a["id"]
    assert client.patch(url, json={"name": b["name"]}).status_code == 409
    assert client.get(url).json()["history"] == []
    for kind, status, owner in [("issue", "办理中", a), ("visit", "", a), ("file", "", a),
                                ("proposal", "pending", a), ("proposal", "accepted", a),
                                ("visit", "", b)]:
        response = client.post("/api/v1/apps/enterprise/records", json={
            "project": "jkq", "type": "enterprise." + kind,
            "data": {"item": {"entId": owner["id"], "status": status}}})
        assert response.is_success, response.text
    result = client.get(url).json()
    for key in ("issues", "visits", "files", "proposals"):
        assert [row["entId"] for row in result[key]] == [a["id"]]
    assert result["proposals"][0]["status"] == "pending"


def test_simultaneous_duplicate(client):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(COMPANIES, json={"name": "同名样例"}), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert client.get(COMPANIES).json()["total"] == 1


def test_minimal_shape_and_nonfinite(client):
    item = create(client, name="最小档案")
    for row in (item, client.get(COMPANIES, params={"q": "最小档案"}).json()["items"][0],
                client.get(COMPANIES + "/" + item["id"]).json()["item"]):
        assert row["industry"] == "" and row["short"] == "" and row["employees"] == 0
        assert row["revenue"]["value"] == "" and row["servicer"] == ""
    payload = json.dumps({"name": "坏值", "fieldStatus": {"score": float("inf")}}, allow_nan=True)
    bad = client.post(COMPANIES, content=payload, headers={"Content-Type": "application/json"})
    assert bad.status_code == 400
    mixed = json.dumps({"rows": [
        {"name": "好行"},
        {"name": "坏行", "fieldStatus": {"score": float("nan")}},
        {"name": "又一行"},
    ]}, allow_nan=True)
    result = client.post(PREFIX + "/import", content=mixed, headers={"Content-Type": "application/json"}).json()
    assert result["added"] == 2 and result["errors"][0]["row"] == 2
    assert {row["name"] for row in client.get(COMPANIES).json()["items"]} >= {"好行", "又一行", "最小档案"}


def test_csv_unclosed_quotes_rejected(client):
    before = client.get(COMPANIES).json()["total"]
    text = "name,industry\n合法企业,制造\n\"未闭合,软件\n后续合法,制造\n"
    response = client.post(PREFIX + "/import", json={"csv": text})
    assert response.status_code == 400
    body = response.json()["error"]
    assert body["code"] == "INVALID_REQUEST" and "边界" in body["message"]
    assert client.get(COMPANIES).json()["total"] == before


def test_partner_revenue_order_and_denial_audit(client):
    create(client, name="低营收", revenue={"value": 1})
    create(client, name="高营收", revenue={"value": 999})
    def names(user):
        return [row["name"] for row in client.get(COMPANIES, params={"sort": "revenue"}).json()["items"]
                if row["name"] in {"低营收", "高营收"}]
    assert names("admin") == ["高营收", "低营收"]
    assert client.post("/api/auth/login", json={"user_id": "partner"}).is_success
    assert names("partner") == ["低营收", "高营收"]
    denied = client.post(COMPANIES, json={"name": "越权"})
    assert denied.status_code == 403
    assert denied.json()["error"]["details"] == {"app": "enterprise", "need": "operate"}
    assert client.post("/api/auth/login", json={"user_id": "sampleadmin"}).is_success
    audit = client.get("/api/audit", params={"app_id": "enterprise"}).json()["items"]
    assert any(entry["action"] == "enterprise.denied" and entry.get("user") == "partner" for entry in audit)

"""正常流程：保存 → 提交 → 确认 → 导出，并断言留痕。"""
import csv
import io

import pytest

PROJECT = "sample-project"
APP = "__APP_ID__".strip("_").lower().replace("_", "-")
BASE = f"/api/apps/{APP}"


def _create(client, title="示例记录", content="示例内容"):
    r = client.post(f"{BASE}/records", json={"project": PROJECT, "title": title, "content": content})
    assert r.status_code == 201
    return r.json()


@pytest.mark.parametrize(("title", "content", "csv_title", "csv_content"), [
    ("示例记录", '第一行, "两处引号"\r第二行\n第三行', "示例记录", '第一行, "两处引号"\r第二行\n第三行'),
    ("=1+1", " \t＋1", "'=1+1", "' \t＋1"),
    ("\t用制表符开头", "@备注", "'\t用制表符开头", "'@备注"),
])
def test_sampleoperator_saves_and_lead_confirms_then_exports(client_for, title, content, csv_title, csv_content):
    sampleoperator = client_for(APP, user="sampleoperator")
    record = _create(sampleoperator, title, content)
    assert (record["status"], record["version"]) == ("draft", 1)
    assert record["data"] == {"title": title, "content": content}

    review = sampleoperator.post(f"{BASE}/records/{record['id']}/submit", json={})
    assert review.status_code == 201
    assert review.json()["status"] == "pending"

    lead = client_for(APP, user="samplereviewer")
    todo = lead.get(f"{BASE}/reviews").json()["todo"]
    assert [r["id"] for r in todo] == [review.json()["id"]]
    done = lead.post(
        f"{BASE}/reviews/{review.json()['id']}/decisions",
        json={"version": 1, "decision": "confirm"},
    )
    assert done.status_code == 200
    assert done.json()["status"] == "confirmed"

    exported = lead.get(f"{BASE}/records/{record['id']}/export")
    assert exported.status_code == 200
    rows = dict(csv.reader(io.StringIO(exported.content.decode("utf-8-sig"), newline="")))
    assert rows["标题"] == csv_title and rows["内容"] == csv_content
    assert rows["确认人"] == "samplereviewer"

    admin = client_for(APP, user="sampleadmin")
    actions = [i["action"] for i in admin.get(f"/api/audit?app_id={APP}").json()["items"]]
    assert {"create", "submit", "confirm", "export"} <= set(actions)


def test_unconfirmed_record_cannot_be_exported(client_for):
    sampleoperator = client_for(APP, user="sampleoperator")
    record = _create(sampleoperator, title="还没确认的记录")
    denied = sampleoperator.get(f"{BASE}/records/{record['id']}/export")
    assert denied.status_code == 409
    assert denied.json()["error"] == {
        "code": "invalid_state",
        "message": "记录确认后才能导出",
        "retryable": False,
    }

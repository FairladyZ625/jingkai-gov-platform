"""输入错误：空标题 422；用过期 baseVersion 保存返回 409 version_conflict。"""
PROJECT = "sample-project"
APP = "__APP_ID__".strip("_").lower().replace("_", "-")
BASE = f"/api/apps/{APP}"


def test_empty_title_is_rejected(client_for):
    client = client_for(APP, user="sampleoperator")
    bad = client.post(f"{BASE}/records", json={"project": PROJECT, "title": ""})
    assert bad.status_code == 422


def test_stale_base_version_is_rejected(client_for):
    client = client_for(APP, user="sampleoperator")
    record = client.post(
        f"{BASE}/records", json={"project": PROJECT, "title": "第一版", "content": "示例"}
    ).json()
    first = client.put(
        f"{BASE}/records/{record['id']}", json={"baseVersion": 1, "title": "第二版"}
    )
    assert first.status_code == 200
    assert first.json()["version"] == 2

    stale = client.put(
        f"{BASE}/records/{record['id']}", json={"baseVersion": 1, "title": "又改一次"}
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
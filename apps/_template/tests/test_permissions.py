"""无权限：观察员只有 view，写接口必须 403，且数据没变。"""
PROJECT = "sample-project"
APP = "__APP_ID__".strip("_").lower().replace("_", "-")
BASE = f"/api/apps/{APP}"


def test_sampleobserver_cannot_create_and_data_is_unchanged(client_for):
    sampleobserver = client_for(APP, user="sampleobserver")
    denied = sampleobserver.post(f"{BASE}/records", json={"project": PROJECT, "title": "观察员不能写"})
    assert denied.status_code == 403
    assert denied.json()["action"] == "operate"

    sampleoperator = client_for(APP, user="sampleoperator")
    assert sampleoperator.get(f"{BASE}/records?project={PROJECT}").json()["items"] == []
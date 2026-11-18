import json
import shutil
from pathlib import Path

import httpx
import pytest

from conftest import ROOT

SAMPLE = "虚构的测试记录".encode()
BASE = "/api/apps/sample-app"


def login(c, uid):
    assert c.post("/api/auth/login", json={"user_id": uid}).status_code == 200


def test_requires_login(make_client):
    c = make_client()
    assert c.get("/api/apps").status_code == 401
    assert c.get(f"{BASE}/records").status_code == 401


def test_catalog_filtered_by_role(make_client):
    c = make_client()
    login(c, "sampleoutsider")
    assert [a["id"] for a in c.get("/api/apps").json()["apps"]] == []
    assert c.get(f"{BASE}/records").status_code == 403
    login(c, "sampleobserver")
    apps = c.get("/api/apps").json()["apps"]
    assert [a["actions"] for a in apps if a["id"] == "sample-app"] == [["view"]]


def test_sampleobserver_cannot_operate(make_client):
    c = make_client()
    login(c, "sampleobserver")
    r = c.post(f"{BASE}/records", files={"file": ("x.txt", SAMPLE)})
    assert r.status_code == 403 and r.json()["action"] == "operate"


def test_broken_app_is_isolated(make_client, tmp_path):
    apps = tmp_path / "apps"
    shutil.copytree(ROOT / "tests/fixtures/platform-app", apps / "sample-app")
    bad = apps / "bad-app"
    shutil.copytree(ROOT / "apps/_template", bad)
    m = json.loads((bad / "app.json").read_text(encoding="utf-8"))
    m.update(id="bad-app", name="坏应用", owner="t", defaultRoles={"sampleoperator": ["view"]})
    (bad / "app.json").write_text(json.dumps(m), encoding="utf-8")
    (bad / "api/router.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    (apps / "no-manifest").mkdir()
    c = make_client(apps)
    h = c.get("/api/health").json()
    assert h["unavailable"] == ["bad-app"] and h["broken"] == 1
    login(c, "sampleoperator")
    listed = {a["id"]: a["available"] for a in c.get("/api/apps").json()["apps"]}
    assert listed == {"sample-app": True, "bad-app": False}
    assert c.get(f"{BASE}/records").status_code == 200


def test_sdk_and_app_static_assets_are_served(make_client):
    c = make_client()
    assert c.get("/").status_code == 404
    assert "createContext" in c.get("/sdk/haiknow.js").text
    assert "mount" in c.get("/apps/sample-app/web/index.js").text


def test_model_usage_is_admin_only_and_keeps_totals(make_client):
    c = make_client()
    assert c.get("/api/model/usage").status_code == 401
    login(c, "sampleoperator")
    assert c.get("/api/model/usage").status_code == 403
    rec = c.post(f"{BASE}/records", files={"file": ("记录.txt", SAMPLE)}).json()
    recognized = c.post(f"{BASE}/records/{rec['id']}/recognize")
    assert recognized.status_code == 200
    assert recognized.json()["summary"].startswith("[模拟模型]")
    login(c, "sampleadmin")
    usage = c.get("/api/model/usage").json()
    assert usage == {
        "mode": "mock", "calls": {"sample-app": 1}, "scope": "process",
        "usage": {"sample-app": {"total": 1, "success": 1, "failure": 0, "mock": 1}},
    }
    restarted = make_client()
    login(restarted, "sampleadmin")
    assert restarted.get("/api/model/usage").json()["usage"] == {}


@pytest.mark.parametrize("failure,kind,status", [
    ("timeout", "timeout", 504), (401, "http", 502),
    ("bad_response", "bad_response", 502), ("partial", "not_configured", 503),
])
def test_model_errors_surface_as_chinese_http_errors(make_client, monkeypatch, failure, kind, status):
    from haiknow_core import model as model_module

    monkeypatch.setenv("HAIKNOW_MODEL_BASE_URL", "http://ark.test/api/v3")
    if failure != "partial":
        monkeypatch.setenv("HAIKNOW_MODEL_API_KEY", "test-key")
        monkeypatch.setenv("HAIKNOW_MODEL_NAME", "test-model")
    requests = []
    def respond(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private-provider-body", request=request)
        if failure == "bad_response":
            return httpx.Response(200, text="private-provider-body test-key")
        return httpx.Response(401, text="private-provider-body test-key")
    original = httpx.AsyncClient
    monkeypatch.setattr(model_module.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    c = make_client()
    login(c, "sampleoperator")
    rec = c.post(f"{BASE}/records", files={"file": ("记录.txt", SAMPLE)}).json()
    r = c.post(f"{BASE}/records/{rec['id']}/recognize")
    assert r.status_code == status and r.json()["kind"] == kind
    assert "模型" in r.json()["detail"]
    assert "test-key" not in r.text and "private-provider-body" not in r.text
    assert len(requests) == (0 if failure == "partial" else 2 if failure == "timeout" else 1)
    assert c.get(f"{BASE}/records/{rec['id']}").json()["status"] == "uploaded"
    login(c, "sampleadmin")
    assert c.get("/api/model/usage").json()["usage"]["sample-app"] == {"total": 1, "success": 0, "failure": 1, "mock": 0}


def test_demo_uses_configured_model_result(make_client, monkeypatch):
    monkeypatch.setenv("HAIKNOW_MODEL_BASE_URL", "http://ark.test/api/v3")
    monkeypatch.setenv("HAIKNOW_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("HAIKNOW_MODEL_NAME", "test-model")
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": "桩模型：示例记录摘要。"}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    c = make_client()
    login(c, "sampleoperator")
    rec = c.post(f"{BASE}/records", files={"file": ("记录.txt", SAMPLE)}).json()
    r = c.post(f"{BASE}/records/{rec['id']}/recognize")
    assert r.status_code == 200
    assert r.json()["summary"] == "桩模型：示例记录摘要。"
    assert len(requests) == 1 and requests[0]["model"] == "test-model"
    login(c, "sampleadmin")
    assert c.get("/api/model/usage").json()["usage"]["sample-app"] == {"total": 1, "success": 1, "failure": 0, "mock": 0}


def test_context_model_reads_its_uploaded_image(make_client, monkeypatch, tmp_path):
    from test_model import PNG

    apps = tmp_path / "apps"
    shutil.copytree(ROOT / "tests/fixtures/platform-app", apps / "sample-app")
    router = apps / "sample-app/api/router.py"
    with router.open("a", encoding="utf-8") as f:
        f.write('''
@router.post("/model-image")
def model_image(file_id: str, ctx: AppContext = Depends(require("operate"))):
    return {"answer": ctx.model.chat([{"role": "user", "content": "识别图片"}], images=[file_id], model="vision-model")}
''')
    monkeypatch.setenv("HAIKNOW_MODEL_BASE_URL", "http://ark.test/api/v3")
    monkeypatch.setenv("HAIKNOW_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("HAIKNOW_MODEL_NAME", "test-model")
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "图片模型结果"}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    c = make_client(apps)
    login(c, "sampleoperator")
    rec = c.post(f"{BASE}/records", files={"file": ("photo.png", PNG)}).json()
    r = c.post(f"{BASE}/model-image", params={"file_id": rec["file"]})
    assert r.status_code == 200 and r.json() == {"answer": "图片模型结果"}
    assert requests[0]["model"] == "vision-model"
    parts = requests[0]["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "识别图片"}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_new_app_script(tmp_path):
    import subprocess
    import sys

    root = tmp_path / "repo"
    shutil.copytree(ROOT / "apps/_template", root / "apps/_template")
    shutil.copytree(ROOT / "scripts", root / "scripts")
    p = subprocess.run(
        [sys.executable, str(root / "scripts/new_app.py"), "notes-helper", "记录助手", "--owner", "tester", "--issue", "12"],
        capture_output=True, text=True,
    )
    assert p.returncode == 0, p.stderr
    m = json.loads((root / "apps/notes-helper/app.json").read_text(encoding="utf-8"))
    assert m["id"] == "notes-helper" and m["owner"] == "tester"
    assert "#12" in (root / "apps/notes-helper/README.md").read_text(encoding="utf-8")
    assert not Path(root / "apps/notes-helper/api/router.py").read_text(encoding="utf-8").count("__APP")

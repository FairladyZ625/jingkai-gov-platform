"""通过卫华真实路由和临时 SQLite 验证经开区实例契约。"""

import os
import sqlite3
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from shutil import copyfile

import pytest

# 仓库检查仅装 pytest。安装平台依赖的 Core 检查会执行这组集成用例。
pytest.importorskip("fastapi", reason="经开区集成测试需要 requirements-dev.txt")

from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient

from jkq import routers
from jkq.app import create_app
from jkq.settings import REPO_ROOT, core_environment


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    for name in ("HAIKNOW_ROOT", "HAIKNOW_CONFIG_DIR", "HAIKNOW_APPS_DIR", "JKQ_WEB_DIR"):
        monkeypatch.delenv(name, raising=False)
    for name in tuple(os.environ):
        if name.startswith(("HAIKNOW_MODEL_", "HAIKNOW_PROVIDER_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HAIKNOW_SECRET", "jkq-test-session-signing")
    monkeypatch.setenv("HAIKNOW_DEMO_LOGIN", "0")
    directory = tmp_path / "database"
    monkeypatch.setenv("HAIKNOW_DATA_DIR", str(directory))
    return directory


def seed_environment(data_dir):
    return {
        "PYTHON": sys.executable,
        "HAIKNOW_DATA_DIR": str(data_dir),
        "HAIKNOW_DEMO_LOGIN": "0",
        "HAIKNOW_SECRET": os.environ["HAIKNOW_SECRET"],
    }


@pytest.fixture
def client(data_dir, cheap_password_hash):
    with TestClient(create_app()) as client:
        yield client


def create_admin(client):
    credentials = {"username": "test-admin", "password": "demo-password"}
    response = client.post("/api/auth/bootstrap", json={**credentials, "name": "测试管理员"})
    assert response.status_code == 200
    return credentials


def assert_error(response, status, code):
    assert response.status_code == status
    assert set(response.json()) == {"error"}
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert error["message"]
    assert isinstance(error["details"], dict)


def test_auth_mapping_preserves_cookie_and_session(client):
    credentials = create_admin(client)
    client.cookies.clear()
    login = client.post("/api/v1/auth/login", json=credentials)
    assert login.status_code == 200
    assert login.json()["user"]["username"] == "test-admin"
    assert "set-cookie" in login.headers
    assert client.get("/api/v1/auth/session").json()["user"]["username"] == "test-admin"
    me = client.get("/api/v1/me").json()
    assert me["role"]["id"] == "admin"
    assert "admin" in me["grants"]["*"]
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/auth/session").json() == {"user": None}


def test_admin_mapping_preserves_query_and_reaches_core(client):
    create_admin(client)
    params = {"q": "测试管理员"}
    users = client.get("/api/v1/admin/users", params=params)
    assert users.status_code == 200
    assert {"items", "roles", "departments"} <= set(users.json())
    assert [user["username"] for user in users.json()["items"]] == ["test-admin"]
    assert client.get("/api/v1/admin/users", params={"q": "无匹配"}).json()["items"] == []


def test_kb_mapping_reaches_core(client):
    create_admin(client)
    categories = client.get("/api/v1/kb/categories")
    assert categories.status_code == 200
    assert categories.json() == client.get("/api/v1/knowledge/categories").json()
    assert categories.json()["items"]


def test_wrong_password_is_bad_credentials(client):
    credentials = create_admin(client)
    client.cookies.clear()
    response = client.post("/api/v1/auth/login", json={**credentials, "password": "wrong"})
    assert_error(response, 401, "BAD_CREDENTIALS")
    assert "set-cookie" not in response.headers


def test_missing_session_is_unauthenticated(client):
    assert_error(client.get("/api/v1/admin/users"), 401, "UNAUTHENTICATED")


def test_missing_permission_is_forbidden(client):
    create_admin(client)
    credentials = {"username": "test-member", "password": "demo-password"}
    assert client.post("/api/admin/users", json={**credentials, "name": "测试成员"}).status_code == 201
    client.cookies.clear()
    assert client.post("/api/v1/auth/login", json=credentials).status_code == 200
    assert_error(client.get("/api/v1/admin/users"), 403, "FORBIDDEN")


def test_missing_resource_is_not_found(client):
    create_admin(client)
    assert_error(client.get("/api/v1/kb/entries/missing"), 404, "NOT_FOUND")


@pytest.mark.parametrize("path", ["/api/v1/xxx", "/api/v1/auth/missing", "/api/v1/kb-extra/categories"])
def test_unmapped_routes_use_error_envelope(client, path):
    assert_error(client.get(path), 404, "NOT_FOUND")


@pytest.mark.parametrize(("method", "path"), [
    ("POST", "/api/v1/admin/departments"),
    ("DELETE", "/api/v1/admin/departments/example"),
])
def test_admin_department_routes_require_login(client, method, path):
    response = client.request(method, path)
    assert_error(response, 401, "UNAUTHENTICATED")


def test_wrong_method_preserves_allow_header(client):
    response = client.post("/api/v1/kb/categories")
    assert_error(response, 405, "METHOD_NOT_ALLOWED")
    assert "GET" in response.headers["allow"]


def test_canonical_redirect_preserves_alias_and_query(client):
    response = client.get("/api/v1/auth/state/?source=jkq", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "http://testserver/api/v1/auth/state?source=jkq"


def test_native_and_aliased_methods_coexist(client):
    create_admin(client)
    body = {"enabled": True}
    assert client.put("/api/admin/apps/missing", json=body).status_code == 405
    response = client.put("/api/v1/admin/apps/missing", json=body)
    assert_error(response, 404, "NOT_FOUND")
    assert client.patch("/api/admin/apps/missing", json={}).status_code == 404
    assert_error(client.patch("/api/v1/admin/apps/missing", json={}), 404, "NOT_FOUND")


def test_native_admin_route_preserves_redirect_and_allow_header(client):
    path = "/api/v1/admin/ai/providers"
    response = client.get(f"{path}/?source=jkq", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == f"http://testserver{path}?source=jkq"
    response = client.post(path)
    assert_error(response, 405, "METHOD_NOT_ALLOWED")
    assert response.headers["allow"] == "GET"


def test_instance_router_registration_precedes_alias(data_dir, monkeypatch):
    router = APIRouter(prefix="/api/v1/auth")

    @router.get("/state")
    def state():
        return {"source": "jkq"}

    @router.get("/session")
    def session():
        return {"user": None}

    monkeypatch.setattr(routers, "ROUTERS", (router,))
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/auth/state").json() == {"source": "jkq"}
        assert client.get("/api/auth/state").json() == {"demoLogin": False, "needsBootstrap": True}
        response = client.get("/api/v1/auth/state/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "http://testserver/api/v1/auth/state"
        response = client.post("/api/v1/auth/state")
        assert_error(response, 405, "METHOD_NOT_ALLOWED")
        assert response.headers["allow"] == "GET"
        assert client.get("/api/v1/auth/session").json() == {"user": None}


def test_registered_route_preserves_http_error_status_details_and_headers(data_dir, monkeypatch):
    router = APIRouter(prefix="/api/v1")

    @router.post("/conflict")
    def conflict():
        raise HTTPException(409, "当前版本已变更", headers={"Retry-After": "2"})

    @router.get("/unavailable")
    def unavailable():
        raise HTTPException(503, "测试内部诊断", headers={"Retry-After": "60"})

    monkeypatch.setattr(routers, "ROUTERS", (router,))
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/conflict")
        assert_error(response, 409, "INVALID_REQUEST")
        assert response.json()["error"]["message"] == "当前版本已变更"
        assert response.headers["retry-after"] == "2"
        response = client.get("/api/v1/unavailable")
        assert_error(response, 503, "INTERNAL_ERROR")
        assert "测试内部诊断" not in response.text
        assert response.headers["retry-after"] == "60"


class PageAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" and "src" in attributes:
            self.urls.append(attributes["src"])
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.urls.append(attributes["href"])


def test_health_and_prototype_assets(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    home = client.get("/")
    assert home.status_code == 200
    assert "经开区共享智能体工作站" in home.text
    assets = PageAssets()
    assets.feed(home.text)
    assert "config/app.config.js" in assets.urls
    for path in assets.urls:
        assert client.get(f"/{path}").status_code == 200, path
    assert "mode: 'mock'" in client.get("/config/app.config.js").text
    assert client.get("/favicon.ico").status_code in (200, 204)


@pytest.mark.parametrize("configured", [False, True])
def test_web_directory_selection(data_dir, tmp_path, monkeypatch, configured):
    root = tmp_path / "instance"
    root.mkdir()
    (root / "config").mkdir()
    for name in ("projects.yaml", "roles.yaml"):
        copyfile(REPO_ROOT / "config" / name, root / "config" / name)
    monkeypatch.setenv("HAIKNOW_ROOT", str(root))
    (root / "web").mkdir()
    (root / "web/index.html").write_text("web 优先", encoding="utf-8")
    override = root / "custom"
    override.mkdir()
    (override / "index.html").write_text("自定义目录", encoding="utf-8")
    if configured:
        monkeypatch.setenv("JKQ_WEB_DIR", "custom")
    with TestClient(create_app()) as client:
        assert client.get("/").text == ("自定义目录" if configured else "web 优先")


def test_missing_required_environment_fails_before_creating_database(data_dir, monkeypatch):
    monkeypatch.delenv("HAIKNOW_SECRET")
    with pytest.raises(RuntimeError, match="缺少必需环境变量 HAIKNOW_SECRET"):
        create_app()
    assert not data_dir.exists()


def test_v1_internal_error_has_standard_envelope(data_dir, monkeypatch):
    router = APIRouter(prefix="/api/v1")

    @router.get("/broken")
    def broken():
        raise RuntimeError("测试后端内部异常")

    monkeypatch.setattr(routers, "ROUTERS", (router,))
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.get("/api/v1/broken")
        assert_error(response, 500, "INTERNAL_ERROR")
        assert "测试后端内部异常" not in response.text


def test_make_seed_is_idempotent(data_dir):
    env = seed_environment(data_dir)
    snapshots = []
    for _ in range(2):
        result = subprocess.run(["make", "--no-print-directory", "seed"], cwd=REPO_ROOT,
                                env=env, capture_output=True, text=True, check=True)
        with sqlite3.connect(data_dir / "platform.db") as db:
            projects = db.execute("select id from projects order by id").fetchall()
            snapshots.append((result.stdout, list(db.iterdump())))
    assert snapshots[0] == snapshots[1]
    assert projects == [("jkq",)]


@pytest.mark.parametrize("config", [
    "companies: [",
    "companies: {id: jingkai}",
    "companies: [{id: jingkai, name: 经开区, projects: [{id: other, name: 演示}]}]",
    "companies: [{id: jingkai, name: 经开区, projects: [{id: jkq}]}]",
])
def test_invalid_project_config_fails_before_opening_database(data_dir, tmp_path, monkeypatch, config):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "projects.yaml").write_text(config, encoding="utf-8")
    monkeypatch.setenv("HAIKNOW_CONFIG_DIR", str(config_dir))
    with pytest.raises(RuntimeError, match=r"HAIKNOW_CONFIG_DIR.*projects\.yaml"):
        create_app()
    assert not data_dir.exists()


def test_seed_can_retry_same_data_dir_after_missing_project_config(data_dir, tmp_path):
    env = {**seed_environment(data_dir), "HAIKNOW_CONFIG_DIR": str(tmp_path / "missing")}
    command = ["make", "--no-print-directory", "seed"]
    failed = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    assert failed.returncode != 0
    assert "HAIKNOW_CONFIG_DIR" in failed.stderr
    assert "projects.yaml" in failed.stderr
    assert not data_dir.exists()
    env["HAIKNOW_CONFIG_DIR"] = str(REPO_ROOT / "config")
    recovered = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)
    assert "实例项目已初始化：jkq" in recovered.stdout
    with sqlite3.connect(data_dir / "platform.db") as db:
        assert db.execute("select id from projects").fetchall() == [("jkq",)]


def test_seed_repairs_existing_empty_project_library_without_replacing_data(data_dir, tmp_path, monkeypatch):
    with monkeypatch.context() as legacy:
        legacy.setenv("HAIKNOW_CONFIG_DIR", str(tmp_path / "missing"))
        with core_environment(REPO_ROOT):
            from haiknow_core.main import create_app as create_core_app

            old_store = create_core_app(REPO_ROOT).state.platform.store
            try:
                old_store.kv_put("test-app", "existing", {"kept": True})
            finally:
                old_store._db.close()
    with sqlite3.connect(data_dir / "platform.db") as db:
        assert db.execute("select id from projects").fetchall() == []
        assert db.execute("select value from settings where key='identity.seeded'").fetchone() == ("true",)

    env = seed_environment(data_dir)
    command = ["make", "--no-print-directory", "seed"]
    subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)
    with sqlite3.connect(data_dir / "platform.db") as db:
        assert db.execute("select id, company_id from projects").fetchall() == [("jkq", "jingkai")]
        assert db.execute("select id from companies where id='company'").fetchone() is None
        assert db.execute("select id, name from companies order by rowid limit 1").fetchone()[0] == "jingkai"
        assert db.execute("select value from kv where app_id='test-app'").fetchone() == ('{"kept": true}',)
        snapshot = list(db.iterdump())
    subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)
    with sqlite3.connect(data_dir / "platform.db") as db:
        assert list(db.iterdump()) == snapshot


def test_model_catalog_and_default_on_instance(client):
    create_admin(client)
    catalog = client.get("/api/v1/models").json()
    assert set(catalog) == {"items", "current", "capabilities"}
    assert catalog["current"] == "auto"
    items = {item["id"]: item for item in catalog["items"]}
    assert items["mock"]["enabled"] is True
    assert items["overseas"]["enabled"] is False
    chat = client.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "公开演练消息"}]})
    assert chat.status_code == 200
    assert chat.json()["mock"] is True
    assert client.put("/api/v1/models/current", json={"model": "mock"}).json() == {"current": "mock"}
    profile = client.get("/api/v1/me").json()
    assert profile["isAdmin"] is True
    assert profile["defaultModel"] == "mock"
    assert profile["settings"]["defaultModel"] == "mock"

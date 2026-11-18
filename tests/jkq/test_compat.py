"""通过卫华真实路由和临时 SQLite 验证经开区实例契约。"""

import os
import sqlite3
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

# 仓库检查仅装 pytest。安装平台依赖的 Core 检查会执行这组集成用例。
pytest.importorskip("fastapi", reason="经开区集成测试需要 requirements-dev.txt")

from fastapi import APIRouter
from fastapi.testclient import TestClient

from jkq import routers
from jkq.app import create_app
from jkq.settings import REPO_ROOT


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    for name in ("HAIKNOW_ROOT", "HAIKNOW_CONFIG_DIR", "HAIKNOW_APPS_DIR", "JKQ_WEB_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HAIKNOW_SECRET", "jkq-test-session-signing")
    monkeypatch.setenv("HAIKNOW_DEMO_LOGIN", "0")
    directory = tmp_path / "database"
    monkeypatch.setenv("HAIKNOW_DATA_DIR", str(directory))
    return directory


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
    assert login.json() == {"ok": True}
    assert "set-cookie" in login.headers
    assert client.get("/api/v1/me").json()["isAdmin"] is True
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/v1/me").status_code == 401


def test_admin_mapping_preserves_query_and_reaches_core(client):
    create_admin(client)
    params = {"q": "测试管理员"}
    users = client.get("/api/v1/admin/users", params=params)
    assert users.status_code == 200
    assert users.json() == client.get("/api/admin/users", params=params).json()
    assert [user["username"] for user in users.json()["users"]] == ["test-admin"]
    assert client.get("/api/v1/admin/users", params={"q": "无匹配"}).json() == {"users": []}


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


def test_wrong_method_preserves_allow_header(client):
    response = client.post("/api/v1/kb/categories")
    assert_error(response, 405, "METHOD_NOT_ALLOWED")
    assert "GET" in response.headers["allow"]


def test_canonical_redirect_preserves_alias_and_query(client):
    response = client.get("/api/v1/auth/state/?source=jkq", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "http://testserver/api/v1/auth/state?source=jkq"


def test_native_routes_take_precedence_by_method(client):
    create_admin(client)
    body = {"enabled": True}
    assert client.put("/api/admin/apps/missing", json=body).status_code == 405
    response = client.put("/api/v1/admin/apps/missing", json=body)
    assert_error(response, 404, "NOT_FOUND")


def test_instance_router_registration_precedes_alias(data_dir, monkeypatch):
    router = APIRouter(prefix="/api/v1/auth")

    @router.get("/state")
    def state():
        return {"source": "jkq"}

    monkeypatch.setattr(routers, "ROUTERS", (router,))
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/auth/state").json() == {"source": "jkq"}
        assert client.get("/api/auth/state").json() == {"demoLogin": False, "needsBootstrap": True}


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
    env = {**os.environ, "PYTHON": sys.executable}
    snapshots = []
    for _ in range(2):
        result = subprocess.run(["make", "--no-print-directory", "seed"], cwd=REPO_ROOT,
                                env=env, capture_output=True, text=True, check=True)
        with sqlite3.connect(data_dir / "platform.db") as db:
            projects = db.execute("select id from projects order by id").fetchall()
            snapshots.append((result.stdout, list(db.iterdump())))
    assert snapshots[0] == snapshots[1]
    assert projects == [("jkq",)]

"""仓库级 pytest 夹具：平台测试和各应用的 tests/ 共用。"""
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import MutableMapping
from importlib.util import find_spec
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
PLATFORM_APP = ROOT / "tests/fixtures/platform-app"
# importlib 模式需要显式加入平台模块、公共测试辅助和仓库脚本的导入路径。
sys.path[:0] = [str(ROOT), str(ROOT / "core/server"), str(ROOT / "core/sdk"), str(ROOT / "core/tests")]
os.environ["HAIKNOW_NO_AUTOAPP"] = "1"
# 测试默认不导入 CAP-04 开发种子，需要样本的用例自行打开 HAIKNOW_KB_SEED=1。
os.environ.setdefault("HAIKNOW_KB_SEED", "0")


def pytest_configure(config):
    # 仓库 CI 只安装 pytest。显式指定 core 或 apps 时，缺依赖仍由收集报错。
    if config.args_source is pytest.Config.ArgsSource.TESTPATHS and find_spec("fastapi") is None:
        config.option.ignore = [*(config.option.ignore or []), "core/tests", "apps"]


# 直接 pytest 也要能跑：本机开着代理时，测试内起的回环 HTTP/WS 服务不该走代理。
LOOPBACK_NO_PROXY = ("127.0.0.1", "localhost", "::1")


def ensure_loopback_no_proxy(env: MutableMapping[str, str]) -> MutableMapping[str, str]:
    """把回环地址追加进 NO_PROXY 与 no_proxy，保留用户已有值；已含 * 时不再追加。"""
    for key in ("NO_PROXY", "no_proxy"):
        entries = [e for e in re.split(r"[,\s]+", env.get(key, "")) if e]
        if "*" in entries:
            continue
        entries.extend(host for host in LOOPBACK_NO_PROXY if host not in entries)
        env[key] = ",".join(entries)
    return env


ensure_loopback_no_proxy(os.environ)


def set_provider_credential(monkeypatch, ident, base_url, value="test-placeholder-key"):
    prefix = "HAIKNOW_PROVIDER_" + ident.upper().replace("-", "_")
    monkeypatch.setenv(prefix + "_BASE_URL", base_url)
    monkeypatch.setenv(prefix + "_API_KEY", value)


_ROUTERS: dict = {}


@pytest.fixture
def reuse_loaded_routers(monkeypatch):
    """每次 create_app 都要重新 exec 全部应用的 api/*.py（定义 pydantic 模型、解析依赖），约占 create_app 三分之一。
    同一个 api 目录且其中 .py 的 mtime、大小都没变时，复用上次加载出的 router 与模块；
    造应用热加载、稳定性用例改写代码会改变指纹，自然走真实加载。加载失败不缓存，错误照常抛出。"""
    from haiknow_core import main

    real = main._load_router

    def load(entry):
        api = entry.dir / "api"
        stamp = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(api.glob("*.py"))) if api.is_dir() else ()
        key = (str(api), stamp)
        hit = _ROUTERS.get(key)
        if hit is None:
            router = real(entry)
            if router is not None:
                pkg_name = "haiknow_apps." + entry.manifest["id"].replace("-", "_")
                hit = _ROUTERS[key] = (router, {n: m for n, m in sys.modules.items() if n.startswith(pkg_name)})
            return router
        sys.modules.update(hit[1])
        return hit[0]

    monkeypatch.setattr(main, "_load_router", load)


@pytest.fixture
def cheap_password_hash(monkeypatch):
    """scrypt 生产参数（n=16384）每次约 50ms，每个夹具 seed 5 个演示账号就是 0.25s。
    测试只验证“散列可校验、盐不同”，不验证抗暴力强度，所以把成本降到最低；
    生产参数由 test_identity_auth 在干净子进程里断言。"""
    from haiknow_core import passwords
    monkeypatch.setattr(passwords, "SCRYPT_N", 2)


@pytest.fixture
def isolated_platform(tmp_path, monkeypatch):
    """测试默认隔离宿主模型配置；需要真实路径的测试自行注入本地桩地址。"""
    for name in ("PROVIDER", "BASE_URL", "API_KEY", "NAME"):
        monkeypatch.delenv(f"HAIKNOW_MODEL_{name}", raising=False)
    for name in list(os.environ):
        if name.startswith("HAIKNOW_PROVIDER_"):
            monkeypatch.delenv(name)
    # 旧应用验收显式启用开发账号；生产模式测试自行关闭。
    monkeypatch.setenv('HAIKNOW_DEMO_LOGIN', '1')

    config = tmp_path / "platform-config"
    config.mkdir()
    users = [
        ("sampleadmin", "样例管理员", "admin", ["*"]),
        ("sampleoperator", "样例办理员", "sampleoperator", ["sample-project"]),
        ("samplereviewer", "样例审核员", "samplereviewer", ["sample-project"]),
        ("sampleobserver", "样例观察员", "sampleobserver", ["sample-project"]),
        ("sampleoutsider", "项目外用户", "sampleoutsider", []),
        ("sampleextra", "样例协审员", "sampleextra", ["sample-project"]),
    ]
    (config / "users.yaml").write_text(json.dumps({"users": [
        dict(id=uid, name=name, position=name, roles=[role], projects=projects)
        for uid, name, role, projects in users
    ]}), encoding="utf-8")
    (config / "projects.yaml").write_text(json.dumps({"companies": [{
        "id": "sample-company", "name": "虚构测试机构", "projects": [
            {"id": "sample-project", "name": "示例项目",
             "products": [{"id": "sample-item", "name": "示例条目"}]},
            {"id": "limited-project", "name": "受限项目",
             "products": [{"id": "research-product", "name": "另一项目条目"}]},
        ],
    }]}), encoding="utf-8")
    (config / "roles.yaml").write_text(json.dumps({"roles": {
        "admin": {"grants": {"*": ["view", "operate", "approve", "admin"]}},
        "sampleextra": {"grants": {"sample-app": ["view", "approve"]}},
    }}), encoding="utf-8")
    apps = tmp_path / "platform-apps"
    # 需要保留两份独立的应用授权，以测试项目、应用和用户的交叉边界。
    shutil.copytree(PLATFORM_APP, apps / "sample-app")
    library = apps / "sample-library"
    library.mkdir()
    manifest = json.loads((PLATFORM_APP / "app.json").read_text())
    (library / "app.json").write_text(json.dumps({
        **manifest, "id": "sample-library", "name": "样例资料库"
    }), encoding="utf-8")
    monkeypatch.setenv("HAIKNOW_CONFIG_DIR", str(config))
    monkeypatch.setenv("HAIKNOW_APPS_DIR", str(apps))
    monkeypatch.setenv("HAIKNOW_DATA_DIR", str(tmp_path / "platform-data"))
    return config, apps


@pytest.fixture
def make_client(isolated_platform, reuse_loaded_routers, cheap_password_hash, monkeypatch):
    from fastapi.testclient import TestClient
    from haiknow_core.main import create_app

    def make(apps_dir: Path | None = None):
        with monkeypatch.context() as patch:
            patch.setenv("HAIKNOW_APPS_DIR", str(apps_dir or isolated_platform[1]))
            return TestClient(create_app(ROOT))

    return make


@pytest.fixture
def client_for(make_client, tmp_path, request):
    """测试实际应用。只有位于模板目录的测试需要先生成应用。"""
    app_dir = request.path.parents[1]
    apps = app_dir.parent if app_dir.name != "_template" else tmp_path / "template-repo/apps"

    def make(app_id: str, user: str = "sampleadmin"):
        if app_dir.name == "_template" and not (apps / app_id).exists():
            shutil.copytree(app_dir, apps / "_template", dirs_exist_ok=True)
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/new_app.py"), app_id,
                 "模板测试应用", "--owner", "tester", "--root", str(apps.parent)],
                check=True, capture_output=True,
            )
        c = make_client(apps)
        assert c.post("/api/auth/login", json={"user_id": user}).status_code == 200
        return c

    return make


@pytest.fixture
def jkq_accounts(isolated_platform, cheap_password_hash, monkeypatch):
    """经开区实例关闭卫华免密演示登录（#12）：把夹具账号改建成真实口令账号。

    返回 (create, login)：create() 等价 jkq.app.create_app() 并写入 users.yaml 里的账号；
    login(client, uid) 走 /api/v1/auth/login。口令每次运行随机生成，不入库。
    """
    import secrets

    import yaml

    config, _ = isolated_platform
    password = secrets.token_urlsafe(12)
    monkeypatch.delenv("HAIKNOW_DEMO_LOGIN", raising=False)
    monkeypatch.delenv("JKQ_DEMO_MODE", raising=False)
    roles = yaml.safe_load((ROOT / "config/roles.yaml").read_text(encoding="utf-8"))
    for role, spec in json.loads((config / "roles.yaml").read_text(encoding="utf-8"))["roles"].items():
        roles["roles"].setdefault(role, {"name": role, **spec})
    (config / "roles.yaml").write_text(json.dumps(roles, ensure_ascii=False), encoding="utf-8")

    def create():
        from haiknow_core.passwords import hash_password
        from jkq.app import create_app

        people = json.loads((config / "users.yaml").read_text(encoding="utf-8"))["users"]
        app = create_app()
        store = app.state.platform.store
        digest = hash_password(password)
        with store._lock, store._db as db:
            store.begin_write()
            for person in people:
                projects = person.get("projects", [])
                db.execute(
                    "insert into users (id,username,name,password_hash,status,last_login,failed_logins,"
                    "locked_until,demo,all_projects,session_gen) values (?,?,?,?,'active',null,0,0,0,?,0)",
                    (person["id"], person["id"], person["name"], digest, int("*" in projects)),
                )
                for role in person.get("roles", []):
                    db.execute("insert or ignore into roles values (?,?,1)", (role, role))
                    db.execute("insert into user_roles values (?,?)", (person["id"], role))
                for project in projects:
                    if project != "*":
                        db.execute("insert or ignore into project_members values (?,?)", (project, person["id"]))
        return app

    def login(client, uid):
        response = client.post("/api/v1/auth/login", json={"username": uid, "password": password})
        assert response.status_code == 200, response.text
        return response

    return create, login

"""四个业务应用共用同一份跨端及种子契约。"""
import json
import subprocess
from importlib import import_module
from pathlib import Path
from haiknow_core.store import AppKV, Store

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCES = {"policy": "rules", "enterprise": "enterprises", "meeting": "minutes", "document": "gongwen"}
FIELDS = ("tools", "intents", "accepts", "routes")


@pytest.mark.parametrize("app", SOURCES)
def test_v4_manifest(app):
    script = """
        global.window = {};
        global.JK = { registerApp({manifest}) {
            console.log(JSON.stringify(manifest, (_, value) =>
                value instanceof RegExp ? value.source : value));
        }};
        const base = './web/apps/' + process.argv[1];
        require(base + '/config.js');
        require(base + '/app.js');
    """
    frontend = json.loads(subprocess.check_output(["node", "-e", script, app], cwd=ROOT))
    backend = json.loads((ROOT / "apps" / app / "app.json").read_text())
    assert frontend["id"] == backend["id"] == app
    if app == "policy":
        # 比较两端共同声明的能力。后端还声明工具桥的端点和写入语义。
        backend["tools"] = [
            {"name": tool["name"], "desc": tool["description"], "params": tool["input"]}
            for tool in backend["tools"]
        ]
    assert {k: backend[k] for k in FIELDS} == {k: frontend[k] for k in FIELDS}
    print(f"{app} 清单比对：0 差异")


@pytest.mark.parametrize(("app", "source"), SOURCES.items())
def test_seed_replaces_reference_snapshot(app, source, tmp_path):
    reset = import_module(f"apps.{app}.api.router").reset_seed
    kv = AppKV(Store(tmp_path / "platform-data"), app)
    kv.put("existing", 1)
    seed_dir = ROOT / "data/seed"
    expected = json.loads((seed_dir / "real" / f"{source}.json").read_text())
    assert expected
    for _ in range(2):
        reset(kv, seed_dir)
        assert kv.list() == {"existing": 1, f"reference:{source}": expected}

    (tmp_path / "real").mkdir()
    path = tmp_path / "real" / f"{source}.json"
    path.write_text("[null]")
    with pytest.raises(ValueError, match="对象数组"):
        reset(kv, tmp_path)
    assert kv.get(f"reference:{source}") == expected
    path.write_text("[]")
    reset(kv, tmp_path)
    assert kv.list() == {"existing": 1, f"reference:{source}": []}


def test_platform_discovers_all_four(client_for):
    response = client_for("policy").get("/api/apps")
    assert response.status_code == 200
    assert set(SOURCES) <= {app["id"] for app in response.json()["apps"]}


@pytest.fixture
def business_accounts(isolated_platform):
    config, _ = isolated_platform
    path = config / "users.yaml"
    users = json.loads(path.read_text())
    for role in ("leader", "member", "partner"):
        users["users"].append({"id": role, "name": role, "roles": [role], "projects": []})
    path.write_text(json.dumps(users))


@pytest.mark.parametrize(("role", "visible"), [
    ("sampleadmin", set(SOURCES)),
    ("leader", set(SOURCES)),
    ("member", set(SOURCES)),
    ("partner", {"policy", "enterprise"}),
    ("sampleoutsider", set()),
])
def test_catalog_and_health_follow_business_grants(client_for, business_accounts, role, visible):
    client = client_for("policy", user=role)
    catalog = client.get("/api/apps")
    assert catalog.status_code == 200
    assert {item["id"] for item in catalog.json()["apps"]} & set(SOURCES) == visible
    for app in SOURCES:
        response = client.get(f"/api/apps/{app}/health")
        assert response.status_code == (200 if app in visible else 403)


def test_existing_install_keeps_admin_grant_decisions(make_client, business_accounts, tmp_path):
    import shutil

    # 旧切片只登记样例角色。升级清单后保留现有授权，管理员按正式矩阵补录。
    apps = tmp_path / "old-apps"
    for app in SOURCES:
        shutil.copytree(ROOT / "apps" / app, apps / app)
        path = apps / app / "app.json"
        manifest = json.loads(path.read_text())
        manifest["defaultRoles"] = {"sampleoperator": ["view", "operate"]}
        path.write_text(json.dumps(manifest))
    make_client(apps)
    for app in SOURCES:
        shutil.copyfile(ROOT / "apps" / app / "app.json", apps / app / "app.json")
    client = make_client(apps)

    def login(user):
        return client.post("/api/auth/login", json={"user_id": user})

    assert login("member").status_code == 200
    assert client.get("/api/apps/policy/health").status_code == 403
    assert login("sampleadmin").status_code == 200
    for app in SOURCES:
        manifest = json.loads((apps / app / "app.json").read_text())
        for role, actions in manifest["defaultRoles"].items():
            if role != "admin":
                assert client.put(f"/api/admin/grants/{role}/{app}", json={"actions": actions}).status_code == 200
        assert client.put(f"/api/admin/grants/sampleoperator/{app}", json={"actions": []}).status_code == 200
    client = make_client(apps)
    for role, allowed in (("member", set(SOURCES)), ("partner", {"policy", "enterprise"}),
                          ("sampleoperator", set())):
        assert login(role).status_code == 200
        catalog = client.get("/api/apps").json()["apps"]
        assert {entry["id"] for entry in catalog} & set(SOURCES) == allowed
        for app in SOURCES:
            assert client.get(f"/api/apps/{app}/health").status_code == (200 if app in allowed else 403)


def test_platform_start_and_restart_without_master_key(make_client, tmp_path):
    for _ in range(2):
        client = make_client(ROOT / "apps")
        assert client.get("/api/apps/document/health").status_code == 401
        assert not (tmp_path / "platform-data" / "ai-master.key").exists()

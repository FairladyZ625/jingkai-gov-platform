"""验证干净快照的启动边界。"""

import sys

from fastapi.testclient import TestClient

from haiknow_core.main import create_app

RETAINED_PATHS = {
    "/api/auth/state",
    "/api/apps",
    "/api/v1/me",
    "/api/v1/ai/parse",
    "/api/v1/knowledge/entries",
    "/api/v1/jobs",
    "/api/v1/schedules",
}
DISABLED_PATHS = (
    "/api/v1/admin/feishu",
    "/api/v1/admin/datasets",
    "/api/v1/admin/data-sources",
    "/api/v1/feishu",
    "/api/v1/cad",
    "/api/v1/latex",
    "/api/v1/datasets",
    "/api/v1/builder",
)


def test_clean_start_retains_core_and_excludes_optional_modules(tmp_path, monkeypatch):
    for setting in ("APPS_DIR", "DATA_DIR", "CONFIG_DIR", "DEMO_LOGIN"):
        monkeypatch.delenv(f"HAIKNOW_{setting}", raising=False)
    monkeypatch.setenv("HAIKNOW_PREVIEW_TOKEN", "fixture-preview")
    monkeypatch.setenv("HAIKNOW_KB_SEED", "1")

    with TestClient(create_app(tmp_path / "empty-root")) as client:
        assert client.get("/api/health").json() == {
            "ok": True, "apps": 0, "unavailable": [], "broken": 0, "model": "mock"
        }
        assert client.get("/api/auth/state").json() == {"needsBootstrap": True, "demoLogin": False}
        assert client.get("/api/auth/users").status_code == 404
        assert client.get("/api/v1/me").status_code == 401
        paths = client.get("/openapi.json").json()["paths"]
        assert RETAINED_PATHS <= paths.keys()
        assert not any(path.startswith(DISABLED_PATHS) for path in paths)
        # 嵌入代理和造应用预览曾注册为不进入 OpenAPI 的路由。
        assert client.get("/embed/example").status_code == 404
        assert client.get("/__preview/enter").status_code == 404

    disabled_modules = {"feishu", "cad", "latex", "datasets", "embed_proxy", "builder"}
    assert not any(
        name.split(".")[1] in disabled_modules
        for name in sys.modules if name.startswith("haiknow_core.")
    )

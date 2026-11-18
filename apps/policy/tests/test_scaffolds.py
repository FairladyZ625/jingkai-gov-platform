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
        const base = './prototype/v4/apps/' + process.argv[1];
        require(base + '/config.js');
        require(base + '/app.js');
    """
    frontend = json.loads(subprocess.check_output(["node", "-e", script, app], cwd=ROOT))
    backend = json.loads((ROOT / "apps" / app / "app.json").read_text())
    assert frontend["id"] == backend["id"] == app
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

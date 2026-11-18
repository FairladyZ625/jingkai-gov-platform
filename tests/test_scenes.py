"""场景表加载校验与 /api/coverage 覆盖视图。"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from haiknow_core import scenes

@pytest.fixture
def scene_config(isolated_platform):
    config = isolated_platform[0]
    _table(config, """groups:
  - id: records
    name: 记录
    scenes:
      - {id: R01, name: 草稿, first: true}
      - {id: R02, name: 确认, first: true}
      - {id: R03, name: 归档}
  - id: resources
    name: 资料
    scenes:
      - {id: R06, name: 检索, first: true}
  - id: pending
    name: 待接入
    scenes:
      - {id: N01, name: 摘要}
""")
    return config


def _table(directory: Path, text: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "scenes.yaml").write_text(text, encoding="utf-8")


def _app(apps: Path, app_id: str, status: str, codes: list[str]) -> None:
    directory = apps / app_id
    (directory / "web").mkdir(parents=True, exist_ok=True)
    (directory / "web" / "index.js").write_text("export async function mount() {}\n", encoding="utf-8")
    manifest = {
        "contract": 1,
        "sdk": "1",
        "id": app_id,
        "name": f"应用 {app_id}",
        "sector": "manufacturing",
        "kind": "module",
        "scenes": codes,
        "owner": "tester",
        "actions": ["view"],
        "defaultRoles": {"sampleoperator": ["view"]},
        "status": status,
    }
    (directory / "app.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def _login(client, user: str = "sampleadmin"):
    assert client.post("/api/auth/login", json={"user_id": user}).status_code == 200
    return client


def test_scene_table_reads_groups_order_and_first_batch(scene_config):
    table = scenes.load(scene_config)
    assert not table.error
    assert [group.id for group in table.groups] == ["records", "resources", "pending"]
    assert table.codes() == {"R01", "R02", "R03", "R06", "N01"}
    assert [scene.id for scene in table if scene.first] == ["R01", "R02", "R06"]


def test_duplicate_scene_code_is_rejected(tmp_path):
    _table(tmp_path, "groups:\n  - id: a\n    name: 甲组\n    scenes:\n      - {id: R01, name: 甲}\n      - {id: R01, name: 乙}\n")
    with pytest.raises(scenes.SceneTableError, match="场景编号重复：R01"):
        scenes.load(tmp_path)


def test_missing_scene_name_is_rejected(tmp_path):
    _table(tmp_path, "groups:\n  - id: a\n    name: 甲组\n    scenes:\n      - {id: R01}\n")
    with pytest.raises(scenes.SceneTableError, match=r"scenes\[1\]\.name"):
        scenes.load(tmp_path)


def test_non_boolean_first_is_rejected(tmp_path):
    _table(tmp_path, "groups:\n  - id: a\n    name: 甲组\n    scenes:\n      - {id: R01, name: 甲, first: 'yes'}\n")
    with pytest.raises(scenes.SceneTableError, match="first 必须是 true 或 false"):
        scenes.load(tmp_path)


def test_missing_table_is_reported(tmp_path):
    with pytest.raises(scenes.SceneTableError, match="不存在"):
        scenes.load(tmp_path)


def test_unknown_codes_are_table_external(scene_config):
    table = scenes.load(scene_config)
    assert scenes.unknown_codes(table, ["DEMO", "R01", "P02", "R01"]) == ["DEMO", "P02"]


def test_coverage_requires_login(make_client, tmp_path):
    assert make_client(tmp_path / "apps").get("/api/coverage").status_code == 401


def test_coverage_groups_keep_legacy_fields_and_report_unknown(make_client, tmp_path, scene_config):
    apps = tmp_path / "apps"
    _app(apps, "alpha", "usable", ["R01", "R06"])
    _app(apps, "beta", "prototype", ["R02", "XYZ"])
    client = _login(make_client(apps))
    data = client.get("/api/coverage").json()

    # 旧字段保留原样：编号 → 应用名称。
    assert data["apps"] == 2
    assert data["sectors"] == {"manufacturing": 2}
    assert data["scenes"] == {
        "R01": ["应用 alpha"], "R06": ["应用 alpha"], "R02": ["应用 beta"], "XYZ": ["应用 beta"],
    }
    assert data["coverage"] == {"covered": 3, "total": 5, "rate": 0.6}
    assert data["firstBatch"] == {"covered": 3, "total": 3, "rate": 1.0}
    assert data["unknown"] == ["XYZ"]
    assert data["tableError"] == ""

    groups = {group["id"]: group for group in data["groups"]}
    assert [group["id"] for group in data["groups"]] == [
        "records", "resources", "pending",
    ]
    quality = groups["records"]
    assert (quality["covered"], quality["total"]) == (2, 3)
    assert [scene["id"] for scene in quality["scenes"]] == ["R01", "R02", "R03"]
    r01, r02 = quality["scenes"][0], quality["scenes"][1]
    assert r01["state"] == "usable" and r01["apps"] == [
        {"id": "alpha", "name": "应用 alpha", "status": "usable"},
    ]
    assert r02["state"] == "prototype" and r02["first"] is True
    assert groups["resources"]["scenes"][0]["id"] == "R06"
    assert groups["resources"]["scenes"][0]["state"] == "usable"
    assert groups["pending"]["scenes"][0]["state"] == "todo"
    assert groups["pending"]["scenes"][0]["apps"] == []


def test_unknown_scene_code_warns_at_startup(make_client, tmp_path, caplog, scene_config):
    apps = tmp_path / "apps"
    _app(apps, "alpha", "usable", ["XYZ"])
    with caplog.at_level(logging.WARNING, logger="haiknow"):
        make_client(apps)
    assert "XYZ" in caplog.text
    assert "platform-config/scenes.yaml" in caplog.text


def test_broken_scene_table_does_not_block_platform(make_client, tmp_path, caplog, scene_config):
    _table(scene_config, "groups: 不是列表\n")
    apps = tmp_path / "apps"
    _app(apps, "alpha", "usable", ["R01"])
    with caplog.at_level(logging.ERROR, logger="haiknow"):
        client = _login(make_client(apps))
    assert "场景表不可用" in caplog.text
    assert client.get("/api/health").json()["apps"] == 1
    data = client.get("/api/coverage").json()
    assert data["groups"] == []
    assert data["coverage"] == {"covered": 0, "total": 0, "rate": 0}
    assert "groups" in data["tableError"]
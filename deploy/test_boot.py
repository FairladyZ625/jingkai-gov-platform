"""空库首管关闭、公网路径和续跑任务。不启动容器，也不打印口令。"""
import shutil
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="经开区集成测试需要 requirements-dev.txt")
from fastapi.testclient import TestClient

from deploy.entrypoint import (
    require_demo_passwords,
    use_same_origin_http,
    write_boot_token,
)
from jkq.app import create_app


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = Path(__file__).resolve().parent
HOLD = DEPLOY / "hold" / "jkq-hold"
PASSWORDS = {
    "JKQ_DEMO_ADMIN_PASSWORD": "fixture-admin-pass",
    "JKQ_DEMO_LEADER_PASSWORD": "fixture-leader-pass",
    "JKQ_DEMO_MEMBER_PASSWORD": "fixture-member-pass",
    "JKQ_DEMO_PARTNER_PASSWORD": "fixture-partner-pass",
}


def test_demo_mode_rejects_missing_or_short_passwords(monkeypatch):
    monkeypatch.setenv("JKQ_DEMO_MODE", "1")
    for name in PASSWORDS:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match="JKQ_DEMO_ADMIN_PASSWORD"):
        require_demo_passwords()
    for name, value in PASSWORDS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("JKQ_DEMO_MEMBER_PASSWORD", "short")
    with pytest.raises(SystemExit, match="JKQ_DEMO_MEMBER_PASSWORD"):
        require_demo_passwords()
    monkeypatch.setenv("JKQ_DEMO_MEMBER_PASSWORD", PASSWORDS["JKQ_DEMO_MEMBER_PASSWORD"])
    require_demo_passwords()
    monkeypatch.setenv("JKQ_DEMO_MODE", "0")
    monkeypatch.delenv("JKQ_DEMO_ADMIN_PASSWORD")
    require_demo_passwords()


def test_public_proxy_rejects_bootstrap_before_forwarding():
    text = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    blocked = text.index("@bootstrap")
    forwarded = text.index("reverse_proxy")
    assert blocked < forwarded
    assert "/api/auth/bootstrap" in text and "/api/v1/auth/bootstrap" in text
    assert "respond 404" in text
    health = (DEPLOY / "healthcheck.py").read_text(encoding="utf-8")
    assert "/api/health" in health and "/api/v1/auth/bootstrap" in health
    compose = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    assert "deploy/healthcheck.py" in compose
    assert 'JKQ_DEPLOY_RUNTIME: "1"' in compose
    ignore = (DEPLOY / "Dockerfile.dockerignore").read_text(encoding="utf-8")
    for line in ("!deploy/entrypoint.py", "!deploy/healthcheck.py", "!deploy/hold/jkq-hold/**"):
        assert line in ignore
    assert "cp -a deploy/hold/jkq-hold apps/jkq-hold" in (DEPLOY / "Dockerfile").read_text(encoding="utf-8")


def test_runtime_patch_is_opt_in_and_keeps_source_mock(tmp_path, monkeypatch):
    source = ROOT / "prototype/v4/config/app.config.js"
    original = source.read_text(encoding="utf-8")
    target = tmp_path / "prototype/v4/config/app.config.js"
    target.parent.mkdir(parents=True)
    target.write_text(original, encoding="utf-8")
    monkeypatch.delenv("JKQ_DEPLOY_RUNTIME", raising=False)
    use_same_origin_http(tmp_path)
    assert "mode: 'mock'" in target.read_text(encoding="utf-8")
    monkeypatch.setenv("JKQ_DEPLOY_RUNTIME", "1")
    use_same_origin_http(tmp_path)
    patched = target.read_text(encoding="utf-8")
    assert "mode: 'http'" in patched and "baseUrl: ''" in patched
    assert source.read_text(encoding="utf-8") == original


def test_empty_volume_closes_bootstrap_and_hold_survives_restart(tmp_path, monkeypatch, cheap_password_hash):
    apps = tmp_path / "apps"
    data = tmp_path / "data"
    shutil.copytree(HOLD, apps / "jkq-hold")
    for name in tuple(__import__("os").environ):
        if name.startswith(("HAIKNOW_MODEL_", "HAIKNOW_PROVIDER_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HAIKNOW_SECRET", "isolated-test-signing-value")
    monkeypatch.setenv("HAIKNOW_DEMO_LOGIN", "0")
    monkeypatch.setenv("JKQ_DEMO_MODE", "1")
    monkeypatch.setenv("HAIKNOW_CONFIG_DIR", str(ROOT / "config"))
    monkeypatch.setenv("HAIKNOW_APPS_DIR", str(apps))
    monkeypatch.setenv("HAIKNOW_DATA_DIR", str(data))
    monkeypatch.setenv("HAIKNOW_ROOT", str(ROOT))
    monkeypatch.delenv("JKQ_DEPLOY_RUNTIME", raising=False)
    for name, value in PASSWORDS.items():
        monkeypatch.setenv(name, value)
    write_boot_token(data)

    with TestClient(create_app()) as client:
        assert client.get("/api/auth/state").json()["needsBootstrap"] is False
        assert client.post("/api/v1/auth/bootstrap", json={}).status_code == 404
        assert client.post("/api/auth/bootstrap", json={}).status_code == 404
        login = client.post("/api/v1/auth/login", json={
            "username": "admin", "password": PASSWORDS["JKQ_DEMO_ADMIN_PASSWORD"],
        })
        assert login.status_code == 200, login.text
        assert login.json()["role"]["id"] == "admin"
        assert client.get("/api/v1/auth/session").json()["user"]["username"] == "admin"
        created = client.post("/api/v1/jobs", json={
            "appId": "jkq-hold", "project": "jkq", "operation": "hold",
            "input": {}, "idempotencyKey": "hold-once",
        })
        assert created.status_code == 202, created.text
        job_id = created.json()["id"]
        first = _wait(client, job_id, lambda doc: (
            doc.get("status") == "running" and doc.get("steps")
            and doc["steps"][0]["status"] == "done" and doc["steps"][0]["name"] == "saved"
        ))

    write_boot_token(data)
    with TestClient(create_app()) as client:
        again = client.post("/api/v1/auth/login", json={
            "username": "admin", "password": PASSWORDS["JKQ_DEMO_ADMIN_PASSWORD"],
        })
        assert again.status_code == 200, again.text
        finished = _wait(client, job_id, lambda doc: doc.get("status") == "done")
        assert finished["id"] == job_id
        assert finished["steps"][0]["status"] == "done"
        assert finished["steps"][0]["result"] == first["steps"][0]["result"]
        assert client.app.state.platform.store.kv_get("jkq-hold", "hold-saved") == 1


def _wait(client, job_id, ready):
    deadline = time.monotonic() + 8
    last = None
    while time.monotonic() < deadline:
        last = client.get(f"/api/v1/jobs/{job_id}", params={"app": "jkq-hold"}).json()
        if ready(last):
            return last
        time.sleep(0.05)
    pytest.fail(str(last))

"""使用临时 Git 远端、真实目录及 Docker 命令替身验证运维流程。"""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

DEPLOY = Path(__file__).resolve().parent


@pytest.fixture
def site(tmp_path):
    repo = tmp_path / "repo"
    target = repo / "deploy"
    target.mkdir(parents=True)
    for name in ("demo", "Makefile", "env.example", "docker-compose.yml"):
        shutil.copy2(DEPLOY / name, target)
    state = tmp_path / "state"
    (state / "data").mkdir(parents=True)
    bins = tmp_path / "bin"
    bins.mkdir()
    for name, body in {
        "docker": """
echo "$*" >> "$DEMO_STATE_DIR/calls"
case "$*" in
  *'ps -q app') echo container ;;
  inspect*Config.Image*) echo jkq-demo-app:old ;;
  inspect*) echo sha256:old ;;
  *'build app') test ! -f "$DEMO_STATE_DIR/build-failure" ;;
  *'up -d'*) if test -f "$DEMO_STATE_DIR/unhealthy"; then rm "$DEMO_STATE_DIR/unhealthy"; exit 1; fi ;;
esac
""",
        "flock": 'test ! -f "$DEMO_STATE_DIR/locked"',
    }.items():
        command = bins / name
        command.write_text("#!/bin/sh\n" + body + "\n")
        command.chmod(0o755)
    env = {**os.environ, "PATH": f"{bins}:{os.environ['PATH']}",
           "DEMO_STATE_DIR": str(state)}

    def run(*args, check=True):
        return subprocess.run(args, cwd=repo, env=env, capture_output=True,
                              text=True, check=check)

    return repo, state, run


def test_reset(site):
    repo, state, run = site
    assert run("deploy/demo", "snapshot", check=False).returncode
    assert run("deploy/demo", "reset", check=False).returncode
    assert not (state / "calls").exists()
    record = state / "data" / "record"
    record.write_text("初始")
    run("deploy/demo", "snapshot")
    record.write_text("变更")
    extra = state / "data" / ".extra"
    extra.touch()
    (state / "unhealthy").touch()
    assert run("deploy/demo", "reset", check=False).returncode
    assert record.read_text() == "变更" and extra.exists()
    run("make", "-f", "deploy/Makefile", "demo-reset")
    assert record.read_text() == "初始" and not extra.exists()
    (state / "locked").touch()
    assert run("deploy/demo", "reset", check=False).returncode


@pytest.mark.parametrize("failure", [None, "build-failure", "unhealthy"])
def test_release(site, failure):
    repo, state, run = site
    run("git", "init", "-b", "main")
    run("git", "config", "user.email", "test@example.invalid")
    run("git", "config", "user.name", "test")
    run("git", "add", "deploy")
    run("git", "commit", "-m", "基线")
    old = run("git", "rev-parse", "HEAD").stdout.strip()
    remote = repo.parent / "release.git"
    run("git", "clone", "--bare", ".", str(remote))
    run("git", "remote", "add", "origin", str(remote))
    run("git", "commit", "--allow-empty", "-m", "更新")
    new = run("git", "rev-parse", "HEAD").stdout.strip()
    run("git", "push", "origin", "main")
    run("git", "switch", "--detach", old)
    if failure:
        (state / failure).touch()
        assert run("deploy/demo", "update", check=False).returncode
    else:
        run("deploy/demo", "update")
        assert run("git", "rev-parse", "HEAD").stdout.strip() == new
        run("deploy/demo", "rollback")
    assert run("git", "rev-parse", "HEAD").stdout.strip() == old
    assert "tag sha256:old jkq-demo-app:restored" in (state / "calls").read_text()


def test_compose(site):
    repo, _, _ = site
    if not shutil.which("docker"):
        pytest.skip("需要 Compose CLI")
    shutil.copy(repo / "deploy/env.example", repo / "deploy/.env")
    result = subprocess.check_output(
        ["docker", "compose", "-f", "deploy/docker-compose.yml", "config", "--format", "json"],
        cwd=repo, text=True,
    )
    services = json.loads(result)["services"]
    app, proxy = services["app"], services["proxy"]
    assert app["command"][-2:] == ["--workers", "1"]
    assert app["volumes"][0]["target"] == app["environment"]["HAIKNOW_DATA_DIR"]
    assert "ports" not in app
    assert {port["target"] for port in proxy["ports"]} == {80, 443}
    assert proxy["environment"]["DEMO_DOMAIN"] == "demo.example.invalid"

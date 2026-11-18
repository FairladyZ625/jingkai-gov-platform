"""使用临时 Git 远端、真实目录及 Docker 命令替身验证运维流程。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import sys
try:
    import fcntl
except ImportError:
    fcntl = None

import pytest

DEPLOY = Path(__file__).resolve().parent


@pytest.fixture
def site(tmp_path):
    if fcntl is None:
        pytest.skip("deploy/demo 运维脚本与 fcntl 文件锁测试仅支持 POSIX 环境")
    repo = tmp_path / "repo"
    target = repo / "deploy"
    target.mkdir(parents=True)
    for name in ("demo", "Makefile", "env.example", "docker-compose.yml", "Caddyfile"):
        shutil.copy2(DEPLOY / name, target)
    shutil.copy(target / "env.example", target / ".env")
    state = tmp_path / "state"
    (state / "data").mkdir(parents=True)
    bins = tmp_path / "bin"
    bins.mkdir()
    for name, body in {
        "docker": """
case "$*" in
  *'config --no-env-resolution --format json app')
    if test -n "$TEST_COMPOSE"; then exec "$TEST_COMPOSE" "$@"; fi
    printf '{"services":{"app":{"volumes":[{"type":"bind","target":"/state/live","source":"%s/data"}]}}}\\n' "$DEMO_STATE_DIR"
    exit 0 ;;
esac
echo "$*" >> "$DEMO_STATE_DIR/calls"
case "$*" in
  *'ps -q app')
    if test -f "$DEMO_STATE_DIR/starting"; then rm "$DEMO_STATE_DIR/starting"; else echo container; fi ;;
  *'exec -T proxy printenv DEMO_DOMAIN') echo demo.example.invalid ;;
  inspect*Config.Image*) echo jkq-demo-app:old ;;
  inspect*) echo sha256:old ;;
  *'build app') test ! -f "$DEMO_STATE_DIR/build-failure" ;;
  *'up -d'*) echo "$DEMO_TAG" > "$DEMO_STATE_DIR/running"
    if test -f "$DEMO_STATE_DIR/unhealthy"; then rm "$DEMO_STATE_DIR/unhealthy"; exit 1; fi ;;
esac
""",
        "curl": """
echo "$*" >> "$DEMO_STATE_DIR/probes"
cat deploy/Caddyfile >> "$DEMO_STATE_DIR/loaded"
if test -f "$DEMO_STATE_DIR/recovery-probe-failure" && test "$DEMO_TAG" = restored; then echo 503; exit 22; fi
if test -f "$DEMO_STATE_DIR/proxy-failure"; then rm "$DEMO_STATE_DIR/proxy-failure"; echo 302; else echo 200; fi
""",
        "mv": """
if test -f "$DEMO_STATE_DIR/rename-failure" && test "$1" = "$DEMO_STATE_DIR/data"; then exit 71; fi
exec /bin/mv "$@"
""",
        "python3": f'''if test "$2" = 'import os,sys; os.replace(*sys.argv[1:])' && test -f "$DEMO_STATE_DIR/record-failure"; then exit 73; fi
exec "{sys.executable}" "$@"''',
        "flock": f'''exec "{sys.executable}" - "$@" <<'PYLOCK'
import fcntl, sys
args = sys.argv[1:]
if args not in (["-w", "1800", "9"], ["-n", "9"]):
    sys.exit(2)
flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if args[0] == "-n" else 0)
fcntl.flock(9, flags)
PYLOCK''',
    }.items():
        command = bins / name
        command.write_text("#!/bin/sh\n" + body + "\n")
        command.chmod(0o755)
    env = {**os.environ, "TEST_COMPOSE": shutil.which("docker") or "", "PATH": f"{bins}:{os.environ['PATH']}",
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
    with (state / "operation.lock").open() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert run("deploy/demo", "reset", check=False).returncode
    record.write_text("保留")
    (state / "rename-failure").touch()
    calls = state / "calls"
    calls.write_text("")
    assert run("deploy/demo", "reset", check=False).returncode == 71
    assert record.read_text() == "保留"
    assert "stop app" in calls.read_text()
    assert "up -d --no-build --force-recreate" in calls.read_text().splitlines()[-1]


def publish_release(repo, run):
    run("git", "init", "-b", "main")
    run("git", "config", "user.email", "test@example.invalid")
    run("git", "config", "user.name", "test")
    run("git", "add", "deploy")
    run("git", "commit", "-m", "基线")
    old = run("git", "rev-parse", "HEAD").stdout.strip()
    run("git", "clone", "--bare", ".", str(repo.parent / "release.git"))
    run("git", "remote", "add", "origin", str(repo.parent / "release.git"))
    with (repo / "deploy/Caddyfile").open("a") as config:
        config.write("# 仅反代配置变更\n")
    run("git", "commit", "-am", "更新反代")
    new = run("git", "rev-parse", "HEAD").stdout.strip()
    run("git", "push", "origin", "main")
    run("git", "switch", "--detach", old)
    return old, new


def test_failed_recovery_probe_still_restores_default_image(site):
    repo, state, run = site
    old, new = publish_release(repo, run)
    (state / "record-failure").touch()
    (state / "recovery-probe-failure").touch()
    result = run("deploy/demo", "update", check=False)
    assert result.returncode == 73
    assert "回退后的健康检查失败" in result.stderr
    assert run("git", "rev-parse", "HEAD").stdout.strip() == old
    local_tags = [line for line in (state / "calls").read_text().splitlines()
                  if line.startswith("tag ") and line.endswith(" jkq-demo-app:local")]
    assert local_tags == [f"tag jkq-demo-app:{new} jkq-demo-app:local", "tag sha256:old jkq-demo-app:local"]
    assert not (state / "previous").exists()


@pytest.mark.parametrize("failure", [None, "build-failure", "unhealthy", "proxy-failure", "record-failure"])
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
    with (repo / "deploy/Caddyfile").open("a") as config:
        config.write("# 仅反代配置变更\n")
    run("git", "commit", "-am", "更新反代")
    new = run("git", "rev-parse", "HEAD").stdout.strip()
    run("git", "push", "origin", "main")
    run("git", "switch", "--detach", old)
    previous = state / "previous"
    if failure:
        (state / failure).touch()
        previous.write_text("prior sha256:prior\n")
        result = run("deploy/demo", "update", check=False)
        assert result.returncode
        if failure == "record-failure":
            assert result.returncode == 73
        assert previous.read_text() == "prior sha256:prior\n"
    else:
        run("deploy/demo", "update")
        assert run("git", "rev-parse", "HEAD").stdout.strip() == new
        assert previous.read_text() == f"{old} sha256:old\n"
        assert (state / "running").read_text().strip() == new
        run("deploy/demo", "rollback")
    assert (state / "running").read_text().strip() == "restored"
    assert (state / "loaded").read_text().endswith((DEPLOY / "Caddyfile").read_text())
    if failure != "build-failure" and failure != "unhealthy":
        assert "# 仅反代配置变更" in (state / "loaded").read_text()
    assert "--resolve demo.example.invalid:443:127.0.0.1" in (state / "probes").read_text()
    assert "--force-recreate" in (state / "calls").read_text()
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
    assert app["command"][3:5] == ["jkq.app:create_app", "--factory"]
    assert app["volumes"][0]["target"] == app["environment"]["HAIKNOW_DATA_DIR"]
    assert "ports" not in app
    assert {port["target"] for port in proxy["ports"]} == {80, 443}
    assert proxy["environment"]["DEMO_DOMAIN"] == "demo.example.invalid"


def test_image_context_keeps_runtime_directories():
    allowed = set((DEPLOY / "Dockerfile.dockerignore").read_text(encoding="utf-8").split())
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    pythonpath = next(line for line in dockerfile.splitlines() if "PYTHONPATH=" in line)
    for entry in pythonpath.split("PYTHONPATH=")[1].split()[0].split(":"):
        relative = entry.removeprefix("/srv/app").strip("/")
        if relative:
            assert f"!{relative}/**" in allowed
    web = "web" if (DEPLOY.parent / "web/index.html").is_file() else "prototype/v4"
    assert f"!{web}/**" in allowed


def test_scheduled_reset_uses_configured_mount_after_lock(site, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    if not shutil.which("docker"):
        pytest.skip("需要 Compose CLI 解析 .env 的挂载")
    repo, _, run = site
    state = repo.parent / "实际 数据"
    (state / "data").mkdir(parents=True)
    (state / "snapshot").mkdir()
    (state / "snapshot/record").write_text("基准")
    with (repo / "deploy/.env").open("a") as envfile:
        envfile.write(f'DEMO_STATE_DIR="{state}"\n')
    # 空环境覆盖改为真正移除，验证任务入口和 systemd 仅依赖 deploy/.env。
    monkeypatch.delenv("DEMO_STATE_DIR", raising=False)
    env = dict(os.environ, PATH=f"{repo.parent / 'bin'}:{os.environ['PATH']}",
               TEST_COMPOSE=shutil.which("docker"))
    service = (DEPLOY / "jkq-demo-reset.service").read_text()
    assert "ExecStart=/opt/jkq-demo/deploy/demo scheduled-reset" in service
    (state / "starting").touch()
    with ThreadPoolExecutor() as executor, (state / "operation.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        def invoke(action):
            return subprocess.run(["deploy/demo", action], cwd=repo, env=env,
                                  capture_output=True, timeout=12)
        assert "已有部署操作进行中" in invoke("update").stderr.decode()
        future = executor.submit(invoke, "scheduled-reset")
        time.sleep(0.4)
        assert not future.done() and not (state / "calls").exists()
        fcntl.flock(lock, fcntl.LOCK_UN)
        assert future.result().returncode == 0
    assert (state / "data/record").read_text() == "基准"
    assert (state / "calls").read_text().count("stop app") == 1

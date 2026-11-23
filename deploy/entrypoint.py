"""演示容器入口。

校验四个演示口令，旋转续跑标记，把容器内前端改成同源真实接口，
然后启动单进程实例。反代只在首管入口已经关闭后才会被健康检查放行。
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PASSWORD_ENVS = (
    "JKQ_DEMO_ADMIN_PASSWORD",
    "JKQ_DEMO_LEADER_PASSWORD",
    "JKQ_DEMO_MEMBER_PASSWORD",
    "JKQ_DEMO_PARTNER_PASSWORD",
)
BOOT_NAME = ".jkq-hold-boot"
BOOTSTRAP_PATHS = ("/api/v1/auth/bootstrap", "/api/auth/bootstrap")


def require_demo_passwords() -> None:
    if os.environ.get("JKQ_DEMO_MODE") != "1":
        return
    for name in PASSWORD_ENVS:
        value = os.environ.get(name)
        if value is None or not 6 <= len(value) <= 1024:
            raise SystemExit(f"{name} 未设置或长度不在 6 至 1024 位，容器拒绝启动")


def write_boot_token(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / BOOT_NAME
    path.write_text(os.urandom(16).hex(), encoding="utf-8")
    path.chmod(0o600)


def use_same_origin_http(root: Path) -> None:
    """只改容器里的前端配置。仓库里的原型保持 mock，file:// 仍可离线打开。

    JKQ_FRONTEND_API_MODE=mock 时保留浏览器内 mock，演示兜底用；默认 http。
    """
    if os.environ.get("JKQ_DEPLOY_RUNTIME") != "1":
        return
    if os.environ.get("JKQ_FRONTEND_API_MODE", "http").strip().lower() == "mock":
        return
    for relative in ("web/config/app.config.js", "prototype/v4/config/app.config.js"):
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        updated = text.replace("mode: 'mock'", "mode: 'http'", 1).replace(
            "baseUrl: 'http://127.0.0.1:8080'", "baseUrl: ''", 1)
        if updated != text:
            path.write_text(updated, encoding="utf-8")


def bootstrap_closed(port: str) -> bool:
    for path in BOOTSTRAP_PATHS:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        except (OSError, urllib.error.URLError):
            return False
        if status != 404:
            return False
    return True


def uvicorn_command(port: str) -> list[str]:
    return [
        sys.executable, "-m", "uvicorn", "jkq.app:create_app", "--factory",
        "--host", "0.0.0.0", "--port", port, "--workers", "1",
    ]


def main() -> int:
    require_demo_passwords()
    root = Path(os.environ.get("HAIKNOW_ROOT", "/srv/app"))
    use_same_origin_http(root)
    data_dir = Path(os.environ.get("HAIKNOW_DATA_DIR", "/state/live"))
    write_boot_token(data_dir)
    port = os.environ.get("APP_PORT", "8000")
    app_env = os.environ.copy()
    # 演示台账使用独立原值库；缺省放进同一持久数据卷，由快照一并备份。
    if app_env.get("JKQ_DEPLOY_RUNTIME") == "1" and app_env.get("JKQ_DEMO_MODE") == "1":
        app_env.setdefault("JKQ_ENTERPRISE_PRIVATE_DB", str(data_dir / "enterprise-private.sqlite"))
    process = subprocess.Popen(uvicorn_command(port), env=app_env)

    def stop(*_args):
        if process.poll() is None:
            process.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return process.returncode or 1
        if bootstrap_closed(port):
            return process.wait()
        time.sleep(0.2)
    stop()
    process.wait(timeout=20)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""经开区实例的目录与启动环境。"""

import os
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def required_environment() -> None:
    if not os.environ.get("HAIKNOW_SECRET", "").strip():
        raise RuntimeError("缺少必需环境变量 HAIKNOW_SECRET（会话签名）")


def instance_paths(root: Path) -> dict[str, str]:
    return {
        "HAIKNOW_ROOT": str(root),
        "HAIKNOW_APPS_DIR": str(root / "apps"),
        "HAIKNOW_DATA_DIR": str(root / "data/private/jkq"),
        "HAIKNOW_CONFIG_DIR": str(root / "config"),
    }


def web_directory(root: Path) -> Path:
    if configured := os.environ.get("JKQ_WEB_DIR"):
        directory = root / configured
    elif (root / "web").is_dir():
        directory = root / "web"
    else:
        directory = root / "prototype/v4"
    if not (directory / "index.html").is_file():
        raise RuntimeError(f"找不到经开区前端入口 {directory / 'index.html'}")
    return directory


@contextmanager
def core_environment(root: Path):
    defaults = {key: value for key, value in instance_paths(root).items() if not os.environ.get(key)}
    defaults["HAIKNOW_NO_AUTOAPP"] = "1"
    # core 是进程内工厂，目录只在构建应用时读取。
    previous = {key: os.environ.get(key) for key in defaults}
    try:
        os.environ.update(defaults)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

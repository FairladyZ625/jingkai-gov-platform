"""用现有 pytest CI 跑浏览器回归；npm 安装和截图都留在临时目录。"""

import os
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parents[1] / "docs/walkthrough/screenshots"


def test_mock_walkthrough(tmp_path):
    env = os.environ.copy()
    # 沿用演示冒烟的锁文件；全局 NODE_PATH 非空不代表已安装 Playwright。
    for filename in ("package.json", "package-lock.json"):
        shutil.copyfile(HERE.parent / "demo" / filename, tmp_path / filename)
    subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=tmp_path, check=True)
    env["NODE_PATH"] = str(tmp_path / "node_modules")
    if shutil.which("google-chrome"):
        env["WALKTHROUGH_CHROME"] = "1"
    subprocess.run(
        ["node", str(HERE / "run.cjs"), str(tmp_path / "screenshots")],
        env=env, check=True, timeout=1800,
    )
    actual = tmp_path / "screenshots"
    assert {p.relative_to(actual) for p in actual.rglob("*.jpg")} == {
        p.relative_to(EVIDENCE) for p in EVIDENCE.rglob("*.jpg")
    }
    assert sum(p.stat().st_size for p in EVIDENCE.rglob("*.jpg")) < 15_000_000

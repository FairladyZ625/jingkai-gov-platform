"""在具备 Codex 登录的主机显式运行独立冒烟，输入仅含固定测试文本。"""
import os
import shutil
import subprocess

import pytest


@pytest.mark.skipif(
    not shutil.which("codex") or os.getenv("JKQ_CODEX_SMOKE") != "1",
    reason="需本机 Codex 并设置 JKQ_CODEX_SMOKE=1",
)
def test_codex_cli(tmp_path):
    output = tmp_path / "reply.txt"
    subprocess.run(
        ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only",
         "--output-last-message", str(output), "只回复 JKQ_OK，不调用工具。"],
        cwd=tmp_path, timeout=90, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    assert output.read_text().strip() == "JKQ_OK"

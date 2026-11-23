"""通过现有 pytest 发现：不监听端口、不安装依赖；构建并测试从归档实际解出的副本。"""
from pathlib import Path
import subprocess


def test_archived_file_fixture(tmp_path):
    here = Path(__file__).resolve().parent
    dest = tmp_path / "t38-browser-ci"
    subprocess.run(["node", str(here / "build.cjs"), str(dest)], check=True)
    unpacked = tmp_path / "unpacked"
    unpacked.mkdir()
    subprocess.run(["tar", "-xzf", str(dest / "browser-fixture.tar.gz"), "-C", str(unpacked)], check=True)
    subprocess.run(["node", str(here / "check.cjs"), str(unpacked / "browser-fixture")], check=True)

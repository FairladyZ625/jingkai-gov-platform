from pathlib import Path
import subprocess
import sys

import pytest


MIGRATION = Path(__file__).resolve().parents[2] / "scripts/migrate_v4_to_web.py"


def git(root, *args):
    return subprocess.check_output(["git", "-C", root, *args], text=True)


def migrate(root):
    return subprocess.run([sys.executable, MIGRATION], cwd=root, capture_output=True, text=True)


@pytest.fixture
def original(tmp_path):
    source = {
        "prototype/v4/index.html": '<script src="feature/widget.js"></script>',
        "prototype/v4/feature/widget.js": "window.widget = true;",
        "prototype/v4/接口规范.md": "接口规范",
        "prototype/v4/APP_CONTRACT.md": "应用契约",
        "tests/demo/run.cjs": "const entry = '../../prototype/v4/index.html';",
    }
    git(tmp_path, "init", "-q")
    for name, content in source.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "user.name=迁移测试", "-c", "user.email=fixture@example.invalid",
        "-c", "core.hooksPath=/dev/null", "commit", "-qm", "原型样例")
    return tmp_path


def test_migration_moves_all_tracked_files_and_updates_existing_demo(original):
    (original / "prototype/v4/local.txt").write_text("仅存在于本地", encoding="utf-8")
    result = migrate(original)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "迁移 4 个已跟踪文件到 web/ 与 docs/\n"
    assert (original / "web/feature/widget.js").read_text() == "window.widget = true;"
    assert (original / "web/index.html").read_text() == '<script src="feature/widget.js"></script>'
    assert (original / "docs/接口规范.md").read_text(encoding="utf-8") == "接口规范"
    assert (original / "docs/APP_CONTRACT.md").read_text(encoding="utf-8") == "应用契约"
    assert "'../../web/index.html'" in (original / "tests/demo/run.cjs").read_text()
    assert git(original, "ls-files", "--", "prototype/v4") == ""
    assert (original / "prototype/v4/local.txt").is_file()


def test_migration_refuses_collision_before_any_move(original):
    collision = original / "web/index.html"
    collision.parent.mkdir()
    collision.write_text("已有入口")
    result = migrate(original)
    assert result.returncode != 0
    assert "迁移目标已存在" in result.stderr
    assert (original / "prototype/v4/index.html").is_file()
    assert not (original / "docs").exists()
    assert collision.read_text() == "已有入口"
    assert git(original, "diff", "--cached", "--name-only") == ""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.check_pr_body import validate


ROOT = Path(__file__).resolve().parents[2]
BODY = "Closes #3\n\n## 摘要\n增加门禁\n## 验证\npytest 通过\n## 截图\n只改流程"
IMAGES = "\n![1440px](wide.png)\n![1280px](compact.png)"


@pytest.mark.parametrize("ref", ["Refs #18", "Closes #3"])
def test_empty_diff(ref):
    assert validate(BODY.replace("Closes #3", ref), []) == []


@pytest.mark.parametrize("path", ["web/index.html", "apps/policy/web/app.js", "prototype/v4/assets/demo.js"])
def test_ui_requires_distinct_images(path):
    for images in ("", IMAGES.splitlines()[1], IMAGES.replace("compact.png", "wide.png")):
        assert validate(BODY + images, [path])
    assert validate(BODY + IMAGES, [path]) == []


@pytest.mark.parametrize("reference", ["", "Refs #n", "<!-- Closes #3 -->", "```\nCloses #3\n```"])
def test_requires_visible_reference(reference):
    assert validate(BODY.replace("Closes #3", reference), ["docs/readme.md"])


@pytest.mark.parametrize("content", ["增加门禁", "pytest 通过", "只改流程"])
def test_empty_section(content):
    assert validate(BODY.replace(content, "<!-- 请填写 -->"), [])


def test_template_contract():
    body = (ROOT / ".github/PULL_REQUEST_TEMPLATE.md").read_text()
    assert len(validate(body, [])) == 4
    for section in ("摘要", "验证", "截图"):
        body = body.replace(f"## {section}", f"## {section}\n已核对")
    assert not validate("Refs #3\n" + body, [])


def test_event_cli_uses_full_diff_including_deleted_ui(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    ui = tmp_path / "web/index.html"
    ui.parent.mkdir()
    ui.write_text("page")
    git("add", ".")
    def commit():
        git("-c", "user.name=test", "-c", "user.email=test@example.org", "commit", "-qam", "测试")
        return git("rev-parse", "HEAD")

    base = commit()
    ui.unlink()
    head = commit()
    event = tmp_path / "event.json"
    for body, expected in [(BODY, 1), (BODY + IMAGES, 0)]:
        event.write_text(json.dumps({"pull_request": {"body": body, "base": {"sha": base}, "head": {"sha": head}}}))
        result = subprocess.run([sys.executable, ROOT / "scripts/check_pr_body.py"], cwd=tmp_path,
                                env={**os.environ, "GITHUB_EVENT_PATH": str(event)}, capture_output=True)
        assert result.returncode == expected, result.stderr

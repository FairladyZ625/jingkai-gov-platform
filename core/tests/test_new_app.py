"""Issue #17 验收样本：一条命令生成应用，用示例账号跑通保存 → 提交 → 确认 → 导出。"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from conftest import ROOT

SCRIPT = ROOT / "scripts" / "new_app.py"
APP = "acceptance-app"
BASE = f"/api/apps/{APP}"
PROJECT = "sample-project"


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "apps" / "_template", root / "apps" / "_template")
    (root / "CODEOWNERS").write_text("/core/ @maintainer\n", encoding="utf-8")
    return root


def _new_app(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--root", str(root)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_new_app_replaces_placeholders_and_registers_codeowner(tmp_path):
    root = _root(tmp_path)
    result = _new_app(root, APP, "验收样本", "--owner", "tester", "--issue", "17")
    assert result.returncode == 0, result.stderr

    app = root / "apps" / APP
    manifest = json.loads((app / "app.json").read_text(encoding="utf-8"))
    assert (manifest["id"], manifest["name"], manifest["owner"]) == (APP, "验收样本", "tester")
    assert manifest["sdk"] == "2"
    readme = (app / "README.md").read_text(encoding="utf-8")
    assert "#17" in readme and "tester" in readme
    assert "../../core/README.md#启动" in readme
    assert "scripts/dev.sh" not in readme
    assert f"/apps/{APP}/ @tester" in (root / "CODEOWNERS").read_text(encoding="utf-8")
    for path in app.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".py", ".js", ".md"}:
            assert "__APP_ID__" not in path.read_text(encoding="utf-8")


def test_duplicate_id_is_refused(tmp_path):
    root = _root(tmp_path)
    assert _new_app(root, APP, "验收样本", "--owner", "tester", "--issue", "17").returncode == 0
    again = _new_app(root, APP, "验收样本", "--owner", "tester", "--issue", "17")
    assert again.returncode == 2
    assert "已存在" in again.stderr


def test_invalid_owner_is_refused(tmp_path):
    root = _root(tmp_path)
    result = _new_app(root, APP, "验收样本", "--owner", "bad owner", "--issue", "17")
    assert result.returncode == 2
    assert "GitLab 用户名" in result.stderr


def test_generated_app_runs_full_flow(tmp_path, make_client):
    root = _root(tmp_path)
    assert _new_app(root, APP, "验收样本", "--owner", "tester", "--issue", "17").returncode == 0

    client = make_client(root / "apps")
    assert client.post("/api/auth/login", json={"user_id": "sampleoperator"}).status_code == 200
    created = client.post(f"{BASE}/records", json={"project": PROJECT, "title": "验收记录", "content": "示例"})
    assert created.status_code == 201
    record = created.json()
    assert (record["status"], record["version"]) == ("draft", 1)

    review = client.post(f"{BASE}/records/{record['id']}/submit", json={})
    assert review.status_code == 201
    assert review.json()["status"] == "pending"

    assert client.post("/api/auth/login", json={"user_id": "samplereviewer"}).status_code == 200
    todo = client.get(f"{BASE}/reviews").json()["todo"]
    assert [item["id"] for item in todo] == [review.json()["id"]]
    done = client.post(
        f"{BASE}/reviews/{review.json()['id']}/decisions",
        json={"version": 1, "decision": "confirm"},
    )
    assert done.status_code == 200
    assert done.json()["status"] == "confirmed"

    exported = client.get(f"{BASE}/records/{record['id']}/export")
    assert exported.status_code == 200
    assert "验收记录" in exported.text and "确认人" in exported.text

    assert client.post("/api/auth/login", json={"user_id": "sampleobserver"}).status_code == 200
    denied = client.post(f"{BASE}/records", json={"project": PROJECT, "title": "观察员不能写"})
    assert denied.status_code == 403

    assert client.post("/api/auth/login", json={"user_id": "sampleadmin"}).status_code == 200
    actions = [item["action"] for item in client.get(f"/api/audit?app_id={APP}").json()["items"]]
    assert {"create", "submit", "confirm", "export"} <= set(actions)


def test_check_generated_app_exercises_its_own_router(tmp_path):
    root = _root(tmp_path)
    assert _new_app(root, APP, "验收样本", "--owner", "tester").returncode == 0
    for path in ("conftest.py", "pytest.ini", "scripts/check.py"):
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, destination)
    for path in ("core/server", "core/sdk", "tests/fixtures"):
        shutil.copytree(ROOT / path, root / path, ignore=shutil.ignore_patterns("__pycache__"))

    def check():
        return subprocess.run(
            [sys.executable, "scripts/check.py", "--only", "tests", "--app", APP],
            cwd=root, capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    router = root / "apps" / APP / "api/router.py"
    original = router.read_text(encoding="utf-8")
    router.write_text(original.replace('post("/records", status_code=201)', 'post("/records", status_code=202)'),
                      encoding="utf-8")
    failed = check()
    assert failed.returncode == 1 and "assert 202 == 201" in failed.stdout, failed.stdout + failed.stderr

    router.write_text(original, encoding="utf-8")
    repaired = check()
    assert repaired.returncode == 0, repaired.stdout + repaired.stderr


def test_name_with_quotes_and_backslash_stays_valid(tmp_path):
    """O'Brien 这类名称要能生成；按目标文件语法转义，不能靠拒绝合法名字。"""
    root = _root(tmp_path)
    name = 'O\'Brien "A\\B" 记录'
    result = _new_app(root, APP, name, "--owner", "tester", "--issue", "17")
    assert result.returncode == 0, result.stderr

    app = root / "apps" / APP
    assert json.loads((app / "app.json").read_text(encoding="utf-8"))["name"] == name
    js = (app / "web/index.js").read_text(encoding="utf-8")
    assert r'''O\'Brien \"A\\B\" 记录''' in js
    node = shutil.which("node")
    if node:
        checked = subprocess.run(
            [node, "--input-type=module", "--check"], input=js, text=True, capture_output=True
        )
        assert checked.returncode == 0, checked.stderr
    compiled = subprocess.run(
        [sys.executable, "-m", "py_compile", str(app / "api" / "router.py")],
        capture_output=True,
        text=True,
    )
    assert compiled.returncode == 0, compiled.stderr


def test_control_char_in_name_is_refused(tmp_path):
    root = _root(tmp_path)
    result = _new_app(root, APP, "Tab\tName", "--owner", "tester", "--issue", "17")
    assert result.returncode == 2
    assert "控制字符" in result.stderr
    assert not (root / "apps" / APP).exists()


def test_two_generated_apps_collect_without_import_file_mismatch(tmp_path):
    """模板测试与 sample-app 同名；两个生成应用全量收集不能互相覆盖模块。"""
    root = _root(tmp_path)
    for app_id in ("import-one", "import-two"):
        assert _new_app(root, app_id, "同名测试收集", "--owner", "tester", "--issue", "17").returncode == 0
    shutil.copy(ROOT / "pytest.ini", root / "pytest.ini")

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "apps"],
        cwd=root,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(ROOT / "core" / "server"), str(ROOT / "core" / "sdk")]),
        },
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "import file mismatch" not in output
    for app_id in ("_template", "import-one", "import-two"):
        assert f"apps/{app_id}/tests/test_permissions.py::" in output


def test_generated_frontend_filters_empty_cards(tmp_path):
    """空待办/空提交卡片返回 null；直接 el.append(null) 会把 null 当文本渲染。"""
    root = _root(tmp_path)
    assert _new_app(root, APP, "验收样本", "--owner", "tester", "--issue", "17").returncode == 0
    js = (root / "apps" / APP / "web" / "index.js").read_text(encoding="utf-8")
    assert "installMockFromQuery" in js
    assert "const cards = [" in js
    assert "el.append(...cards.filter(Boolean));" in js

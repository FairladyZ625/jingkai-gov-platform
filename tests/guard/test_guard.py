"""使用临时 Git 仓库验证真正的 pre-commit，不改开发者的索引或配置。"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES = json.loads((ROOT / "scripts/guard_rules.json").read_text(encoding="utf-8"))


class GuardTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name)
        for name in ("scripts", ".githooks"):
            shutil.copytree(ROOT / name, self.repo / name)
        shutil.copy(ROOT / ".gitignore", self.repo)
        self.run_git("init", "-q")
        self.run_git("config", "core.hooksPath", ".githooks")
        self.run_git("add", ".")
        self.commit()

    def run_git(self, *args, check=True):
        return subprocess.run(["git", *args], cwd=self.repo, check=check,
                              capture_output=True, text=True, encoding="utf-8")

    def commit(self, check=True):
        return self.run_git("-c", "user.name=Guard Test", "-c", "user.email=test@example.org",
                            "-c", "commit.gpgsign=false", "commit", "-qm", "检查样本", check=check)

    def stage(self, name, content):
        path = self.repo / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(content, encoding="utf-8")
        self.run_git("add", "-f", "--", name)
        return path

    def assert_blocked(self, location):
        before = self.run_git("rev-parse", "HEAD").stdout
        result = self.commit(check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn(location, result.stderr)
        self.assertEqual(self.run_git("rev-parse", "HEAD").stdout, before)
        return result.stderr

    def test_keyword_in_staged_version(self):
        path = self.stage("说明.md", "公开说明\n" + RULES["keywords"][0])
        path.write_text("工作区已修正", encoding="utf-8")
        output = self.assert_blocked("说明.md:2：商务敏感词")
        print(output.strip())

    def test_force_added_env(self):
        self.stage(".env", "TEST_ONLY=1")
        print(self.assert_blocked(".env：受限路径").strip())

    def test_private_paths(self):
        for name in ("data/private/a.txt", "sub/00_内部资料样例/a.md", "sub/a.key", "a.WAV"):
            with self.subTest(name=name):
                self.stage(name, "test")
                self.assert_blocked(name)
                self.run_git("rm", "--cached", "--", name)

    def test_credentials_report_only_location(self):
        for value in ("sk-" + "x" * 20, "AKIA" + "X" * 16, "-----BEGIN " + "PRIVATE KEY-----"):
            with self.subTest():
                self.stage("test.txt", "test\n" + value)
                self.assertNotIn(value, self.assert_blocked("test.txt:2：疑似凭据"))

    def test_public_text_still_checked(self):
        name, phrases = next(iter(RULES["public_phrases"].items()))
        self.stage(name, phrases[0])
        self.commit()
        self.stage(name, phrases[0] + RULES["keywords"][0])
        self.assert_blocked(name + ":1：商务敏感词")

    def test_ci_entry_reads_index(self):
        self.stage("normal.md", "公开文档")
        result = subprocess.run([sys.executable, "scripts/guard.py"], cwd=self.repo,
                                check=True, capture_output=True, text=True, encoding="utf-8")
        self.assertIn("发现 0 项问题", result.stdout)

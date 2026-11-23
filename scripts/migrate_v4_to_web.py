#!/usr/bin/env python3
"""在包含 v4 的主线检出中重放目录搬迁，保留原型文件内容。"""
from pathlib import Path
import os
import subprocess
import sys


DOCS = {"接口规范.md", "APP_CONTRACT.md"}
PATH_UPDATES = {
    ".github/workflows/ci.yml": ("prototype/v4/", "web/"),
    "web/mock/build_mock.py": ("prototype/v4/", "web/"),
    "web/config/mock-data.js": ("由 prototype/v4/mock/build_mock.py 生成", "由 web/mock/build_mock.py 生成"),
    "scripts/guard_rules.json": ('"prototype/v4/', '"web/'),
    "scripts/data/build_real_supplement.py": ("prototype/v4/data/", "web/data/"),
    "scripts/gen-plan-data.sh": ("prototype/v4/plan-data", "web/plan-data"),
    "scripts/gen_plan_data.py": ("prototype/v4/plan-data", "web/plan-data"),
    "tests/data/real-supplement.test.cjs": ("prototype/v4/data", "web/data"),
    "tests/demo/README.md": ("prototype/v4/index.html", "web/index.html"),
    "tests/demo/run.cjs": ("prototype/v4/index.html", "web/index.html"),
    "tests/demo-data/policy/contract.test.cjs": ("prototype/v4/", "web/"),
    "tests/demo-data/workspace/browser.cjs": ("prototype/v4/index.html", "web/index.html"),
    "tests/demo-data/workspace/check.cjs": ("'prototype/v4'", "'web'"),
    "tests/p0/panels.spec.js": ("prototype/v4/index.html", "web/index.html"),
}


def git(*args):
    return subprocess.check_output(["git", *args])


def replace(path, old, new):
    if path.is_file():
        content = path.read_bytes()
        updated = content.replace(old.encode(), new.encode())
        if updated != content:
            path.write_bytes(updated)


def main():
    os.chdir(os.fsdecode(git("rev-parse", "--show-toplevel").rstrip(b"\n")))
    source = Path("prototype/v4")
    tracked = [Path(os.fsdecode(name)) for name in
               git("ls-files", "-z", "--", source).split(b"\0") if name]
    if not tracked or not (source / "index.html").is_file():
        sys.exit("当前检出缺少待搬迁的 v4 原型")
    if git("diff", "--name-only", "--", source) or git("diff", "--cached", "--name-only", "--", source):
        sys.exit("请先处理原型目录的未提交改动，再运行搬迁")
    moves = []
    for path in tracked:
        relative = path.relative_to(source)
        target = Path("docs" if str(relative) in DOCS else "web") / relative
        if target.exists() or target.is_symlink():
            sys.exit(f"迁移目标已存在：{target}")
        for parent in target.parents:
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                sys.exit(f"迁移目标的父目录不可用：{parent}")
        if not path.is_file():
            sys.exit(f"待迁文件不可用：{path}")
        moves.append((path, target))
    for path, target in moves:
        target.parent.mkdir(parents=True, exist_ok=True)
        git("mv", "--", path, target)
    old_dirs = {parent for path in tracked for parent in path.parents
                if parent == source or source in parent.parents}
    for directory in sorted(old_dirs, key=lambda path: len(path.parts), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    for name, (old, new) in PATH_UPDATES.items():
        replace(Path(name), old, new)
    replace(Path("scripts/gen_plan_data.py"), "ROOT / 'prototype' / 'v4'", "ROOT / 'web'")
    replace(Path("web/mock/build_mock.py"), "resolve().parents[3]", "resolve().parents[2]")
    print(f"迁移 {len(moves)} 个已跟踪文件到 web/ 与 docs/")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""检查 Git 暂存快照。本地提交和 CI 共用入口，只输出位置与类别。"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

RULES = "scripts/guard_rules.json"
SECRET = re.compile(r"sk-[A-Za-z0-9_-]{16,}|AK[A-Z0-9]{14,}|AKID[A-Za-z0-9]{12,}|LTAI[A-Za-z0-9]{12,}|-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
BLOCKED_SUFFIXES = {".key", ".pem", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".amr"}


def git(*args):
    return subprocess.check_output(["git", *args])


def forbidden(path):
    return (any(p.startswith(("00_内部资料", ".env")) for p in path.parts)
            or path.parts[:2] == ("data", "private")
            or path.suffix.lower() in BLOCKED_SUFFIXES)


def scan():
    os.chdir(Path(os.fsdecode(git("rev-parse", "--show-toplevel").rstrip(b"\n"))))
    rules = json.loads(git("show", ":" + RULES))
    checked = issues = 0
    for record in git("ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        meta, name = record.split(b"\t", 1)
        mode, oid, stage = meta.split()
        path = PurePosixPath(os.fsdecode(name))
        checked += 1
        if forbidden(path):
            print(f"{path}：受限路径")
            issues += 1
            continue
        if stage != b"0":
            print(f"{path}：暂存区存在未解决的冲突")
            issues += 1
            continue
        if mode == b"160000":  # 子模块在索引中只保存提交编号
            continue
        blob = git("cat-file", "blob", oid)
        if blob.startswith((b"\xff\xfe", b"\xfe\xff")):
            content = blob.decode("utf-16")
        elif b"\0" in blob:
            continue
        else:
            content = blob.decode("utf-8", errors="surrogateescape")
        for number, line in enumerate(content.splitlines(), 1):
            if SECRET.search(line):
                print(f"{path}:{number}：疑似凭据")
                issues += 1
            if str(path) == RULES:
                continue
            for phrase in rules["public_phrases"].get(str(path), []):
                line = line.replace(phrase, "")
            if any(word in line for word in rules["keywords"]):
                print(f"{path}:{number}：商务敏感词")
                issues += 1
    print(f"检查暂存快照 {checked} 项，发现 {issues} 项问题。")
    return int(bool(issues))


if __name__ == "__main__":
    sys.exit(scan())

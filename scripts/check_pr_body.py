"""校验 GitHub PR 事件正文，按 PR 的实际 Git 差异判断截图要求。"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def validate(body, paths):
    visible = re.sub(r"<!--.*?(?:-->|$)", "", body, flags=re.S)
    errors = []
    # 代码块可以承载验证输出，但不能代替关联指令或截图。
    prose = re.sub(r"(?ms)^(?:```|~~~).*?^(?:```|~~~)[^\n]*$", "【代码块】", visible)
    if not re.search(r"(?im)^\s*(?:Refs|Closes)[ \t]+#[1-9]\d*\s*$", prose):
        errors.append("请单独一行填写 Refs #编号 或 Closes #编号。")
    parts = re.split(r"(?m)^##[ \t]+([^\n]+)$", prose)
    sections = {title.strip(): content.strip() for title, content in zip(parts[1::2], parts[2::2])}
    for title in ("摘要", "验证", "截图"):
        if not sections.get(title):
            errors.append(f"请填写「{title}」一节。")
    if any(re.match(r"^(?:prototype/v4|web|apps/[^/]+/web)/", path) for path in paths):
        images = re.findall(r"!\[([^\]]*)\]\(([^\s)]+)\)", sections.get("截图", ""))
        candidates = []
        for width in ("1440", "1280"):
            urls = {url for label, url in images if re.search(rf"(?<!\d){width}(?!\d)", label)}
            candidates.append(urls)
            if not urls:
                errors.append(f"请在截图节附上独立的 {width}px Markdown 图片。")
        if all(candidates) and len(set.union(*candidates)) < 2:
            errors.append("两个宽度需要分别链接到对应的图片。")
    return errors


def main():
    pr = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())["pull_request"]
    diff = subprocess.check_output([
        "git", "diff", "--name-only", "--no-renames", "-z",
        f"{pr['base']['sha']}...{pr['head']['sha']}", "--",
    ])
    errors = validate(pr["body"] or "", os.fsdecode(diff).split("\0"))
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print("PR 正文检查通过")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())

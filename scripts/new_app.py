#!/usr/bin/env python3
"""从模板新建应用：python scripts/new_app.py <id> "<名称>" --owner <人> [--issue <iid>]

生成后直接是一个能跑的最小应用：保存 → 提交确认 → 导出，并带三类测试。
会自动在 CODEOWNERS 登记 /apps/<id>/，所以新应用第一次跑 check 就过 CHK-APP-06。
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".json", ".py", ".js", ".md", ".html", ".css", ".txt", ".yaml", ".yml"}
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")


def _text(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{label}不能为空")
    if any(ord(ch) < 0x20 or 0x7f <= ord(ch) <= 0x9f for ch in value):
        raise ValueError(f"{label}不能包含换行、制表符等控制字符")
    return value


def _js_string(value: str) -> str:
    """放进单引号 JS 字符串；引号、反斜杠、行分隔符逐字符转义。"""
    out = []
    for ch in value:
        code = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == "'":
            out.append("\\'")
        elif ch == '"':
            out.append('\\"')
        elif ch in ("\n", "\r", "\t"):
            out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
        elif code < 0x20 or code == 0x7f or code in (0x2028, 0x2029):
            out.append(f"\\u{code:04x}")
        else:
            out.append(ch)
    return "".join(out)


def _escaped(value: str, suffix: str) -> str:
    """按目标文件语法转义：JSON / Python 字符串用 json.dumps，JS 用单引号安全转义。"""
    if suffix in {".json", ".py"}:
        return json.dumps(value, ensure_ascii=False)[1:-1]
    if suffix == ".js":
        return _js_string(value)
    return value


def _write_codeowners(root: Path, app_id: str, owner: str) -> bool:
    """登记 /apps/<id>/；返回是否写入。CODEOWNERS 不存在时保持原样，由 check 提示。"""
    path = root / "CODEOWNERS"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    pattern = f"/apps/{app_id}/"
    if any(line.split("#", 1)[0].strip().startswith(pattern) for line in text.splitlines()):
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(f"{text}{pattern} @{owner}\n", encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("name")
    ap.add_argument("--owner", required=True, help="GitLab 用户名，写入 app.json 和 CODEOWNERS")
    ap.add_argument("--issue", default="", help="关联 Issue 编号，只写数字")
    ap.add_argument("--root", default=str(ROOT), help="目标仓库根，默认当前仓库")
    a = ap.parse_args()

    root = Path(a.root).resolve()
    if not ID_RE.match(a.id):
        print("id 只能是小写字母、数字、连字符，字母开头，2–40 位", file=sys.stderr)
        return 2
    try:
        name = _text(a.name, "名称")
        owner = _text(a.owner.lstrip("@"), "负责人")
        issue = _text(a.issue.lstrip("#"), "Issue 编号") if a.issue.strip() else "<iid>"
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    if not re.match(r"^[A-Za-z0-9_.-]+$", owner):
        print("负责人只填 GitLab 用户名（字母、数字、下划线、点、连字符），不要带 @ 或空格", file=sys.stderr)
        return 2

    template = root / "apps" / "_template"
    if not template.is_dir():
        print(f"{template} 不存在，--root 要指向 haiknow-app-platform 仓库根", file=sys.stderr)
        return 2
    dst = root / "apps" / a.id
    if dst.exists():
        print(f"{dst} 已存在", file=sys.stderr)
        return 2

    shutil.copytree(
        template,
        dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )
    replacements = {"__APP_ID__": a.id, "__APP_NAME__": name, "__OWNER__": owner, "__ISSUE__": issue}
    for path in dst.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        for key, value in replacements.items():
            text = text.replace(key, _escaped(value, path.suffix))
        path.write_text(text, encoding="utf-8")

    registered = _write_codeowners(root, a.id, owner)
    print(f"已创建 apps/{a.id}")
    if registered:
        print(f"CODEOWNERS 已登记 {a.id} 的负责人 @{owner}")
    else:
        print(f"没有新建 CODEOWNERS 行：确认已有 /apps/{a.id}/ @{owner}，否则 check 会报 CHK-APP-06")
    print(
        "下一步：\n"
        f"  1. 改 apps/{a.id}/README.md 的需求七问，以及 app.json 的 sector / scenes / summary\n"
        f"  2. python scripts/check.py --app {a.id}\n"
        "  3. 按 core/README.md 启动，用办理角色新建并提交，切换审核角色确认后导出"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
#!/usr/bin/env python3
"""统一质量门。本地和 CI 跑同一条命令：python scripts/check.py

  --only manifest,readme,boundary,errors,size,owners,secrets,ledger,docs,tests   只跑部分检查
  --app <id>                                                              只检查一个应用（tests 也只跑它）
退出码非 0 表示不能合入。失败行格式：文件:行 [CHK-XXX-NN] 问题 → 改法。
规则目录见 docs/specs/检查规则.md。
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import MutableMapping
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "core" / "server"), str(ROOT / "core" / "sdk")]

from haiknow_core import manifest as mf  # noqa: E402

# 本机开着代理时，测试内起的 HTTP/WS 服务只监听回环，不该走代理。
LOOPBACK_NO_PROXY = ("127.0.0.1", "localhost", "::1")


def ensure_loopback_no_proxy(env: MutableMapping[str, str]) -> MutableMapping[str, str]:
    """把回环地址追加进 NO_PROXY 与 no_proxy，保留用户已有值；已含 * 时不再追加。"""
    for key in ("NO_PROXY", "no_proxy"):
        entries = [e for e in re.split(r"[,\s]+", env.get(key, "")) if e]
        if "*" in entries:
            continue
        entries.extend(host for host in LOOPBACK_NO_PROXY if host not in entries)
        env[key] = ",".join(entries)
    return env


def _test_env(**extra: str) -> dict[str, str]:
    """测试子进程的环境：宿主 env 加上回环 NO_PROXY，再叠加调用方变量。"""
    return dict(ensure_loopback_no_proxy({**os.environ, **extra}))


SKIP_DIRS = {".git", ".venv", "data", "harness", ".harness", "node_modules", ".cache", "__pycache__", ".pytest_cache", ".worktrees", ".local"}
SEVEN = ["触发", "使用者与确认人", "输入", "处理步骤", "确认依据", "输出", "验收样本"]
PY_ALLOWED_3P = {"fastapi", "pydantic", "starlette", "haiknow_sdk"}
PY_FORBIDDEN = {"sqlite3", "subprocess", "socket", "ctypes", "multiprocessing", "haiknow_core", "haiknow_apps"}
MAX_APP_FILE = 2 * 1024 * 1024
# style= 内联样式的唯一白名单：相对仓库根的路径 → 理由。由底座评审后登记，应用不能自己豁免。
STYLE_ALLOWED: dict[str, str] = {}
# 应用前端界面规范门（CHK-APP-15…17）。豁免只放平台侧文件，应用目录里没有豁免入口。
UI_RULES = ("CHK-APP-15", "CHK-APP-16", "CHK-APP-17")
UI_EXEMPTIONS = Path("scripts/ui_exemptions.json")
UI_UI_CSS = Path("core/sdk/js/ui/ui.css")
UI_TOKENS_CSS = Path("core/web/tokens.css")
UI_SHELL_CSS = Path("core/web/style.css")
# 外壳 style.css 里“存量 SDK1 兼容块”之后不是新应用可用类名；标记由 style.css 自己维护。
UI_PUBLIC_SHELL_MARKER = "@hk-public-styles-end"
UI_COMPONENTS = {
    "ThemeSwitch", "Button", "StatusTag", "TaskStatus", "Input", "DateInput", "Select", "Textarea",
    "Checkbox", "FileUpload", "FormField", "Form", "Table", "Card", "MetricGrid", "Notice", "StepStrip",
    "Tabs", "PageHeader", "WorkbenchLayout", "StateView", "EmptyState", "LoadingState", "ErrorState",
    "ForbiddenState", "Toast",
}
# 《视觉与界面规范》§4.1：五个固定业务状态词，顺序与 ui/index.js 的 BUSINESS_STATUSES 一致。
UI_BUSINESS_STATUSES = ("草稿", "待补充", "待确认", "已确认", "需重新核对")
# 直接作为状态标签传给 StatusTag/badge 时明确违规的词；映射表里的值另按五词白名单逐个比对。
UI_STATUS_VIOLATIONS = {
    "待审核", "审核中", "已审核", "已完结", "处理完毕", "待复审", "已导出", "已提交", "已完成", "运行中",
}
UI_STATUS_CALLS = ("StatusTag", "badge")
UI_CLASS_TOKEN = re.compile(r"(?<![\w-])(hk-[a-z][A-Za-z0-9_-]*)")
JS_STRING = re.compile(r"""(['"])((?:\\.|(?!\1).)*)\1""", re.S)
JS_NAMED_IMPORT = re.compile(r"""import\s+(?:\w+\s*,\s*)?\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]""", re.S)
JS_UI_STAR_IMPORT = re.compile(r"""import\s+\*\s+as\s+\w+\s+from\s*['"]/sdk/ui/index\.js['"]""")
SECRET_RES = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"),
]
JS_IMPORT = re.compile(r"""(?:import\s[^'"]*?from\s*|import\s*\(\s*|import\s+|export\s[^'"]*?from\s*)['"]([^'"]+)['"]""")
FETCH = re.compile(r"""\bfetch\s*\(\s*(['"`])([^'"`\n]*)\1""")
HEX_COLOR = re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9a-fA-F])")
COLOR_FN = re.compile(r"\b(?:rgb|rgba|hsl|hsla)\s*\(")
STYLE_ATTR = re.compile(r"""\bstyle\s*=\s*["']""")
STYLE_PROP = re.compile(r"""(?<![\w-])style\s*:\s*['"`]""")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

# 规则编号 → 默认改法。docs/specs/检查规则.md 必须逐条覆盖，测试会比对两边。
RULES = {
    "CHK-APP-01": "用 python scripts/new_app.py <id> \"<名称>\" --owner <人> 从模板生成，或补清单",
    "CHK-APP-02": "按报错行修逗号、引号；可用 python -m json.tool apps/<id>/app.json 自检",
    "CHK-APP-03": "按 docs/specs/应用接入规范.md 补齐 contract/sdk/id/name/sector/kind/owner/status",
    "CHK-APP-04": "按 docs/specs/应用接入规范.md 改成允许值；embed 型必须写 url",
    "CHK-APP-05": "新建 web/index.js 并导出 async mount(el, ctx)，或把 kind 改成 embed 并写 url",
    "CHK-APP-06": "在 CODEOWNERS 加 /apps/<id>/ @<owner>，与 app.json 的 owner 保持一致",
    "CHK-APP-07": "按 apps/_template/README.md 补需求七问",
    "CHK-APP-08": "补 ### N. <名称> 小节，需求七问七个都要有",
    "CHK-APP-09": "填写该节；没想清楚就把 app.json 的 status 改回 idea",
    "CHK-APP-10": "平台能力只经 haiknow_sdk；数据库、进程、网络和平台内部模块都不许应用直连",
    "CHK-APP-11": "在 Issue 里提依赖由底座评估，或改用 SDK / 标准库",
    "CHK-APP-12": "配置走平台（如 ctx.model）；需要新配置在 Issue 提给底座，不读环境变量",
    "CHK-APP-13": "修语法错误；可用 python -m py_compile apps/<id>/api/router.py 自检",
    "CHK-APP-14": "平台能力只经 haiknow_sdk 的公开方法；删除 SDK 句柄私有属性访问（含 getattr 的静态私有名）",
    "CHK-APP-15": "从 /sdk/ui/index.js 导入 PageHeader/WorkbenchLayout/Card/Form/Table/StatusTag/EmptyState/ForbiddenState 等组件；见 docs/specs/视觉与界面规范.md §1.4",
    "CHK-APP-16": "状态标签走 StatusTag({ status })；状态词只用 草稿/待补充/待确认/已确认/需重新核对；见 docs/specs/视觉与界面规范.md §4.1",
    "CHK-APP-17": "改用 /sdk/ui/index.js 的组件与 core/sdk/js/ui/ui.css 里已有的类；见 docs/specs/视觉与界面规范.md §1.4",
    "CHK-WEB-01": "只 import /sdk/... 或本应用 web/ 内的相对路径；新组件提给底座加到 SDK",
    "CHK-WEB-02": "把文件放进本应用 web/，或改用 /sdk/ 组件",
    "CHK-WEB-03": "改用 ctx.api() / ctx.upload()，SDK 会自动加 /api/apps/<id> 前缀",
    "CHK-WEB-04": "改用 var(--hk-*) 设计令牌，应用不自造色值",
    "CHK-WEB-05": "用 SDK 组件的 class；确需动态样式时由底座在 STYLE_ALLOWED 登记",
    "CHK-ERR-01": "界面文案不拼错误码；错误一律经 errorMessage(err) 或 ctx.preview.errors.message(err) 转成中文再展示",
    "CHK-ERR-02": "不直接展示 err.message；改用 ctx.preview.errors.message(err)（平台页面用 errorMessage(err)）",
    "CHK-ERR-03": "在 apps/<id>/web/errors.json 登记 {\"码\": \"中文提示\"}；键用大写 SNAKE_CASE，不得与平台码重名，值必须是中文",
    "CHK-ERR-04": "在 core/sdk/js/preview/errors.js 的 PLATFORM_ERROR_MESSAGES 补齐该码的中文提示，并保持与 prototype/v4/接口规范.md 一致",
    "CHK-TEST-01": "新建 apps/<id>/tests/test_*.py，至少覆盖一条完整流程",
    "CHK-TEST-02": "加一条断言 403 或 PermissionDenied 的无权限用例",
    "CHK-TEST-03": "按失败用例修；本地用 python scripts/check.py --app <id> 复现",
    "CHK-REPO-01": "删除或压缩；样例只放小的脱敏文件，大文件进平台文件存储",
    "CHK-REPO-02": "按 CODEOWNERS @ 对应负责人评审；审批由 GitLab 执行",
    "CHK-REPO-03": "删除并轮换密钥；密钥只放 .env 或平台配置，不入库",
    "CHK-REPO-04": "删除 .env；.env.example 只留字段名",
    "CHK-REPO-05": "git rm --cached 台账文件；harness/ 只留本机",
    "CHK-REPO-06": "修链接或补文件",
    "CHK-REPO-07": "补 README.md 并在 docs/README.md 索引里加一行",
}


def files() -> list[Path]:
    if shutil.which("git") and (ROOT / ".git").exists():
        out = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.splitlines()
        return [ROOT / p for p in out if (ROOT / p).is_file()]
    res = []
    for p in ROOT.rglob("*"):
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS):
            res.append(p)
    return res


def app_dirs(only: str | None) -> list[Path]:
    d = ROOT / "apps"
    if not d.is_dir():
        return []
    out = [p for p in sorted(d.iterdir()) if p.is_dir() and not p.name.startswith((".", "_"))]
    return [p for p in out if only is None or p.name == only]


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.notices: list[str] = []

    def rule(self, code: str, where: str, msg: str, line: int | None = None) -> None:
        loc = f"{where}:{line}" if line else where
        self.errors.append(f"{loc} [{code}] {msg} → {RULES[code]}")

    def notice(self, code: str, msg: str) -> None:
        self.notices.append(f"[{code}] {msg} → {RULES[code]}")


def _codeowners() -> list[tuple[str, list[str]]]:
    f = ROOT / "CODEOWNERS"
    out: list[tuple[str, list[str]]] = []
    if not f.is_file():
        return out
    for raw in f.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        out.append((parts[0], parts[1:]))
    return out


def _owner_pattern_matches(pattern: str, path: str) -> bool:
    p = pattern[1:] if pattern.startswith("/") else pattern
    if p.endswith("/"):
        p += "**"
    return fnmatch.fnmatch(path, p)


def codeowners_for(path: str) -> list[str]:
    """CODEOWNERS 后匹配覆盖前匹配，与 GitLab 的规则一致。"""
    owners: list[str] = []
    for pattern, entries in _codeowners():
        if _owner_pattern_matches(pattern, path):
            owners = entries
    return owners


def _registered_owners(app_id: str) -> list[str] | None:
    for pattern, owners in _codeowners():
        if pattern.rstrip("/") == f"/apps/{app_id}".rstrip("/"):
            return owners
    return None


def _status(d: Path) -> str:
    try:
        m = json.loads((d / "app.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "idea"
    return m.get("status", "idea") if isinstance(m, dict) else "idea"


def _key_line(raw: str, key: str) -> int | None:
    """在 app.json 原文里找字段所在行，让报错能指到行。"""
    m = re.search(rf'"{re.escape(key)}"\s*:', raw)
    return line_of(raw, m.start()) if m else None


def _manifest_line(raw: str, msg: str) -> int | None:
    m = re.match(r"(?:缺少字段|字段)\s+([A-Za-z_]+)", msg)
    key = m.group(1) if m else msg.split(".")[0].split(" ")[0]
    return _key_line(raw, key) if key.isidentifier() else None


def check_manifest(r: Report, only: str | None) -> None:
    for d in app_dirs(only):
        f = d / "app.json"
        where = rel(f)
        if not f.is_file():
            r.rule("CHK-APP-01", rel(d), "缺少 app.json")
            continue
        raw = f.read_text(encoding="utf-8")
        try:
            m = json.loads(raw)
        except json.JSONDecodeError as e:
            r.rule("CHK-APP-02", where, f"不是合法 JSON：{e.msg}", line=e.lineno)
            continue
        if not isinstance(m, dict):
            r.rule("CHK-APP-02", where, "顶层必须是 JSON 对象，不能是数组或其他类型")
            continue
        for e in mf.validate(m, d.name):
            code = "CHK-APP-03" if e.startswith("缺少字段") or "类型应为" in e else "CHK-APP-04"
            r.rule(code, where, e, line=_manifest_line(raw, e))
        # 新应用必须声明 SDK 主版本；平台运行时仍把旧应用的缺省值按 "1" 处理。
        if "sdk" not in m:
            r.rule("CHK-APP-03", where, '缺少字段 sdk（新应用写 "sdk": "2"；旧应用由平台按 1 兼容运行）')
        if m.get("kind") == "module" and not (d / "web" / "index.js").is_file():
            r.rule("CHK-APP-05", rel(d / "web"), "module 型应用缺少 web/index.js")
        owner = m.get("owner")
        owner_line = _key_line(raw, "owner")
        if isinstance(owner, str) and not owner.strip():
            r.rule("CHK-APP-03", where, "字段 owner 不能为空（填 GitLab 用户名）", line=owner_line)
        registered = _registered_owners(d.name)
        if registered is None:
            r.rule("CHK-APP-06", where, f"CODEOWNERS 未登记 /apps/{d.name}/，改动找不到评审人", line=owner_line)
        elif isinstance(owner, str) and owner.strip() and f"@{owner.strip()}" not in registered:
            r.rule(
                "CHK-APP-06",
                where,
                f"CODEOWNERS 中 /apps/{d.name}/ 的负责人是 {' '.join(registered)}，与 app.json 的 owner {owner.strip()} 不一致",
                line=owner_line,
            )


def check_readme(r: Report, only: str | None) -> None:
    for d in app_dirs(only):
        f = d / "README.md"
        where = rel(f)
        if not f.is_file():
            r.rule("CHK-APP-07", where, "缺少 README.md（需求七问）")
            continue
        text = f.read_text(encoding="utf-8")
        status = _status(d)
        for i, name in enumerate(SEVEN, 1):
            m = re.search(rf"^###\s*{i}\.\s*{name}\s*$(.*?)(?=^###\s|^##\s|\Z)", text, re.M | re.S)
            if not m:
                r.rule("CHK-APP-08", where, f"缺少七问小节「### {i}. {name}」")
                continue
            body = re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S).strip()
            if not body and status != "idea":
                r.rule("CHK-APP-09", where, f"「{name}」未填写（status 为 idea 以外时七问必须填完）", line=line_of(text, m.start()))


def _py_imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield node.lineno, a.name.split(".")[0], 0
        elif isinstance(node, ast.ImportFrom):
            yield node.lineno, (node.module or "").split(".")[0], node.level


def _check_backend(r: Report, d: Path) -> None:
    stdlib = set(sys.stdlib_module_names)
    api = d / "api"
    for f in sorted(api.rglob("*.py")) if api.is_dir() else []:
        where = rel(f)
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=where)
        except SyntaxError as e:
            r.rule("CHK-APP-13", where, f"语法错误：{e}", line=e.lineno)
            continue
        enterprise_store = f == ROOT / "apps/enterprise/api/ledger_store.py"
        # 仅豁免字面量键的下标读取，赋值、删除及其他环境变量仍报错。
        allowed_env = {
            node.value for node in ast.walk(tree)
            if enterprise_store and isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load)
            and isinstance(node.slice, ast.Constant) and node.slice.value == "JKQ_ENTERPRISE_PRIVATE_DB"
            and isinstance(node.value, ast.Attribute) and node.value.attr == "environ"
            and isinstance(node.value.value, ast.Name) and node.value.value.id == "os"
        }
        for line, mod, level in _py_imports(tree):
            if level > 0:
                continue  # 本应用内相对导入
            if enterprise_store and mod == "sqlite3":
                continue
            if mod in PY_FORBIDDEN:
                r.rule("CHK-APP-10", where, f"禁止 import {mod}（只能通过 haiknow_sdk 使用平台能力）", line=line)
            elif mod not in stdlib and mod not in PY_ALLOWED_3P:
                r.rule("CHK-APP-11", where, f"未登记的依赖 {mod}；需要新依赖先在 Issue 里提，由底座负责人加入白名单", line=line)
        for node in ast.walk(tree):
            env_attribute = isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv", "putenv"}
            env_import = (enterprise_store and isinstance(node, ast.ImportFrom) and node.module == "os"
                          and any(a.name in {"*", "environ", "getenv", "putenv"} for a in node.names))
            if (env_attribute and node not in allowed_env) or env_import:
                r.rule("CHK-APP-12", where, "禁止读写环境变量；配置走平台", line=node.lineno)
            if isinstance(node, ast.Attribute) and node.attr.startswith("_") and not node.attr.startswith("__"):
                r.rule("CHK-APP-14", where, f"禁止访问 SDK 私有属性 {node.attr}（CHK-BOUNDARY）", line=node.lineno)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
                and node.args[1].value.startswith("_")
            ):
                r.rule("CHK-APP-14", where, f"禁止通过 getattr 访问 SDK 私有属性 {node.args[1].value}（CHK-BOUNDARY）", line=node.lineno)


def _check_web(r: Report, d: Path) -> None:
    web = d / "web"
    if not web.is_dir():
        return
    for f in sorted(web.rglob("*")):
        if not f.is_file() or f.suffix not in {".js", ".css", ".html"}:
            continue
        where = rel(f)
        text = f.read_text(encoding="utf-8")
        allow_style = where in STYLE_ALLOWED
        if f.suffix == ".js":
            for m in JS_IMPORT.finditer(text):
                spec = m.group(1)
                line = line_of(text, m.start())
                if spec.startswith("/sdk/"):
                    continue
                if spec.startswith("."):
                    if not (f.parent / spec).resolve().is_relative_to(web.resolve()):
                        r.rule("CHK-WEB-02", where, f"import {spec} 越出本应用 web/ 目录", line=line)
                    continue
                r.rule("CHK-WEB-01", where, f"import {spec} 不允许：只能 import '/sdk/...' 或本应用相对路径", line=line)
            for m in FETCH.finditer(text):
                path = m.group(2)
                if path.startswith("/api/") or path.startswith("/api?"):
                    r.rule("CHK-WEB-03", where, f"直接 fetch 平台接口 {path}；改用 ctx.api()", line=line_of(text, m.start()))
            if not allow_style:
                for m in STYLE_PROP.finditer(text):
                    r.rule("CHK-WEB-05", where, "style 内联样式；改用 SDK 组件的 class", line=line_of(text, m.start()))
        for rx, code, msg in (
            (HEX_COLOR, "CHK-WEB-04", "十六进制颜色字面量"),
            (COLOR_FN, "CHK-WEB-04", "rgb()/rgba()/hsl() 颜色函数"),
        ):
            for m in rx.finditer(text):
                detail = f" {m.group(0)}" if code == "CHK-WEB-04" and rx is HEX_COLOR else ""
                r.rule(code, where, f"{msg}{detail}；只能用 var(--hk-*)", line=line_of(text, m.start()))
        if not allow_style:
            for m in STYLE_ATTR.finditer(text):
                r.rule("CHK-WEB-05", where, "style= 内联样式；改用 SDK 组件的 class", line=line_of(text, m.start()))


def check_boundary(r: Report, only: str | None) -> None:
    for d in app_dirs(only):
        _check_backend(r, d)
        _check_web(r, d)
    check_ui_rules(r, only)


# ---- 错误码中文映射门（CHK-ERR）----
ERR_MESSAGE = re.compile(r"\b(?:err|error|e|ex|exc|cause|reason)\.message\b")
ERR_TEMPLATE_CODE = re.compile(r"`[^`]*\$\{[^}`]*\.code\b[^}`]*\}[^`]*`")
ERR_CONCAT_CODE = re.compile(r"""(?:['"`]\s*\+\s*[\w.?\[\]]*\.code\b|[\w.?\[\]]*\.code\s*\+\s*['"`])""")
ERR_SHOWN_CODE = re.compile(
    r"""(?:\b(?:toast|showToast|setNotice|setStatus|Notice|alert)\s*\([^)\n]*\.code\b[^)\n]*\)"""
    r"""|\b(?:textContent|innerText|message|text|detail)\s*[:=]\s*[\w.?\[\]]*\.code\b(?!\s*[=!]=))"""
)
ERR_BADGE_CODE = re.compile(r"""\bbadge\s*\(\s*[^,()\n]*\.code\s*[,)]""")
ERR_CODE_CMP = re.compile(r"""\.code\s*[=!]==?\s*(['"])([A-Za-z0-9_]+)\1""")
HAN = re.compile(r"[\u4e00-\u9fff]")
CODE_KEY = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*")
PLATFORM_ERRORS_JS = Path("core/sdk/js/preview/errors.js")
PLATFORM_API_DOC = Path("prototype/v4/接口规范.md")


def _blank_js_comments(text: str) -> str:
    """把注释换成空白（保留换行），避免注释里的示例触发误报且行号不偏移。"""
    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))
    text = re.sub(r"/\*.*?\*/", blank, text, flags=re.S)
    return re.sub(r"(?<![:\w'\"`])//[^\n]*", blank, text)


# ---- 应用前端界面规范门（CHK-APP-15…17）----
def _ui_today() -> date:
    """独立出来是为了让豁免到期测试固定日期，不依赖跑测试当天的系统时间。"""
    return date.today()


def _ui_exemptions() -> dict:
    f = ROOT / UI_EXEMPTIONS
    if not f.is_file():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _ui_exemption_active(entry: object, today: date | None = None) -> bool:
    """缺 Issue 号、缺规则或过期都不生效；坏条目按未豁免处理，避免静默放行。"""
    if not isinstance(entry, dict):
        return False
    if not re.fullmatch(r"#\d+", str(entry.get("issue", "")).strip()):
        return False
    rules = entry.get("rules")
    if not isinstance(rules, list) or not rules:
        return False
    try:
        expires = date.fromisoformat(str(entry.get("expires", "")))
    except ValueError:
        return False
    return (today or _ui_today()) <= expires


def _ui_exempt_codes(app_id: str) -> set[str]:
    entry = _ui_exemptions().get(f"apps/{app_id}")
    if not _ui_exemption_active(entry):
        return set()
    return set(entry.get("rules", ())) & set(UI_RULES)


def _css_classes(path: Path) -> set[str]:
    f = ROOT / path
    if not f.is_file():
        return set()
    text = f.read_text(encoding="utf-8")
    if path == UI_SHELL_CSS:
        # 兼容块只服务存量 SDK1 应用；新应用继续用它们就是本次要拦的“凭空类名”。
        text = text.split(UI_PUBLIC_SHELL_MARKER, 1)[0]
    return {m.group(1) for m in re.finditer(r"\.(hk-[A-Za-z0-9_-]+)", text)}


def _ui_defined_classes() -> set[str]:
    return _css_classes(UI_UI_CSS) | _css_classes(UI_TOKENS_CSS) | _css_classes(UI_SHELL_CSS)


def _ui_component_imports(text: str) -> set[str]:
    found: set[str] = set()
    for m in JS_NAMED_IMPORT.finditer(text):
        if m.group(2) != "/sdk/ui/index.js":
            continue
        for part in m.group(1).split(","):
            name = part.strip().split(" as ", 1)[0].strip()
            if name:
                found.add(name)
    if JS_UI_STAR_IMPORT.search(text):
        found.update(UI_COMPONENTS)
    return found


def _js_call_bodies(text: str, name: str):
    for m in re.finditer(rf"\b{re.escape(name)}\s*\(", text):
        start = m.end()
        depth, i = 1, start
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        if depth == 0:
            yield start, text[start:i - 1]


def _js_object_bodies(text: str):
    for m in re.finditer(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\{", text):
        start = m.end()
        depth, i = 1, start
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        if depth == 0:
            yield m.group(1), start, text[start:i - 1]


def _ui_call_status_literals(text: str):
    """StatusTag("待审核") / StatusTag({ status: "待审核" }) / badge("待审核")。"""
    for call in UI_STATUS_CALLS:
        for start, body in _js_call_bodies(text, call):
            m = re.match(r"\s*\{[^{}]*\bstatus\s*:\s*(['\"])((?:\\.|(?!\1).)*)\1", body, re.S)
            if m is None:
                m = re.match(r"\s*(['\"])((?:\\.|(?!\1).)*)\1", body, re.S)
            if m:
                yield m.group(2), start + m.start(2)


def _ui_status_maps(text: str):
    """被 StatusTag/badge 引用的 *STATUS* 映射表；值须是五个固定业务状态词。"""
    referenced: set[str] = set()
    for call in UI_STATUS_CALLS:
        for _, body in _js_call_bodies(text, call):
            referenced.update(re.findall(r"\b([A-Za-z_$][\w$]*)\b", body))
    for name, start, body in _js_object_bodies(text):
        if "status" not in name.lower() or name not in referenced:
            continue
        for m in JS_STRING.finditer(body):
            value = m.group(2)
            if HAN.search(value):
                yield name, value, start + m.start(2)


def _blank_css_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)


def _blank_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)


def _check_ui_status(r: Report, f: Path, raw: str) -> None:
    text = _blank_js_comments(raw)
    where = rel(f)
    for value, pos in _ui_call_status_literals(text):
        if value in UI_STATUS_VIOLATIONS:
            r.rule(
                "CHK-APP-16",
                where,
                f"状态标签「{value}」不是五个固定业务状态（草稿/待补充/待确认/已确认/需重新核对）；状态标签须走 StatusTag（《视觉与界面规范》§4.1）",
                line=line_of(text, pos),
            )
    for name, value, pos in _ui_status_maps(text):
        if value in UI_BUSINESS_STATUSES:
            continue
        r.rule(
            "CHK-APP-16",
            where,
            f"状态映射 {name} 的值「{value}」不在五个固定业务状态（草稿/待补充/待确认/已确认/需重新核对）内；状态标签须走 StatusTag（《视觉与界面规范》§4.1）",
            line=line_of(text, pos),
        )


def _check_ui_app(r: Report, d: Path, defined_classes: set[str]) -> None:
    web = d / "web"
    if not web.is_dir():
        return
    exempt = _ui_exempt_codes(d.name)
    entry = web / "index.js"
    if entry.is_file() and "CHK-APP-15" not in exempt:
        text = _blank_js_comments(entry.read_text(encoding="utf-8"))
        if not (_ui_component_imports(text) & UI_COMPONENTS):
            r.rule(
                "CHK-APP-15",
                rel(entry),
                "应用入口没有从 /sdk/ui/index.js 导入组件；只用 /sdk/haiknow.js 的 h/table/button/badge 手搓页面不算通过（《视觉与界面规范》§1.4）",
                line=1,
            )
    if "CHK-APP-16" not in exempt:
        for f in sorted(web.rglob("*.js")):
            _check_ui_status(r, f, f.read_text(encoding="utf-8"))
    if "CHK-APP-17" not in exempt:
        for f in sorted(web.rglob("*")):
            if not f.is_file() or f.suffix not in {".js", ".css", ".html"}:
                continue
            text = f.read_text(encoding="utf-8")
            if f.suffix == ".js":
                text = _blank_js_comments(text)
            elif f.suffix == ".css":
                text = _blank_css_comments(text)
            else:
                text = _blank_html_comments(text)
            seen: set[str] = set()
            for m in UI_CLASS_TOKEN.finditer(text):
                cls = m.group(1)
                if cls in defined_classes or cls in seen:
                    continue
                seen.add(cls)
                r.rule(
                    "CHK-APP-17",
                    rel(f),
                    f"类名 {cls} 未在 core/sdk/js/ui/ui.css、core/web/tokens.css 或外壳公开样式中定义（存量 SDK1 兼容块不算）；新应用不手写这类凭空类名（《视觉与界面规范》§1.4）",
                    line=line_of(text, m.start()),
                )


def check_ui_rules(r: Report, only: str | None) -> None:
    defined = _ui_defined_classes()
    for d in app_dirs(only):
        _check_ui_app(r, d, defined)


def _error_state_code_calls(text: str):
    """ErrorState({ ... code: ... }) —— 冻结组件会把 code 渲染成「错误码：xxx」，调用方不许传。"""
    for m in re.finditer(r"\bErrorState\s*\(", text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        body = text[m.end():i]
        km = re.search(r"(?<![\w.])code\s*:", body)
        if km:
            yield m.end() + km.start()


def _err_json_registry(r: Report, d: Path) -> dict[str, str] | None:
    f = d / "web" / "errors.json"
    if not f.is_file():
        return {}
    where = rel(f)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        r.rule("CHK-ERR-03", where, f"errors.json 不是合法 JSON：{e.msg}", line=e.lineno)
        return None
    if not isinstance(data, dict):
        r.rule("CHK-ERR-03", where, "errors.json 顶层必须是 {码: 中文提示} 对象")
        return None
    return data


def _platform_error_table() -> dict[str, str] | None:
    f = ROOT / PLATFORM_ERRORS_JS
    if not f.is_file():
        return None
    text = f.read_text(encoding="utf-8")
    m = re.search(r"export const PLATFORM_ERROR_MESSAGES = \{(.*?)^\};", text, re.S | re.M)
    if not m:
        return None
    return {k: v for k, v in re.findall(r"^\s+([a-z][a-z0-9_]*):\s*'([^'\n]*)',?\s*$", m.group(1), re.M)}


def _issue_table() -> dict[str, str] | None:
    """共用组件的校验码中文类别表（ISSUE_MESSAGES）。"""
    f = ROOT / PLATFORM_ERRORS_JS
    if not f.is_file():
        return None
    text = f.read_text(encoding="utf-8")
    m = re.search(r"export const ISSUE_MESSAGES = \{(.*?)^\};", text, re.S | re.M)
    if not m:
        return None
    return {k: v for k, v in re.findall(r"^\s+([a-z][a-z0-9_]*):\s*'([^'\n]*)',?\s*$", m.group(1), re.M)}


def _component_issue_codes():
    """组件后端实际产出的校验码：Issue("码", …) 与 _Stop("码", …)。"""
    base = ROOT / "core" / "sdk" / "haiknow_sdk" / "preview" / "components"
    if not base.is_dir():
        return
    for f in sorted(base.glob("c0*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=rel(f))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            if name in ("Issue", "_Stop") and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                yield node.args[0].value, rel(f)


def _backend_codes(tree: ast.AST):
    """应用后端抛出的自定义错误码：DataError("码", ...) 和错误体里常量形式的 "code": "码"。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            if name == "DataError" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                yield node.lineno, node.args[0].value.upper()
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "code" and isinstance(v, ast.Constant) and isinstance(v.value, str):
                    yield v.lineno, v.value


def _scan_error_display(r: Report, f: Path) -> None:
    where = rel(f)
    text = _blank_js_comments(f.read_text(encoding="utf-8"))
    for m in ERR_MESSAGE.finditer(text):
        r.rule("CHK-ERR-02", where, f"直接使用 {m.group(0)}；原始说明可能是英文或含内部信息", line=line_of(text, m.start()))
    lines = {line_of(text, m.start()) for rx in (ERR_TEMPLATE_CODE, ERR_CONCAT_CODE, ERR_SHOWN_CODE, ERR_BADGE_CODE) for m in rx.finditer(text)}
    for line in sorted(lines):
        r.rule("CHK-ERR-01", where, "把错误码拼进或直接展示在界面文案里", line=line)
    for pos in _error_state_code_calls(text):
        r.rule("CHK-ERR-01", where, "ErrorState 传了 code，界面会显示「错误码：xxx」", line=line_of(text, pos))


def check_errors(r: Report, only: str | None) -> None:
    platform = _platform_error_table()
    # 1) 前端展示：core/web 与全部应用 web/（含 _template）；--app 只查该应用
    apps_root = ROOT / "apps"
    app_roots = [p for p in sorted(apps_root.iterdir()) if p.is_dir() and not p.name.startswith(".") and (only is None or p.name == only)] if apps_root.is_dir() else []
    scan_dirs = [p / "web" for p in app_roots]
    if only is None:
        scan_dirs.append(ROOT / "core" / "web")
        scan_dirs.append(ROOT / "core" / "sdk" / "js" / "preview" / "components")
    for base in scan_dirs:
        for f in sorted(base.rglob("*.js")) if base.is_dir() else []:
            _scan_error_display(r, f)
    # 2) 应用自定义码登记
    for d in app_roots:
        registry = _err_json_registry(r, d)
        if registry is None:
            continue
        reg_where = rel(d / "web" / "errors.json")
        for code, text in registry.items():
            if not CODE_KEY.fullmatch(str(code)):
                r.rule("CHK-ERR-03", reg_where, f"错误码 {code!r} 须使用大写 SNAKE_CASE")
            if platform and code.lower() in platform:
                r.rule("CHK-ERR-03", reg_where, f"{code} 是平台码，不能在应用里重新登记；直接使用平台提示")
            if not (isinstance(text, str) and HAN.search(text)):
                r.rule("CHK-ERR-03", reg_where, f"{code} 的提示必须是中文")
        known = set(registry) | {key.upper() for key in platform or {}}
        for f in sorted((d / "api").rglob("*.py")) if (d / "api").is_dir() else []:
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"), filename=rel(f))
            except SyntaxError:
                continue  # 语法错误由 CHK-APP-13 报
            for line, code in _backend_codes(tree):
                if code not in known:
                    r.rule("CHK-ERR-03", rel(f), f"自定义错误码 {code} 未在 {reg_where} 登记中文提示", line=line)
        for f in sorted((d / "web").rglob("*.js")) if (d / "web").is_dir() else []:
            js = _blank_js_comments(f.read_text(encoding="utf-8"))
            for m in ERR_CODE_CMP.finditer(js):
                if m.group(2) not in known:
                    r.rule("CHK-ERR-03", rel(f), f"前端判断了未登记的错误码 {m.group(2)}", line=line_of(js, m.start()))
    # 3) 平台码表与文档、服务端一致
    if only is not None:
        return
    where = str(PLATFORM_ERRORS_JS)
    if platform is None:
        r.rule("CHK-ERR-04", where, "找不到 PLATFORM_ERROR_MESSAGES 码表")
        return
    for code, text in platform.items():
        if not HAN.search(text) or code in text:
            r.rule("CHK-ERR-04", where, f"{code} 的提示必须是不含码的中文")
    wanted: dict[str, str] = {}
    doc = ROOT / PLATFORM_API_DOC
    if doc.is_file():
        for code in re.findall(r"`([A-Z][A-Z0-9_]*) \d{3}`", doc.read_text(encoding="utf-8"), re.M):
            wanted.setdefault(code.lower(), str(PLATFORM_API_DOC))
    server = ROOT / "core" / "server"
    patterns = (
        r"\b(?:DataError|AIError)\(\s*['\"]([A-Za-z][A-Za-z0-9_]*)['\"]",
        r"\bIdentityError\(\s*\d+\s*,\s*['\"]([A-Za-z][A-Za-z0-9_]*)['\"]",
        r"\b(?:_error|v1_error)\(\s*\d+\s*,\s*['\"]([A-Za-z][A-Za-z0-9_]*)['\"]",
        r"['\"]code['\"]\s*:\s*['\"]([A-Za-z][A-Za-z0-9_]*)['\"]",
    )
    for f in sorted(server.rglob("*.py")) if server.is_dir() else []:
        src = f.read_text(encoding="utf-8")
        for pat in patterns:
            for m in re.finditer(pat, src):
                wanted.setdefault(m.group(1).lower(), rel(f))
    for code, source in sorted(wanted.items()):
        if code not in platform:
            r.rule("CHK-ERR-04", where, f"{source} 使用了错误码 {code}，码表里没有它的中文提示")
    # 4) 组件校验码：后端 Issue/_Stop 的码必须在 ISSUE_MESSAGES 登记中文类别
    issues = _issue_table()
    if issues is None:
        r.rule("CHK-ERR-04", where, "找不到 ISSUE_MESSAGES 校验码中文类别表")
        return
    for code, text in issues.items():
        if not HAN.search(text) or code in text:
            r.rule("CHK-ERR-04", where, f"{code} 的中文类别必须是不含码的中文")
    for code, source in sorted(set(_component_issue_codes())):
        if code not in issues:
            r.rule("CHK-ERR-04", where, f"{source} 产出了校验码 {code}，ISSUE_MESSAGES 里没有它的中文类别")


def check_size(r: Report, _: str | None) -> None:
    for f in files():
        parts = f.relative_to(ROOT).parts
        if not parts or parts[0] != "apps":
            continue
        try:
            size = f.stat().st_size
        except OSError:
            continue
        if size > MAX_APP_FILE:
            r.rule("CHK-REPO-01", rel(f), f"{size / 1024 / 1024:.1f}MB，超过 2MB 上限")


def is_platform_path(path: str) -> bool:
    """apps/<id>/ 下才是应用自己的面；apps/README.md、apps/_shared/ 等共享路径算平台面。"""
    parts = path.strip("/").split("/")
    if len(parts) < 3 or parts[0] != "apps":
        return True
    return parts[1].startswith(("_", "."))


def changed_paths() -> list[str] | None:
    """本 MR 的改动清单；没有 git 或没有基准分支时返回 None，由调用方降级为提示。"""
    if not (shutil.which("git") and (ROOT / ".git").exists()):
        return None
    base = os.environ.get("CI_MERGE_REQUEST_DIFF_BASE_SHA") or "origin/main"
    diff = subprocess.run(["git", "diff", "--name-only", "-z", base], cwd=ROOT, capture_output=True, text=True)
    if diff.returncode != 0:
        return None
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT, capture_output=True, text=True
    )
    paths = [p for p in diff.stdout.split("\0") + untracked.stdout.split("\0") if p]
    return sorted(set(paths))


def check_owners(r: Report, _: str | None) -> None:
    paths = changed_paths()
    if paths is None:
        if os.environ.get("CI_MERGE_REQUEST_IID"):
            r.notice("CHK-REPO-02", "无法读取改动清单（CI 镜像无 git 或缺少基准分支）；请在评审时确认 apps/ 之外的平台路径已由 CODEOWNERS 负责人审批")
        return
    platform = sorted(p for p in paths if is_platform_path(p))
    if not platform:
        return
    owners = sorted({o for p in platform for o in codeowners_for(p)})
    shown = "、".join(platform[:5]) + (" 等" if len(platform) > 5 else "")
    r.notice("CHK-REPO-02", f"{len(platform)} 个平台路径改动（{shown}）需要 CODEOWNERS 负责人审批：{' '.join(owners) or '未登记'}")


def check_secrets(r: Report, _: str | None) -> None:
    for f in files():
        if f.name in {".env.example"} or f.suffix in {".png", ".jpg", ".jpeg", ".gif", ".xlsx", ".docx", ".pdf", ".zip", ".ico", ".woff2"}:
            continue
        if f.name == ".env":
            r.rule("CHK-REPO-04", rel(f), ".env 不得入库")
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for rx in SECRET_RES:
            m = rx.search(text)
            if m and f.resolve() != Path(__file__).resolve():
                r.rule("CHK-REPO-03", rel(f), "疑似密钥，不得入库", line=line_of(text, m.start()))
                break


def check_ledger(r: Report, _: str | None) -> None:
    if shutil.which("git") and (ROOT / ".git").exists():
        tracked = subprocess.run(["git", "ls-files", "harness", ".harness"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    else:  # CI 检出里只有已跟踪文件
        tracked = [str(p) for p in (ROOT / "harness").rglob("*")] if (ROOT / "harness").exists() else []
    if tracked:
        r.rule("CHK-REPO-05", "harness/", f"个人 Harness 台账不得入库（{len(tracked)} 个文件）")


def check_docs(r: Report, _: str | None) -> None:
    md_files = [f for f in files() if f.suffix == ".md"]
    for f in md_files:
        text = f.read_text(encoding="utf-8")
        # 去掉代码块但保留行数，避免死链行号偏移
        text = re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
        for m in MD_LINK.finditer(text):
            link = m.group(1).split("#")[0]
            if not link or re.match(r"^[a-z]+:", link) or link.startswith("/"):
                continue
            if not (f.parent / link).exists():
                r.rule("CHK-REPO-06", rel(f), f"死链 {link}", line=line_of(text, m.start()))
    docs = ROOT / "docs"
    index_path = docs / "README.md"
    if not index_path.is_file():
        return
    index = index_path.read_text(encoding="utf-8")
    for sub in sorted(p for p in docs.iterdir() if p.is_dir()):
        if not (sub / "README.md").is_file():
            r.rule("CHK-REPO-07", rel(sub), "每个文档目录要有 README.md 说明放什么")
        if f"({sub.name}/" not in index:
            r.rule("CHK-REPO-07", "docs/README.md", f"索引未链接 {sub.name}/")


def _is_status_code(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "status_code"


def _is_403(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == 403


def _is_false_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and not node.value


def _asserts_403(node: ast.AST) -> bool:
    """assert 的顶层必须正向要求 403：Eq 或正向 and 链，拒绝 not / or / is False。"""
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        if any(_is_false_constant(value) for value in node.values):
            return False
        return any(_asserts_403(value) for value in node.values)
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
        left, right = node.left, node.comparators[0]
        return (_is_status_code(left) and _is_403(right)) or (_is_403(left) and _is_status_code(right))
    return False


def _raises_permission_call(node: ast.AST) -> bool:
    """pytest.raises(PermissionDenied) 或 raises(PermissionDenied)，只作为 with 的上下文才算。"""
    if not isinstance(node, ast.Call) or not node.args:
        return False
    fn = node.func
    is_raises = (isinstance(fn, ast.Attribute) and fn.attr == "raises") or (isinstance(fn, ast.Name) and fn.id == "raises")
    if not is_raises:
        return False
    arg = node.args[0]
    name = arg.id if isinstance(arg, ast.Name) else arg.attr if isinstance(arg, ast.Attribute) else ""
    return name == "PermissionDenied"


def _has_permission_case(tree: ast.AST) -> bool:
    """只认真正的无权限断言：assert 正向 == 403，或 with pytest.raises(PermissionDenied)。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and _asserts_403(node.test):
            return True
        if isinstance(node, (ast.With, ast.AsyncWith)) and any(
            _raises_permission_call(item.context_expr) for item in node.items
        ):
            return True
    return False


def _tests_have_permission_case(tests: list[Path]) -> bool:
    for f in tests:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except (SyntaxError, UnicodeDecodeError):
            continue  # 语法错误交给 pytest（CHK-TEST-03）报
        if _has_permission_case(tree):
            return True
    return False


def check_test_files(r: Report, only: str | None) -> None:
    for d in app_dirs(only):
        if not (d / "api" / "router.py").is_file():
            continue
        tests = sorted((d / "tests").glob("test_*.py")) if (d / "tests").is_dir() else []
        if not tests:
            r.rule("CHK-TEST-01", rel(d / "tests"), "有后端但缺少 tests/test_*.py")
            continue
        if not _tests_have_permission_case(tests):
            r.rule("CHK-TEST-02", rel(tests[0]), "tests/ 没有真正的无权限断言（assert ... == 403 或 with pytest.raises(PermissionDenied)）")


def _run_js_tests(r: Report) -> None:
    """tests/js 是纯 Node 行为脚本；清单与 CI 的 js-tests 作业一致。没装 node 时只打印跳过。"""
    scripts = sorted((ROOT / "tests" / "js").glob("*.test.mjs")) + [ROOT / "tests" / "js" / "mock_test.mjs"]
    node = shutil.which("node")
    if node is None:
        print(f"[跳过] tests/js（{len(scripts)} 个前端行为脚本）：未找到 node")
        return
    env = _test_env(ADMIN_AI_JS="core/web/admin-ai.js")  # admin-ai.test.mjs 读取被测文件的路径
    for script in scripts:
        p = subprocess.run([node, "--no-warnings", str(script)], cwd=ROOT, capture_output=True, text=True, env=env)
        if p.returncode != 0:
            print(p.stdout + p.stderr)
            r.rule("CHK-TEST-03", rel(script), f"前端行为脚本失败（退出码 {p.returncode}）")
            return
    print(f"[通过] tests/js（{len(scripts)} 个前端行为脚本）")


def check_tests(r: Report, only: str | None) -> None:
    check_test_files(r, only)
    # -rs：把每个 skip 的测试名与原因打进 CI 日志，不允许「绿了但没人知道跳过了什么」。
    args = [sys.executable, "-m", "pytest", "-rs"]
    if only:
        args += [str(ROOT / "apps" / only)]
    else:
        args.append(".")
    p = subprocess.run(args, cwd=ROOT, env=_test_env())
    if p.returncode not in (0, 5):  # 5 = 没有收集到测试
        r.rule("CHK-TEST-03", "tests", f"pytest 失败（退出码 {p.returncode}）")
    if not only:  # --app 只跑该应用；tests/js 是平台面，全量门才跑
        _run_js_tests(r)


CHECKS = {
    "manifest": check_manifest,
    "readme": check_readme,
    "boundary": check_boundary,
    "errors": check_errors,
    "size": check_size,
    "owners": check_owners,
    "secrets": check_secrets,
    "ledger": check_ledger,
    "docs": check_docs,
    "tests": check_tests,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--app")
    a = ap.parse_args()
    names = [n for n in a.only.split(",") if n] or list(CHECKS)
    unknown = set(names) - set(CHECKS)
    if unknown:
        print(f"未知检查 {unknown}", file=sys.stderr)
        return 2
    r = Report()
    for n in names:
        before = len(r.errors)
        CHECKS[n](r, a.app)
        print(f"[{'通过' if len(r.errors) == before else '失败'}] {n}")
    if r.notices:
        print("\n提示（不阻断合入，需人工确认）：")
        print("\n".join(f"  - {n}" for n in r.notices))
    if r.errors:
        print("\n" + "\n".join(f"  - {e}" for e in r.errors))
        print(f"\n{len(r.errors)} 个问题，不能合入。规则说明见 docs/specs/检查规则.md。")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

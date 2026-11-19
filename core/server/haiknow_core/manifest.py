"""应用清单 app.json 的字段约定与校验。平台启动和 scripts/check.py 共用。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from haiknow_sdk import ACTIONS

CONTRACT = 1
KINDS = ("module", "embed")
SECTORS = ("platform", "manufacturing", "marketing", "warehouse", "hr", "content", "other")
STATUSES = ("idea", "prototype", "usable", "demo-ready")
SUPPORTED_SDK = ("1", "2")
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
# 版本会成为 data/app-versions/<id>/<version>/ 的目录名，校验放在清单元数据边界。
VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}")

REQUIRED = {
    "contract": int,
    "id": str,
    "name": str,
    "sector": str,
    "kind": str,
    "owner": str,
    "status": str,
}


def sdk_error(m: dict) -> str:
    """旧清单缺省为 1；不支持的主版本保留目录条目但不执行应用代码。"""
    if m.get("sdk", "1") not in SUPPORTED_SDK:
        return "SDK 版本不兼容：sdk 必须为字符串主版本，当前支持 " + ", ".join(SUPPORTED_SDK)
    return ""


def validate(m: dict, folder: str | None = None) -> list[str]:
    errs: list[str] = []
    if not isinstance(m, dict):
        return ["app.json 必须是对象"]
    for k, t in REQUIRED.items():
        if k not in m:
            errs.append(f"缺少字段 {k}")
        elif not isinstance(m[k], t):
            errs.append(f"字段 {k} 类型应为 {t.__name__}")
    if errs:
        return errs
    if m["contract"] != CONTRACT:
        errs.append(f"contract 应为 {CONTRACT}")
    if not ID_RE.match(m["id"]):
        errs.append("id 只能是小写字母、数字、连字符，字母开头，2–40 位")
    if folder is not None and m["id"] != folder and not folder.startswith("_"):
        errs.append(f"id {m['id']} 与目录名 {folder} 不一致")
    if m["kind"] not in KINDS:
        errs.append(f"kind 只能是 {KINDS}")
    if m["sector"] not in SECTORS:
        errs.append(f"sector 只能是 {SECTORS}")
    if m["status"] not in STATUSES:
        errs.append(f"status 只能是 {STATUSES}")
    if m["kind"] == "embed" and not str(m.get("url", "")).startswith(("http://", "https://")):
        errs.append("embed 型应用必须写 http(s) 绝对地址的 url")
    roles = m.get("defaultRoles") or {}
    if not isinstance(roles, dict):
        errs.append("defaultRoles 必须是角色到动作数组的对象")
    else:
        for role, acts in roles.items():
            if not isinstance(acts, list) or any(a not in ACTIONS for a in acts):
                errs.append(f"defaultRoles.{role} 必须是已知动作的数组")
    if "actions" in m and (not isinstance(m["actions"], list) or any(a not in ACTIONS for a in m["actions"])):
        errs.append("actions 必须是已知动作的数组")
    if "review" in m and m["review"] not in ("platform", "app"):
        errs.append("review 只能是 platform（平台通用审核）或 app（应用自管审核）")
    cross = m.get("crossProject")
    if cross is not None:
        if not isinstance(cross, dict) or not isinstance(cross.get("subjectField"), str) or not cross["subjectField"].strip():
            errs.append("crossProject.subjectField 必须是非空字符串")
        elif not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", cross["subjectField"]):
            errs.append("crossProject.subjectField 必须是简单的顶层字段名")
    scenes = m.get("scenes", [])
    if not isinstance(scenes, list) or not all(isinstance(s, str) for s in scenes):
        errs.append("scenes 必须是字符串数组（场景编号）")
    if "version" in m and (not isinstance(m["version"], str) or not VERSION_RE.fullmatch(m["version"])):
        errs.append("version 必须是字母数字开头的安全路径名（如 1.0.0），不写则为 0")
    return errs


def discover(apps_dir: Path, include_template: bool = False) -> list[tuple[Path, dict | None, list[str]]]:
    """返回 (目录, 清单或 None, 错误)；不抛异常，坏清单只影响自己。"""
    out = []
    if not apps_dir.is_dir():
        return out
    for d in sorted(p for p in apps_dir.iterdir() if p.is_dir()):
        if d.name.startswith(".") or (d.name.startswith("_") and not include_template):
            continue
        f = d / "app.json"
        if not f.is_file():
            out.append((d, None, ["缺少 app.json"]))
            continue
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            out.append((d, None, [f"app.json 不是合法 JSON：{e}"]))
            continue
        except (OSError, UnicodeError) as e:
            out.append((d, None, [f"app.json 无法读取（{type(e).__name__}）"]))
            continue
        out.append((d, m, validate(m, d.name)))
    return out

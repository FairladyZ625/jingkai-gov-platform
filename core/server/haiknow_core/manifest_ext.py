"""经开区应用清单扩展。未声明扩展的卫华 v1 清单仍可运行。"""
from __future__ import annotations

import re

_SEGMENT = re.compile(r"[A-Za-z0-9_~-][A-Za-z0-9_.~-]*")
_PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_TOOL = re.compile(r"[a-z][a-z0-9_-]*")
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_DATA_CLASSES = ("public", "internal", "confidential")
_FIELDS = ("tools", "starters", "chatCards", "deepLink", "dataClass", "accepts", "intents", "routes")


def safe_segment(value: str) -> bool:
    return _SEGMENT.fullmatch(value) is not None


def endpoint_parts(endpoint: str, app_id: str) -> tuple[str, list[str]]:
    """仅解析本应用的已声明 API 路径，支持整段的 FastAPI 路径参数。"""
    method, _, path = endpoint.partition(" ")
    prefix = f"/api/apps/{app_id}/"
    segments = path.removeprefix(prefix).split("/")
    if (method not in _METHODS or not path.startswith(prefix)
            or not all(safe_segment(segment) or _PARAM.fullmatch(segment) for segment in segments)):
        raise ValueError("必须是当前应用下的 HTTP 方法与 API 路径")
    return method, segments


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(map(_text, value))


def _string_map(value: object) -> bool:
    return isinstance(value, dict) and all(map(_text, value.values()))


_TYPES = {
    "非空字符串": _text,
    "字符串数组": _strings,
    "字符串值对象": _string_map,
    "布尔值": lambda value: isinstance(value, bool),
}


def _object_fields(value: object, fields: dict[str, str], path: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"字段 {path} 类型应为对象")
        return False
    before = len(errors)
    for key, field_type in fields.items():
        field = f"{path}.{key}"
        if key not in value:
            errors.append(f"缺少字段 {field}")
        elif not _TYPES[field_type](value[key]):
            errors.append(f"字段 {field} 类型应为{field_type}")
    return len(errors) == before


def validate_extensions(manifest: dict, *, required: bool = False) -> list[str]:
    """扩展成组声明，数组可为空，声明后检查成员与必填子字段。"""
    if not required and not any(key in manifest for key in _FIELDS):
        return []
    errors = [f"缺少字段 {key}" for key in _FIELDS if key not in manifest]
    for key in ("starters", "chatCards", "routes"):
        if key in manifest and not _strings(manifest[key]):
            errors.append(f"字段 {key} 类型应为字符串数组")
    if "deepLink" in manifest:
        _object_fields(manifest["deepLink"], {"params": "字符串数组"}, "deepLink", errors)
    if "dataClass" in manifest and manifest["dataClass"] not in _DATA_CLASSES:
        errors.append("字段 dataClass 必须是 public、internal 或 confidential")

    for key, fields in (
        ("tools", {"name": "非空字符串", "description": "非空字符串", "write": "布尔值",
                   "input": "字符串值对象", "endpoint": "非空字符串"}),
        ("accepts", {"kind": "非空字符串", "ext": "字符串数组", "match": "非空字符串"}),
        ("intents", {"id": "非空字符串", "action": "非空字符串", "plan": "字符串数组"}),
    ):
        items = manifest.get(key, [])
        if not isinstance(items, list):
            errors.append(f"字段 {key} 类型应为对象数组")
            continue
        names: set[str] = set()
        for index, item in enumerate(items):
            path = f"{key}[{index}]"
            if not _object_fields(item, fields, path, errors) or key != "tools":
                continue
            app_id = manifest.get("id", "")
            prefix = f"{app_id}."
            name = item["name"]
            if not name.startswith(prefix) or not _TOOL.fullmatch(name.removeprefix(prefix)):
                errors.append(f"字段 {path}.name 必须是 {app_id}.工具名")
            if name in names:
                errors.append(f"字段 {path}.name 重复：{name}")
            names.add(name)
            try:
                method, _ = endpoint_parts(item["endpoint"], app_id)
            except ValueError as error:
                errors.append(f"字段 {path}.endpoint {error}")
            else:
                allowed = {"POST", "PUT", "PATCH", "DELETE"} if item["write"] else {"GET", "POST"}
                if method not in allowed:
                    errors.append(f"字段 {path}.endpoint 的 HTTP 方法与 write 不匹配")
    return errors

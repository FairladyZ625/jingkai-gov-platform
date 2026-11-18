"""场景表：加载 config/scenes.yaml，校验结构并回答编号是否登记。

场景表只描述结构（编号、名称、分组、是否首批），不含业务数据；覆盖关系来自各应用
app.json 的 `scenes`。业主换新版需求表时只替换这个文件。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

FILE_NAME = "scenes.yaml"


class SceneTableError(ValueError):
    """场景表不可用；消息直接给人看，指出文件与出错字段。"""


@dataclass(frozen=True)
class Scene:
    id: str
    name: str
    first: bool = False


@dataclass(frozen=True)
class SceneGroup:
    id: str
    name: str
    scenes: tuple[Scene, ...]


@dataclass(frozen=True)
class SceneTable:
    groups: tuple[SceneGroup, ...] = ()
    error: str = ""

    def __iter__(self):
        for group in self.groups:
            yield from group.scenes

    def codes(self) -> set[str]:
        return {scene.id for scene in self}


def load(config_dir: Path) -> SceneTable:
    """读取并校验场景表；结构不合法时抛 SceneTableError，读回的数据不再重复校验。"""
    path = Path(config_dir) / FILE_NAME
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SceneTableError(f"{path} 不存在") from exc
    except OSError as exc:
        raise SceneTableError(f"{path} 读取失败：{exc}") from exc
    except yaml.YAMLError as exc:
        raise SceneTableError(f"{path} 不是合法 YAML：{exc}") from exc
    return _parse(raw, path)


def unknown_codes(table: SceneTable, codes: set[str] | list[str]) -> list[str]:
    """应用声明了、场景表却没有登记的编号；用于启动提示，不阻断服务。"""
    return sorted(set(codes) - table.codes())


def _parse(raw: object, path: Path) -> SceneTable:
    if not isinstance(raw, dict):
        raise SceneTableError(f"{path} 顶层必须是对象")
    groups_raw = raw.get("groups")
    if not isinstance(groups_raw, list) or not groups_raw:
        raise SceneTableError(f"{path} 缺少非空的 groups 列表")
    groups: list[SceneGroup] = []
    seen_groups: set[str] = set()
    seen_scenes: set[str] = set()
    for gi, group_raw in enumerate(groups_raw, 1):
        where = f"groups[{gi}]"
        if not isinstance(group_raw, dict):
            raise SceneTableError(f"{path} {where} 必须是对象")
        group_id = _text(group_raw, "id", where, path)
        if group_id in seen_groups:
            raise SceneTableError(f"{path} 分组 id 重复：{group_id}")
        seen_groups.add(group_id)
        group_name = _text(group_raw, "name", where, path)
        scenes_raw = group_raw.get("scenes")
        if not isinstance(scenes_raw, list) or not scenes_raw:
            raise SceneTableError(f"{path} {where}.scenes 必须是非空列表")
        scenes: list[Scene] = []
        for si, scene_raw in enumerate(scenes_raw, 1):
            scene_where = f"{where}.scenes[{si}]"
            if not isinstance(scene_raw, dict):
                raise SceneTableError(f"{path} {scene_where} 必须是对象")
            code = _text(scene_raw, "id", scene_where, path)
            if code in seen_scenes:
                raise SceneTableError(f"{path} 场景编号重复：{code}")
            seen_scenes.add(code)
            name = _text(scene_raw, "name", scene_where, path)
            first = scene_raw.get("first", False)
            if not isinstance(first, bool):
                raise SceneTableError(f"{path} {scene_where}.first 必须是 true 或 false")
            scenes.append(Scene(code, name, first))
        groups.append(SceneGroup(group_id, group_name, tuple(scenes)))
    return SceneTable(tuple(groups))


def _text(raw: dict, key: str, where: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SceneTableError(f"{path} {where}.{key} 必须是非空字符串")
    return value.strip()
"""C07 内容制作和审核：素材版本与使用权 → 制作任务 → 成果版本 → 修改意见与审核。

应用只写素材（版本、来源、使用权）、制作要求与生成参数；组件负责使用权校验、拼生成请求、
排成果版本号、记录修改意见和审核状态。生成动作是可选的注入函数：应用把 `ctx.ai.image` /
`ctx.ai.chat` 包成 `generate(request)` 传进来；组件本身不调模型、不存文件、不读环境变量。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

from .common import Issue, error_body

VERSION = "1.0.0"

RIGHTS = ("有", "无", "待确认")
STATUSES = ("待审", "通过", "退回")
KINDS = ("image", "chat")

__all__ = [
    "VERSION", "RIGHTS", "STATUSES", "KINDS", "Asset", "AssetRef", "Task", "Check", "Build",
    "Comment", "Version", "Outcome", "check", "build", "record", "comment", "decide", "Issue", "error_body",
]


@dataclass(frozen=True)
class Asset:
    """一份素材的一个版本；使用权按版本记录。"""

    id: str
    version: int = 1
    name: str = ""
    source: str = ""
    rights: str = "待确认"
    file_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("素材 id 不能为空")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ValueError("素材版本必须是正整数")
        if self.rights not in RIGHTS:
            raise ValueError(f"未知使用权标记 {self.rights}，只能是 {RIGHTS}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "source": self.source,
            "rights": self.rights,
            "fileId": self.file_id,
        }


@dataclass(frozen=True)
class AssetRef:
    """制作任务引用的素材版本；只认具体版本，不跟随最新版。"""

    id: str
    version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("素材引用 id 不能为空")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ValueError("素材引用版本必须是正整数")

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "version": self.version}


@dataclass(frozen=True)
class Task:
    """一次制作任务：要求、引用的素材版本和生成参数。"""

    id: str
    requirement: str
    assets: tuple[AssetRef, ...] = ()
    params: Mapping[str, Any] = field(default_factory=dict)
    kind: str = "image"

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("制作任务 id 不能为空")
        if not isinstance(self.requirement, str) or not self.requirement.strip():
            raise ValueError(f"制作任务 {self.id} 的要求不能为空")
        if self.kind not in KINDS:
            raise ValueError(f"未知生成类型 {self.kind}，只能是 {KINDS}")
        object.__setattr__(self, "assets", tuple(self.assets or ()))
        for ref in self.assets:
            if not isinstance(ref, AssetRef):
                raise TypeError("assets 里只能是 AssetRef")
        if not isinstance(self.params, Mapping):
            raise TypeError("params 必须是 dict")
        object.__setattr__(self, "params", dict(self.params))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "requirement": self.requirement,
            "kind": self.kind,
            "assets": [ref.to_dict() for ref in self.assets],
            "params": dict(self.params),
        }


@dataclass
class Check:
    ok: bool
    errors: list[Issue]
    warnings: list[Issue]
    assets: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "assets": [dict(item) for item in self.assets],
        }


@dataclass
class Build:
    ok: bool
    errors: list[Issue]
    warnings: list[Issue]
    assets: list[dict[str, Any]]
    request: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "assets": [dict(item) for item in self.assets],
            "request": dict(self.request) if self.request is not None else None,
        }


@dataclass(frozen=True)
class Comment:
    id: str
    author: str
    text: str
    at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "author": self.author, "text": self.text, "at": self.at}


@dataclass(frozen=True)
class Version:
    """一个成果版本；素材引用与生成参数按生成时快照保存。"""

    id: str
    task: str
    number: int
    output: Any
    params: Mapping[str, Any] = field(default_factory=dict)
    assets: tuple[AssetRef, ...] = ()
    status: str = "待审"
    reviewer: str = ""
    reason: str = ""
    comments: tuple[Comment, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("成果版本 id 不能为空")
        if not isinstance(self.task, str) or not self.task.strip():
            raise ValueError("成果版本必须属于一个制作任务")
        if not isinstance(self.number, int) or isinstance(self.number, bool) or self.number < 1:
            raise ValueError("成果版本号必须是正整数")
        if self.status not in STATUSES:
            raise ValueError(f"未知审核状态 {self.status}，只能是 {STATUSES}")
        object.__setattr__(self, "assets", tuple(self.assets or ()))
        object.__setattr__(self, "comments", tuple(self.comments or ()))
        object.__setattr__(self, "params", dict(self.params or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "number": self.number,
            "output": self.output,
            "params": dict(self.params),
            "assets": [ref.to_dict() for ref in self.assets],
            "status": self.status,
            "reviewer": self.reviewer,
            "reason": self.reason,
            "comments": [item.to_dict() for item in self.comments],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Version":
        """应用把版本存进 ctx.kv / records 后按原结构读回。"""
        if not isinstance(data, Mapping):
            raise TypeError("版本必须是 dict")
        return cls(
            id=str(data.get("id", "")),
            task=str(data.get("task", "")),
            number=int(data.get("number", 0)),
            output=data.get("output"),
            params=dict(data.get("params") or {}),
            assets=tuple(
                AssetRef(str(item["id"]), int(item["version"])) for item in data.get("assets", ())
            ),
            status=str(data.get("status", "待审")),
            reviewer=str(data.get("reviewer", "")),
            reason=str(data.get("reason", "")),
            comments=tuple(
                Comment(str(item["id"]), str(item["author"]), str(item["text"]), str(item.get("at", "")))
                for item in data.get("comments", ())
            ),
        )


@dataclass
class Outcome:
    ok: bool
    versions: list[Version]
    errors: list[Issue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "versions": [version.to_dict() for version in self.versions],
            "errors": [issue.to_dict() for issue in self.errors],
        }


def check(task: Task, assets: Sequence[Asset]) -> Check:
    """按引用版本查素材：不存在、没有使用权是错误，使用权待确认只给警告（可出草稿）。"""
    if not isinstance(task, Task):
        raise TypeError("task 必须是 Task")
    items = tuple(assets or ())
    index: dict[tuple[str, int], Asset] = {}
    known: set[str] = set()
    for asset in items:
        if not isinstance(asset, Asset):
            raise TypeError("assets 里只能是 Asset")
        known.add(asset.id)
        index.setdefault((asset.id, asset.version), asset)

    errors: list[Issue] = []
    warnings: list[Issue] = []
    resolved: list[dict[str, Any]] = []
    for ref in task.assets:
        asset = index.get((ref.id, ref.version))
        if asset is None:
            if ref.id in known:
                errors.append(Issue(
                    "unknown_asset_version", f"素材 {ref.id} 没有版本 {ref.version}", field=ref.id
                ))
            else:
                errors.append(Issue("unknown_asset", f"引用了不存在的素材 {ref.id}", field=ref.id))
            continue
        if asset.rights == "无":
            errors.append(Issue(
                "rights_denied", f"素材 {asset.name or asset.id} 没有使用权，不能用于成果", field=asset.id
            ))
        elif asset.rights == "待确认":
            warnings.append(Issue(
                "rights_pending", f"素材 {asset.name or asset.id} 使用权待确认，只能出草稿", field=asset.id
            ))
        resolved.append(asset.to_dict())

    return Check(ok=not errors, errors=errors, warnings=warnings, assets=resolved)


def build(task: Task, assets: Sequence[Asset]) -> Build:
    """校验素材并组装生成请求；不通过时不生成请求，应用据此回 422。"""
    checked = check(task, assets)
    request = None
    if checked.ok:
        names = "、".join(
            f"{item['name'] or item['id']} v{item['version']}" for item in checked.assets
        )
        prompt = task.requirement.strip()
        if names:
            prompt = f"{prompt}；参考素材：{names}"
        request = {
            "task": task.id,
            "kind": task.kind,
            "prompt": prompt,
            "params": dict(task.params),
            "assets": [dict(item) for item in checked.assets],
        }
    return Build(
        ok=checked.ok,
        errors=checked.errors,
        warnings=checked.warnings,
        assets=checked.assets,
        request=request,
    )


def record(
    prepared: Build,
    output: Any,
    *,
    versions: Iterable[Version] = (),
) -> Version:
    """把一次生成结果记成新版本；素材与参数取生成请求里的快照。"""
    if not isinstance(prepared, Build):
        raise TypeError("prepared 必须是 build() 的返回")
    if not prepared.ok or prepared.request is None:
        raise ValueError("素材检查未通过，不能生成成果")
    if _empty(output):
        raise ValueError("生成结果不能为空")
    items = _versions(versions)
    numbers = [item.number for item in items if item.task == prepared.request["task"]]
    number = max(numbers, default=0) + 1
    return Version(
        id=f"{prepared.request['task']}#v{number}",
        task=prepared.request["task"],
        number=number,
        output=output,
        params=dict(prepared.request["params"]),
        assets=tuple(AssetRef(item["id"], item["version"]) for item in prepared.request["assets"]),
    )


def comment(
    versions: Iterable[Version],
    version_id: str,
    *,
    author: str,
    text: str,
    at: str = "",
) -> Outcome:
    """给一个成果版本追加修改意见。"""
    items = _versions(versions)
    index = _find(items, version_id)
    if index is None:
        return Outcome(False, items, [Issue("version_not_found", f"没有版本 {version_id}", field=version_id)])
    errors: list[Issue] = []
    if not str(author or "").strip():
        errors.append(Issue("author_required", "需要填写提出意见的人", field=version_id))
    if not str(text or "").strip():
        errors.append(Issue("comment_required", "修改意见不能为空", field=version_id))
    if errors:
        return Outcome(False, items, errors)
    target = items[index]
    entry = Comment(
        id=f"{target.id}#c{len(target.comments) + 1}",
        author=str(author).strip(),
        text=str(text).strip(),
        at=str(at or ""),
    )
    items[index] = replace(target, comments=target.comments + (entry,))
    return Outcome(True, items, [])


def decide(
    versions: Iterable[Version],
    version_id: str,
    status: str,
    *,
    reviewer: str,
    reason: str = "",
    assets: Sequence[Asset] | None = None,
) -> Outcome:
    """审核成果版本：通过要复查素材使用权，退回要写理由；只有待审版本可以审核。"""
    if status not in ("通过", "退回"):
        raise ValueError(f"未知审核状态 {status}，只能是 通过 / 退回")
    items = _versions(versions)
    index = _find(items, version_id)
    if index is None:
        return Outcome(False, items, [Issue("version_not_found", f"没有版本 {version_id}", field=version_id)])
    target = items[index]
    errors: list[Issue] = []
    if not str(reviewer or "").strip():
        errors.append(Issue("reviewer_required", "需要填写审核人", field=version_id))
    if target.status != "待审":
        errors.append(Issue("already_decided", f"版本 {version_id} 已经审核过，退回后请交新版本", field=version_id))
    if status == "退回" and not str(reason or "").strip():
        errors.append(Issue("reason_required", "退回必须填写理由", field=version_id))
    if status == "通过":
        if assets is None:
            raise ValueError("通过审核时必须传 assets 复查素材使用权")
        errors.extend(_approval_errors(target, assets))
    if errors:
        return Outcome(False, items, errors)
    items[index] = replace(
        target,
        status=status,
        reviewer=str(reviewer).strip(),
        reason=str(reason or "").strip(),
    )
    return Outcome(True, items, [])


def _approval_errors(version: Version, assets: Sequence[Asset]) -> list[Issue]:
    index = {(asset.id, asset.version): asset for asset in (assets or ()) if isinstance(asset, Asset)}
    errors: list[Issue] = []
    for ref in version.assets:
        asset = index.get((ref.id, ref.version))
        if asset is None:
            errors.append(Issue("unknown_asset", f"引用了不存在的素材 {ref.id}", field=ref.id))
        elif asset.rights == "无":
            errors.append(Issue("rights_denied", f"素材 {asset.name or asset.id} 没有使用权，不能通过", field=asset.id))
        elif asset.rights == "待确认":
            errors.append(Issue("rights_pending", f"素材 {asset.name or asset.id} 使用权待确认，不能通过", field=asset.id))
    return errors


def _versions(versions: Iterable[Version]) -> list[Version]:
    items = list(versions or ())
    for version in items:
        if not isinstance(version, Version):
            raise TypeError("versions 里只能是 Version")
    return items


def _find(versions: list[Version], version_id: str) -> int | None:
    for index, version in enumerate(versions):
        if version.id == version_id:
            return index
    return None


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False
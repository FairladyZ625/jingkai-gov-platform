"""独立保存批注，通过 SDK 版本核对合并并发回复或状态更新。"""

from datetime import datetime

from haiknow_sdk import AppContext, DataError

from .drafts import BEIJING

RECORD_TYPE = "document-comment"


def _comment(record: dict) -> dict:
    data = {key: value for key, value in record["data"].items() if key != "draftId"}
    return {**data, "id": record["id"]}


def by_draft(ctx: AppContext) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    records = ctx.records.list(type=RECORD_TYPE)["items"]
    for record in reversed(records):
        groups.setdefault(record["data"]["draftId"], []).append(_comment(record))
    return groups


def add(ctx: AppContext, draft: dict, para: int, text: str) -> dict:
    created = ctx.records.save(project=draft["project"], type=RECORD_TYPE, data={
        "draftId": draft["id"],
        "para": para,
        "by": ctx.user.name,
        "at": datetime.now(BEIJING).isoformat(timespec="seconds"),
        "text": text,
        "replies": [],
        "resolved": False,
    })
    return _comment(created)


def update(ctx: AppContext, draft_id: str, cid: str, reply: str | None, resolved: bool | None) -> dict:
    at = datetime.now(BEIJING).isoformat(timespec="seconds")
    for attempt in range(3):
        current = ctx.records.get(cid)
        if current["type"] != RECORD_TYPE or current["data"]["draftId"] != draft_id:
            raise DataError("not_found", "批注不存在")

        data = current["data"]
        if reply is not None:
            data["replies"].append({"by": ctx.user.name, "at": at, "text": reply})
        if resolved is not None and resolved != data["resolved"]:
            data.update(resolved=resolved, resolvedBy=ctx.user.name, resolvedAt=at)
        elif reply is None:
            return _comment(current)

        try:
            record = ctx.records.save(id=cid, baseVersion=current["version"], data=data)
        except DataError as exc:
            if exc.code != "version_conflict" or attempt == 2:
                raise
        else:
            return _comment(record)

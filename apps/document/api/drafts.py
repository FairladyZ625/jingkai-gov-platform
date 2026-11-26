"""公文记录和送审状态的适配层，版本与审计沿用卫华数据底座。"""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from haiknow_sdk import DataError

RECORD_TYPE = "document-draft"
PROJECT = "jkq"
BEIJING = timezone(timedelta(hours=8))
STATUSES = {"draft": "草稿", "pending": "审签中", "needs_info": "已退回",
            "confirmed": "已定稿", "recheck": "已退回"}


def resolve_citations(knowledge, user, references, content):
    if references and knowledge is None:
        raise DataError("app_unavailable", "知识库尚未接入，暂时无法核对引文")

    citations = []
    seen = set()
    for reference in references:
        source = knowledge.detail(user, reference.id)
        if source["space"] not in {"policy", "template"}:
            raise DataError("invalid_request", "公文仅支持引用政策和公文范文", id=reference.id)
        identity, version = source["id"], source["version"]
        if (identity, version) in seen:
            continue
        seen.add((identity, version))
        n = len(citations) + 1
        marker = f"〔{n}〕"
        citation = {"n": n, "marker": marker, "id": identity, "version": version,
                    "title": source["title"],
                    "href": f"/api/v1/kb/docs/{quote(identity, safe='')}?version={version}"}
        if source["space"] == "policy":
            excerpts = source.get("excerpts") or []
            text = excerpts[0]["original"] if excerpts else source.get("text", "")
            excerpt = next((part.strip() for part in text.splitlines() if part.strip()), "")[:240]
            if excerpt:
                content["paragraphs"].append(f"政策原文摘录：{excerpt}{marker}")
            else:
                content["paragraphs"].append(f"政策出处：《{source['title']}》{marker} 【待补：政策条款原文】")
        citations.append(citation)
    return citations


def create(ctx, template_id, policy_id, content, citations, *, provider="mock", source=None):
    label = "政策模板初稿" if provider == "policy-template" else "模板初稿"
    record = ctx.records.save(project=PROJECT, type=RECORD_TYPE, data={
        "templateId": template_id, "policyId": policy_id, "author": ctx.user.name, "authorId": ctx.user.id,
        "by": f"{ctx.user.name}（{label}）", "content": content, "citations": citations, "comments": [],
        **({"source": source} if source else {}),
    })
    ctx.audit(f"document.draft.{provider}", {"recordId": record["id"], "provider": provider})
    return _draft(record, [_edition(record)])


def _edition(record):
    data = record["data"]
    return {
        "v": record["version"] - 1,
        "at": datetime.fromtimestamp(record["createdAt"], BEIJING).isoformat(timespec="seconds"),
        "by": data["by"],
        "content": data["content"],
    }


def _draft(current, editions):
    data = current["data"]
    return {
        "id": current["id"], "title": data["content"]["title"], "templateId": data["templateId"],
        "policyId": data["policyId"], "status": STATUSES[current["status"]], "author": data["author"],
        "versions": editions, "comments": data["comments"], "refs": data["citations"],
        **({"source": data["source"]} if data.get("source") else {}),
    }


def _record(ctx, identity, version=None):
    record = ctx.records.get(identity, version)
    if record["type"] != RECORD_TYPE:
        raise DataError("not_found", "文稿不存在")
    return record


def _present(ctx, current, version=None):
    identity, latest = current["id"], current["version"]
    if version is not None:
        core_version = version + 1
        if core_version > latest:
            raise DataError("not_found", "文稿版本不存在")
        record = current if core_version == latest else _record(ctx, identity, core_version)
        return _draft(current, [_edition(record)])
    # 初稿是可读的第 0 版。第一次保存后，默认历史只返回显式保存的版本。
    editions = [_edition(_record(ctx, identity, v)) for v in range(2, latest)]
    editions.append(_edition(current))
    return _draft(current, editions)


def get(ctx, identity, version):
    return _present(ctx, _record(ctx, identity), version)


def _locked():
    return DataError("locked", "已定稿文稿不能修改，请另存新稿")


def save(ctx, identity, content, note, base_version=None):
    editor = f"{ctx.user.name}（{note}）" if note else ctx.user.name
    for attempt in range(3):
        current = _record(ctx, identity)
        if current["status"] == "confirmed":
            raise _locked()
        if base_version is not None and current["version"] - 1 != base_version:
            raise DataError("stale_version", "文稿已有新版本，请刷新后核对再保存")
        try:
            record = ctx.records.save(id=identity, baseVersion=current["version"],
                                      data={**current["data"], "by": editor, "content": content})
        except DataError as exc:
            if exc.code != "version_conflict" or attempt == 2 or base_version is not None:
                raise
        else:
            return _present(ctx, record)


def summaries(ctx):
    records = ctx.records.list(type=RECORD_TYPE)["items"]
    records.sort(key=lambda record: record["createdAt"], reverse=True)
    return [summary(record) for record in records]


def summary(record):
    """文稿列表和工作台共用的记录摘要，不改变底层记录。"""
    data = record["data"]
    version = _edition(record)
    return {
        "id": record["id"], "title": data["content"]["title"], "templateId": data["templateId"],
        "status": STATUSES[record["status"]], "author": data["author"], "updated": version["at"],
        "versions": version["v"], "comments": sum(not comment["resolved"] for comment in data["comments"]),
    }

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jkq.kb.importer.repository import MemoryImportRepository
from jkq.kb.importer.service import ImportFailure, ImportService, SpaceAccess, Upload

USER = SimpleNamespace(id="示例用户")
POLICY = SpaceAccess(frozenset({"policy"}), frozenset({"policy"}))
ALL = SpaceAccess(frozenset({"policy", "rules"}), frozenset({"policy", "rules"}))


def payload(text="第一条 使用虚构资料。", *, title="星汀绿色阅读办法", **meta):
    return {"items": [{"name": "样本.txt", "text": text, "meta": {"title": title, **meta}}]}


def setup(*, access=POLICY, repository=None, **options):
    if repository is None:
        repository = MemoryImportRepository()
    return ImportService(repository, lambda user: access, **options), repository


def docs(repository, space="policy"):
    with repository.transaction(write=False) as view:
        return view.candidates(space)


def test_preview_roundtrip_persists_metadata_and_rebuilds_chunks():
    service, repository = setup()
    body = "第一条 支持绿色阅读。\n第十二条 仅使用虚构材料。"
    data = payload(body, docNo="星阅发〔2026〕7号", org="星汀虚构阅读中心",
                   date="2026年3月8日", status="即将到期", url="https://example.invalid/policy")
    item, = asyncio.run(service.preview(USER, data))["items"]
    assert docs(repository) == []
    assert item["stages"] == {"parse": "done", "chunk": "done", "tag": "done"}
    assert item["chunks"] == 2
    assert item["chunkPreview"] == [
        {"head": "第一条", "text": body.splitlines()[0]},
        {"head": "第十二条", "text": body.splitlines()[1]},
    ]
    assert item["tags"] == ["文化", "绿色低碳"]
    item.update(chunks=81, chunkPreview=[], tags=["用户标签"])
    result = asyncio.run(service.commit(USER, {"items": [item]}))
    saved, = docs(repository)
    assert result["chunks"] == saved["chunks"] == 2
    assert saved["status"] == "即将到期" and saved["text"] == body and saved["uploadedBy"] == USER.id
    assert saved["source"] == dict(docNo="星阅发〔2026〕7号", org="星汀虚构阅读中心",
                                   date="2026-03-08", url="https://example.invalid/policy")
    assert saved["tags"] == ["用户标签"]
    for chunk in saved["chunkList"]:
        assert body[chunk["start"]:chunk["end"]] == chunk["text"]
        assert chunk["text"].startswith(chunk["head"])


def test_version_by_doc_number_and_exact_duplicates_include_previous_version():
    service, repository = setup(title_threshold=1)
    initial = payload(docNo="星阅发〔2026〕7号")
    first, = asyncio.run(service.commit(USER, initial))["docs"]
    revised = payload("第一条 已修订。", title="虚构的另一标题", docNo="星阅发【2026】 7 号")
    preview, = asyncio.run(service.preview(USER, revised))["items"]
    assert preview["dup"] == dict(type="version", title=first["title"], id=first["id"],
                                   sim=100, oldDate="", oldVersion=1)
    assert docs(repository)[0]["status"] == "现行有效"

    latest, = asyncio.run(service.commit(USER, {"items": [dict(preview, decision="version")]}))["docs"]
    old, new = docs(repository)
    assert (old["status"], old["replacedBy"]) == ("已更新", latest["id"])
    assert (new["version"], new["prev"]) == (2, first["id"])
    initial["items"][0]["decision"] = "new"
    retry = asyncio.run(service.commit(USER, initial))
    assert retry == dict(docs=[], chunks=0, skipped=[dict(name="样本.txt", reason="已在库中")])


@pytest.mark.parametrize("threshold,expected", [(0.62, "version"), (0.9, "new")])
def test_title_similarity_threshold(threshold, expected):
    service, _ = setup(title_threshold=threshold)
    asyncio.run(service.commit(USER, payload()))
    item, = asyncio.run(service.preview(USER, payload("第一条 修订。", title="星汀绿色阅读办法修订")))["items"]
    assert item["dup"]["type"] == expected


def test_duplicate_and_version_hints_stay_in_authorized_target_space():
    service, repository = setup(access=ALL)
    hidden = payload(space="rules")
    original, = asyncio.run(service.commit(USER, hidden))["docs"]
    service, _ = setup(repository=repository)
    preview, = asyncio.run(service.preview(USER, payload()))["items"]
    assert preview["dup"] == {"type": "new"}
    for action in (service.preview, service.commit):
        with pytest.raises(ImportFailure) as denied:
            asyncio.run(action(USER, hidden))
        assert denied.value.status == 403
        assert original["id"] not in str(denied.value)
    forged = dict(preview, decision="version", dup={"type": "version", "id": original["id"]})
    with pytest.raises(ImportFailure) as conflict:
        asyncio.run(service.commit(USER, {"items": [forged]}))
    assert conflict.value.code == "VERSION_CONFLICT"
    assert docs(repository) == []
    assert docs(repository, "rules")[0]["status"] == "现行有效"


def test_explicit_version_conflict_rolls_back_entire_batch():
    service, repository = setup()
    first, = asyncio.run(service.commit(USER, payload()))["docs"]
    candidate, = asyncio.run(service.preview(USER, payload("第一条 有待确认的新版。")))["items"]
    asyncio.run(service.commit(USER, payload("第一条 另一份先提交的新版。"), one_step=True))
    new_doc, = payload("第一条 另一份文件。", title="其他工作方案")["items"]
    with pytest.raises(ImportFailure) as conflict:
        asyncio.run(service.commit(USER, {"items": [new_doc, dict(candidate, decision="version")]}))
    old, latest = docs(repository)
    assert conflict.value.status == 409
    assert old["id"] == first["id"] and old["status"] == "已更新"
    assert latest["status"] == "现行有效" and latest["version"] == 2


def test_insert_failure_rolls_back_old_version_update():
    service, repo = setup()
    asyncio.run(service.commit(USER, payload()))
    initial = docs(repo)

    class FailingRepository(MemoryImportRepository):
        @contextmanager
        def transaction(self, *, write):
            with super().transaction(write=write) as view:
                if write:
                    def fail(document):
                        assert view.candidates("policy")[0]["status"] == "已更新"
                        raise RuntimeError("模拟写入失败")

                    view.insert = fail
                yield view

    service, repo = setup(repository=FailingRepository(initial))
    with pytest.raises(RuntimeError, match="模拟写入失败"):
        asyncio.run(service.commit(USER, payload("第一条 新内容。"), one_step=True))
    assert docs(repo) == initial


def test_concurrent_and_in_batch_duplicates_use_current_write_view():
    service, repository = setup()
    item, = payload()["items"]

    def commit():
        return asyncio.run(service.commit(USER, {"items": [item, item]}))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(commit) for _ in range(2)]
        results = [future.result() for future in futures]
    assert len(docs(repository)) == 1
    assert sorted(len(result["skipped"]) for result in results) == [1, 2]


def test_two_revisions_in_one_batch_return_final_status():
    service, repository = setup()
    items = [payload(text)["items"][0] for text in ("第一条 第一版。", "第一条 第二版。")]
    result = asyncio.run(service.commit(USER, {"items": items}, one_step=True))
    first, latest = result["docs"]
    assert first["status"] == "已更新" and first["replacedBy"] == latest["id"]
    assert [doc["status"] for doc in docs(repository)] == [first["status"], latest["status"]]


def test_new_ignores_client_hint_and_both_skip_forms():
    service, repository = setup()
    original, = asyncio.run(service.commit(USER, payload()))["docs"]
    item, = payload("第一条 全新的正文。")["items"]
    response = asyncio.run(service.commit(USER, {"items": [
        dict(item, decision="new", dup={"type": "duplicate", "id": original["id"]}),
        {"name": "待跳过一", "decision": "skip"},
        {"name": "待跳过二", "decision": "new", "skip": True},
    ]}))
    assert [doc["version"] for doc in docs(repository)] == [1, 1]
    assert [entry["name"] for entry in response["skipped"]] == ["待跳过一", "待跳过二"]


@pytest.mark.parametrize("classification", ["confidential", "invalid"])
def test_batch_classification_is_not_downgraded_by_item(classification):
    remote = AsyncMock(return_value="出域桩")
    service, _ = setup(remote_parser=remote)
    items = [dict(name="样本.txt", fileIndex=0, classification="public")]
    files = [Upload("样本.txt", "第一条 测试。".encode())]
    data = {"items": items, "classification": classification}
    if classification == "invalid":
        with pytest.raises(ImportFailure, match="密级"):
            asyncio.run(service.preview(USER, data, files=files))
    else:
        item, = asyncio.run(service.preview(USER, data, files=files))["items"]
        assert item["text"] == "第一条 测试。"
        assert item["classification"] == "confidential"
    remote.assert_not_called()

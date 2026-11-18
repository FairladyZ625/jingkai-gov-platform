import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("fastapi", reason="HTTP 测试需要运行依赖 requirements-dev.txt")
pytest.importorskip("httpx")
pytest.importorskip("python_multipart")

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from jkq.kb.importer.public_url import PublicURLReader
from jkq.kb.importer.repository import MemoryImportRepository
from jkq.kb.importer.routes import build_router
from jkq.kb.importer.service import ImportService, SpaceAccess

PREFIX = "/api/v1/kb/import"
SAMPLES = Path(__file__).resolve().parents[4] / "tests/fixtures/kb_import"
GRANTS = {
    "writer": SpaceAccess(frozenset({"policy", "rules"}), frozenset({"policy"})),
    "blind-writer": SpaceAccess(frozenset({"rules"}), frozenset({"policy"})),
}


def make_client(*, remote_parser=None, **kwargs):
    repository = MemoryImportRepository()
    service = ImportService(repository, lambda user: GRANTS[user.id],
                            parser_for=lambda *_: remote_parser, **kwargs)
    app = FastAPI()

    def current_user(request: Request):
        user = request.headers.get("x-test-user", "writer")
        if user == "expired":
            raise HTTPException(401, "会话失效")
        return SimpleNamespace(id=user) if user in GRANTS else None

    app.include_router(build_router(service, current_user))
    return TestClient(app), repository


def documents(repository):
    with repository.transaction(write=False) as view:
        return view.candidates("policy")


def code(response, status, expected):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == expected and error["details"] == {}
    assert any("\u4e00" <= letter <= "\u9fff" for letter in error["message"])
    return error


def upload(client, route, item, file, **batch):
    return client.post(PREFIX + route, data={"payload": json.dumps({"items": [item], **batch})},
                       files=[("file", file)])


def test_actual_pdf_preview_and_two_pdf_commits():
    if not shutil.which("pdftotext"):
        pytest.skip("实际 PDF 解析需要 Poppler 的 pdftotext")
    client, repository = make_client()
    file = ("policy.pdf", (SAMPLES / "policy.pdf").read_bytes(), "application/pdf")
    item = {"fileIndex": 0, "key": "slot", "text": "不能覆盖上传文件"}
    response = upload(client, "/preview", item, file)
    assert response.status_code == 200, response.text
    preview, = response.json()["items"]
    assert preview["key"] == "slot" and preview["dup"] == {"type": "new"}
    assert preview["text"] == (SAMPLES / "policy.txt").read_text().strip()
    assert documents(repository) == []

    first = upload(client, "/commit", item, file)
    second = upload(client, "/commit", dict(item, decision="new"), file)
    assert first.status_code == second.status_code == 200
    saved, = documents(repository)
    assert first.json()["docs"][0]["id"] == saved["id"]
    assert second.json() == dict(docs=[], chunks=0, skipped=[dict(name="policy.pdf", reason="已在库中")])
    assert [chunk["head"] for chunk in saved["chunkList"] if chunk["head"]] == ["第一条", "第十二条"]
    assert saved["source"]["url"] == "https://example.invalid/reading"


def test_json_preview_commit_roundtrip_with_edited_fields_and_client_projection():
    client, repository = make_client()
    data = {"items": [{"key": "doc1", "name": "样本", "text": "第一条 起始正文。", "from": "对话"}]}
    response = client.post(PREFIX + "/preview", json=data)
    assert response.status_code == 200, response.text
    item, = response.json()["items"]
    assert item["key"] == "doc1" and item["ok"] and item["from"] == "对话"
    item["meta"].update(title="编辑后的标题", status="已失效")
    body = {"items": [dict(item, file={}, decision="new", skip=False)]}
    response = client.post(PREFIX + "/commit", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["docs"][0]["title"] == "编辑后的标题"
    assert documents(repository)[0]["status"] == "已失效"


def test_multipart_files_bound_by_zero_based_index():
    client, _ = make_client()
    files = [("file", ("一.txt", "第一条 第一份。".encode())), ("file", ("二.txt", "第二条 第二份。".encode()))]
    items = [{"fileIndex": 1, "key": "second"}, {"fileIndex": 0, "key": "first"}]
    body = {"payload": json.dumps({"items": items})}
    response = client.post(PREFIX + "/preview", data=body, files=files)
    assert response.status_code == 200, response.text
    assert [(item["key"], item["text"]) for item in response.json()["items"]] == [
        ("second", "第二条 第二份。"), ("first", "第一条 第一份。"),
    ]
    items[1]["fileIndex"] = 1
    body["payload"] = json.dumps({"items": items})
    code(client.post(PREFIX + "/preview", data=body, files=files), 422, "CHECK_FAILED")
    code(client.post(PREFIX + "/commit", json={"items": items}), 422, "CHECK_FAILED")


def test_single_multipart_file_needs_no_metadata():
    client, _ = make_client()
    response = client.post(PREFIX + "/preview", files={"file": ("sample.txt", "第一条 上传正文。".encode())})
    assert response.status_code == 200
    assert response.json()["items"][0]["text"] == "第一条 上传正文。"


def test_import_request_size_and_batch_limits(monkeypatch):
    client, repository = make_client()
    data = {"items": [{"name": "样本", "text": "正文"}] * 33}
    code(client.post(PREFIX + "/preview", json=data), 422, "CHECK_FAILED")
    monkeypatch.setattr("jkq.kb.importer.routes.MAX_REQUEST", 256)
    code(client.post(PREFIX + "/commit", json=data), 413, "REQUEST_TOO_LARGE")
    file = ("sample.txt", b"x" * 256)
    code(upload(client, "/commit", {"fileIndex": 0}, file), 413, "REQUEST_TOO_LARGE")
    assert documents(repository) == []


def test_parse_failure_has_readable_reason_and_bytes_take_precedence():
    client, repository = make_client()
    response = upload(client, "/preview", {"fileIndex": 0, "text": "兜底正文"},
                      ("坏.pdf", b"broken", "application/pdf"))
    assert "文件头损坏" in code(response, 422, "PARSE_FAILED")["message"]
    assert documents(repository) == []


@pytest.mark.parametrize("identity,status,expected", [
    ("unknown", 401, "UNAUTHENTICATED"), ("expired", 401, "UNAUTHENTICATED"),
    ("blind-writer", 403, "FORBIDDEN"), ("writer", 403, "FORBIDDEN"),
])
def test_permission_denied_before_parser_and_dns(identity, status, expected):
    parser = AsyncMock(return_value="解析结果")
    resolve = AsyncMock(return_value=["8.8.8.8"])
    client, _ = make_client(remote_parser=parser, reader=PublicURLReader(resolve=resolve))
    headers = {"x-test-user": identity}
    data = {"items": [{"name": "样本.txt", "text": "正文", "meta": {"space": "rules"}}]}
    for endpoint in ("/preview", "/commit", ""):
        code(client.post(PREFIX + endpoint, json=data, headers=headers), status, expected)
    code(client.post(PREFIX + "/url", json={"url": "https://example.invalid/", "space": "rules"},
                     headers=headers), status, expected)
    parser.assert_not_called()
    resolve.assert_not_called()


def test_unknown_fields_and_classification_fail_closed():
    parser = AsyncMock(return_value="解析结果")
    client, _ = make_client(remote_parser=parser)
    file = ("样本.txt", "第一条 本地解析正文。".encode(), "text/plain")
    for item in (
        {"fileIndex": 0, "classification": "机密"},
        {"fileIndex": 0, "meta": {"classification": "confidential"}},
        {"fileIndex": 0, "hash": "客户端提供"},
    ):
        code(upload(client, "/preview", item, file), 422, "CHECK_FAILED")
    parser.assert_not_called()


def test_duplicate_classification_in_multipart_cannot_override_confidential():
    parser = AsyncMock(return_value="出域解析桩正文")
    client, _ = make_client(remote_parser=parser)
    response = client.post(
        PREFIX + "/preview",
        data={"payload": '{"items":[{"fileIndex":0,"classification":"confidential","classification":"public"}]}'},
        files={"file": ("sample.txt", b"sample")},
    )
    code(response, 422, "CHECK_FAILED")
    parser.assert_not_called()


def test_confidential_opt_out_covers_preview_commit_and_one_step():
    parser = AsyncMock(return_value="出域解析桩正文。")
    client, repository = make_client(remote_parser=parser)
    file = ("样本.txt", "第一条 本地解析正文。".encode(), "text/plain")
    item = {"fileIndex": 0, "classification": "confidential"}
    for endpoint in ("/preview", "/commit", ""):
        response = upload(client, endpoint, item, file)
        assert response.status_code == 200, response.text
    assert documents(repository)[0]["classification"] == "confidential"
    assert documents(repository)[0]["text"] == "第一条 本地解析正文。"
    parser.assert_not_called()

    response = upload(client, "/preview", dict(item, classification="public"), file)
    assert response.json()["items"][0]["text"] == "出域解析桩正文。"
    parser.assert_awaited_once_with("样本.txt", "txt", file[1], "public")


class WebResponse:
    status_code = 200
    headers = {"content-type": "text/html; charset=utf-8"}
    charset_encoding = "utf-8"

    async def aiter_raw(self):
        yield ("<html><head><title>星汀试验区阅读办法</title></head><body>"
               "<p>第一条 网页正文。</p><script>非正文</script></body></html>").encode()


def test_web_preview_is_read_only_and_one_step_accepts_items_text_url():
    @asynccontextmanager
    async def request(target):
        assert str(target.address) == "8.8.8.8"
        yield WebResponse()

    resolve = AsyncMock(return_value=["8.8.8.8"])
    client, repository = make_client(reader=PublicURLReader(resolve=resolve, open_response=request))
    url = "https://example.invalid/reading"
    response = client.post(PREFIX + "/url", json={"url": url})
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["snapshot"] is False and page["item"]["url"] == url
    assert page["item"]["text"] == "第一条 网页正文。"
    assert page["item"]["meta"]["title"] == "星汀试验区阅读办法"
    assert documents(repository) == []

    result = client.post(PREFIX, json={
        "items": [{"name": "条目文字", "text": "第一条 条目正文。"}],
        "text": "第一条 粘贴正文。", "title": "粘贴标题",
        "url": url, "space": "policy", "from": "对话",
    })
    assert result.status_code == 200, result.text
    assert result.json()["chunks"] == 3 and result.json()["skipped"] == []
    assert {d["text"] for d in documents(repository)} == {
        "第一条 条目正文。", "第一条 粘贴正文。", "第一条 网页正文。",
    }
    assert result.json()["docs"][2]["source"]["url"] == url


@pytest.mark.parametrize("phase,status,expected", [
    ("forbidden", 400, "URL_NOT_ALLOWED"), ("redirect", 400, "URL_NOT_ALLOWED"),
    ("fetch", 502, "URL_FETCH_FAILED"), ("timeout", 504, "URL_FETCH_TIMEOUT"),
])
def test_url_errors_keep_public_envelope(phase, status, expected):
    async def resolve(host, port):
        if phase == "timeout":
            await asyncio.Event().wait()
        return ["8.8.8.8"]

    @asynccontextmanager
    async def request(target):
        if phase == "redirect":
            yield SimpleNamespace(status_code=302, headers={"location": "http://192.168.1.5/"})
        else:
            yield SimpleNamespace(status_code=503, headers={})

    reader = PublicURLReader(resolve=resolve, open_response=request, timeout=0.05)
    client, repository = make_client(reader=reader)
    url = "file:///not-allowed" if phase == "forbidden" else "https://example.invalid/"
    for route in ("/url", ""):
        code(client.post(PREFIX + route, json={"url": url}), status, expected)
    assert documents(repository) == []

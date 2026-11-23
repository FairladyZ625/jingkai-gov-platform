"""用现有实例、会话及 SQLite 验证导入装配。"""

import json
from pathlib import Path
import shutil
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from haiknow_core.aihub import adapters
from jkq.app import create_app
from jkq.kb.importer.public_url import PublicURLError, PublicURLReader

PREFIX = "/api/v1/kb"
FIXTURES = Path(__file__).resolve().parents[4] / "tests/fixtures/kb_import"


@pytest.fixture
def boot(tmp_path, monkeypatch, cheap_password_hash):
    monkeypatch.setenv("HAIKNOW_DATA_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("HAIKNOW_APPS_DIR", str(tmp_path / "apps"))
    monkeypatch.setenv("HAIKNOW_SECRET", "isolated-test-signing-value")
    monkeypatch.delenv("HAIKNOW_DEMO_LOGIN", raising=False)
    monkeypatch.setenv("JKQ_DEMO_MODE", "1")
    for role in ("admin", "leader", "member", "partner"):
        monkeypatch.setenv(f"JKQ_DEMO_{role.upper()}_PASSWORD", f"test-{role}")

    def start():
        app = create_app()
        return TestClient(app), app.state.platform

    return start


def login(client, partner=False):
    user, password = ("hejun", "test-partner") if partner else ("wangmin", "test-member")
    assert client.post("/api/v1/auth/login", json={"username": user, "password": password}).status_code == 200


@pytest.mark.parametrize("origin,space,size,status", [
    ("公文协作", "template", 24576, 200),
    ("政策匹配", "policy", 24576, 200),
    ("公文协作", "template", "24 KB", 422),
    ("未知来源", "policy", 24576, 422),
])
def test_one_step_import_from_apps(boot, monkeypatch, origin, space, size, status):
    read = AsyncMock()
    monkeypatch.setattr(PublicURLReader, "read", read)
    client, _ = boot()
    login(client)
    response = client.post(PREFIX + "/import", json={
        "items": [{"name": "协作样本.txt", "text": "第一条 样本正文。", "size": size}],
        "from": origin, "space": space, "text": None, "title": None, "url": None,
    })
    assert response.status_code == status, response.text
    if status == 200:
        doc, = response.json()["docs"]
        assert (doc["from"], doc["space"]) == (origin, space)
    else:
        assert response.json()["error"]["code"] == "CHECK_FAILED"
    read.assert_not_awaited()


@pytest.mark.parametrize("failure,status,code", [
    (RuntimeError("reader-internal-diagnostic"), 502, "URL_FETCH_FAILED"),
    (PublicURLError(400, "URL_NOT_ALLOWED", "不允许读取此网址"), 400, "URL_NOT_ALLOWED"),
    (PublicURLError(504, "URL_FETCH_TIMEOUT", "读取网页超时"), 504, "URL_FETCH_TIMEOUT"),
])
def test_import_url_reader_errors(boot, monkeypatch, failure, status, code):
    read = AsyncMock(side_effect=failure)
    monkeypatch.setattr(PublicURLReader, "read", read)
    client, _ = boot()
    login(client)
    url = "https://example.invalid/sample"
    for route in ("/import", "/import/url"):
        response = client.post(PREFIX + route, json={"url": url})
        assert response.status_code == status, response.text
        error = response.json()["error"]
        assert error["code"] == code and error["details"] == {}
        if isinstance(failure, PublicURLError):
            assert error["message"] == str(failure)
        else:
            assert str(failure) not in response.text
            assert any("\u4e00" <= char <= "\u9fff" for char in error["message"])
        read.assert_awaited_once_with(url)
        read.reset_mock()


def test_import_uses_same_documents_database_with_version_links_and_audit(boot):
    client, platform = boot()
    path = PREFIX + "/import"
    doc_path = PREFIX + "/docs"
    data = {"items": [{
        "name": "policy.txt", "text": (FIXTURES / "policy.txt").read_text(), "meta": {"space": "policy"},
    }]}
    assert client.post(path + "/preview", json=data).status_code == 401
    login(client, partner=True)
    assert client.post(path + "/preview", json=data).status_code == 403
    login(client)
    before = client.get(doc_path).json()["total"]
    first = client.post(path + "/preview", json=data)
    assert first.status_code == 200, first.text
    assert client.get(doc_path).json()["total"] == before

    old, = client.post(path + "/commit", json=first.json()).json()["docs"]
    assert client.get(doc_path).json()["total"] == before + 1
    second = {"items": [dict(data["items"][0], text=data["items"][0]["text"] + "\n新增附则。")]}
    preview, = client.post(path + "/preview", json=second).json()["items"]
    assert preview["dup"]["id"] == old["id"]
    assert preview["dup"]["type"] == "version"
    version = {"items": [dict(preview, decision="version")]}
    new, = client.post(path + "/commit", json=version).json()["docs"]
    assert new["version"] == 2 and new["prev"] == old["id"]
    assert client.post(path + "/commit", json=version).json()["skipped"]
    assert [entry["action"] for entry in platform.store.audit_list("kb")][:2] == ["import.version", "import.new"]

    client, _ = boot()
    login(client)
    original = client.get(f"{doc_path}/{old['id']}").json()["item"]
    latest = client.get(f"{doc_path}/{new['id']}").json()["item"]
    assert (original["status"], original["replacedBy"]) == ("已更新", new["id"])
    assert latest["source"] == {
        "org": "星汀虚构阅读中心", "date": "2026-03-08", "docNo": "星阅发〔2026〕7号",
        "url": "https://example.invalid/reading",
    }
    assert [entry["head"] for entry in latest["importChunks"] if entry["head"]] == ["第一条", "第十二条"]
    assert latest["text"].endswith("新增附则。")


def test_configured_mineru_only_reads_public_pdf_in_policy_space(boot, monkeypatch):
    if not shutil.which("pdftotext"):
        pytest.skip("本地 PDF 解析需要 pdftotext")
    client, platform = boot()
    login(client)
    settings = platform.model.aihub.settings
    settings.put_provider("test-mineru", "mineru", "https://example.invalid", ["test-parse"], True)
    settings.put_route("parse", "test-mineru", "test-parse")
    mineru = AsyncMock(return_value={"blocks": [{"text": "第一条 模拟 MinerU 解析结果。"}]})
    monkeypatch.setattr(adapters, "mineru_parse", mineru)
    pdf = (FIXTURES / "policy.pdf").read_bytes()
    file = {"file": ("policy.pdf", pdf)}

    def preview(classification, space="policy"):
        response = client.post(PREFIX + "/import/preview", files=file, data={
            "payload": json.dumps({"items": [{"fileIndex": 0}], "classification": classification, "space": space}),
        })
        assert response.status_code == 200, response.text
        return response.json()["items"][0]

    assert preview("public")["text"] == (FIXTURES / "policy.txt").read_text().strip()
    mineru.assert_not_called()
    monkeypatch.setenv("HAIKNOW_PROVIDER_TEST_MINERU_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("HAIKNOW_PROVIDER_TEST_MINERU_API_KEY", "test-placeholder-key")
    assert preview("public")["text"] == "第一条 模拟 MinerU 解析结果。"
    assert mineru.await_args.args[2]["data"] == pdf
    assert preview("internal")["text"] != "第一条 模拟 MinerU 解析结果。"
    assert preview("confidential")["classification"] == "confidential"
    assert preview("public", "enterprise")["classification"] == "confidential"
    mineru.assert_awaited_once()

import shutil
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from urllib.parse import unquote

import pytest

from jkq.attachments.service import MAX_BYTES, InputError, fallback_apps, prepare


MANIFESTS = fallback_apps(None)["items"]


@pytest.mark.parametrize(("name", "data", "kind", "app"), [
    ("现场.MP3", b"audio", "audio", "meeting"), ("录音.m4a", b"audio", "audio", "meeting"),
    ("经开〔2026〕3号.pdf", b"%PDF", "policy", "policy"),
    ("企业材料.xlsx", b"x", "visit", "enterprise"), ("通知.txt", b"x", "document", "document"),
    ("普通.pdf", b"x", "unknown", None), ("样本.txt", "实施办法".encode(), "policy", "policy"),
])
def test_routing(name, data, kind, app):
    item, route = prepare("file", name, data, MANIFESTS)
    assert (item["kind"], route["app"]) == (kind, app)
    if kind == "policy":
        assert route["alsoImport"] == {"lib": "policy"}
    if kind == "unknown":
        assert route["action"] == "ask" and "alsoImport" not in route


def test_uses_visible_manifest_and_size_boundary():
    manifests = [{"id": "enterprise", "accepts": [{"ext": ["pdf"], "match": "品牌"}]}]
    assert prepare("file", "品牌.pdf", b"x", manifests)[1]["app"] == "enterprise"
    assert prepare("file", "经开〔2026〕3号.pdf", b"x", manifests)[0]["kind"] == "unknown"
    assert prepare("file", "a.pdf", bytes(MAX_BYTES), MANIFESTS)[0]["size"] == MAX_BYTES
    with pytest.raises(InputError) as err:
        prepare("file", "a.pdf", bytes(MAX_BYTES + 1), MANIFESTS)
    assert (err.value.status, err.value.code) == (413, "FILE_TOO_LARGE")


@pytest.fixture
def clients(request):
    pytest.importorskip("fastapi")
    from haiknow_core.main import current_user
    from jkq.attachments.routes import install
    from jkq.conversations.store import ConversationNotFound, ConversationStore

    make_client = request.getfixturevalue("make_client")
    store = ConversationStore(make_client().app.state.platform.store)
    cid = store.create("sampleadmin")["id"]

    def reopen(user="sampleadmin"):
        client = make_client()
        plat = client.app.state.platform
        install(client.app, plat, current_user, ConversationStore(plat.store),
                app_id="sample-app", project="sample-project", not_found=ConversationNotFound)
        assert client.post("/api/auth/login", json={"user_id": user}).is_success
        return client
    return reopen, store, cid


def test_persisted_message_and_download(clients):
    reopen, store, cid = clients
    base = f"/api/v1/conversations/{cid}/attachments"
    name = "经开〔2026〕8号 政策.pdf"
    data = b"%PDF-1.4\n" + bytes(range(256))
    result = reopen().post(base, files={"files[]": (name, data)})
    assert result.is_success, result.text
    item, = result.json()["items"]
    route, = result.json()["routes"]
    assert route["app"] == "policy" and route["alsoImport"]["lib"] == "policy"
    message, = store.detail("sampleadmin", cid)["messages"]
    assert (message["attachments"], message["routes"]) == ([item], [route])
    after = reopen()
    assert after.get(base).json()["items"] == [item]
    download = after.get(item["url"])
    assert download.content == data
    assert unquote(download.headers["Content-Disposition"].split("''")[1]) == name
    outsider = reopen("sampleextra")
    generic = "/api/v1/files/" + item["id"]
    for path in (generic, generic + "/content"):
        assert outsider.get(path).status_code == 404
    for response in (outsider.get(base), outsider.get(item["url"]),
                     outsider.post(base, data={"text": "样本"})):
        assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(("field", "value", "kind"), [
    ("url", "https://kfqgw.beijing.gov.cn/example", "policy"),
    ("text", "关于实施办法的说明", "policy"),
    ("url", "https://example.org/sample", "unknown"),
])
def test_paste(clients, field, value, kind):
    base = f"/api/v1/conversations/{clients[2]}/attachments"
    response = clients[0]().post(base, data={field: value})
    assert response.is_success, response.text
    item, = response.json()["items"]
    route, = response.json()["routes"]
    assert item[field] == value and item["kind"] == kind
    assert route["attachmentId"] == item["id"]


@pytest.mark.parametrize(("name", "size", "status", "code"), [
    ("a.pdf", MAX_BYTES + 1, 413, "FILE_TOO_LARGE"),
    ("a.pdf", MAX_BYTES + 100000, 413, "FILE_TOO_LARGE"),
    ("样本.exe", 1, 415, "UNSUPPORTED_TYPE"),
])
def test_rejected_batch_leaves_no_message(clients, name, size, status, code):
    base = f"/api/v1/conversations/{clients[2]}/attachments"
    client = clients[0]()
    result = client.post(base, files=[("files[]", ("a.txt", b"x")), ("files[]", (name, bytes(size)))])
    assert result.status_code == status
    assert result.json()["error"]["code"] == code
    assert any("\u4e00" <= c <= "\u9fff" for c in result.json()["error"]["message"])
    assert client.get(base).json() == {"items": []}


def test_multi_attachment_suggestions_share_one_message(clients):
    reopen, store, cid = clients
    result = reopen().post(f"/api/v1/conversations/{cid}/attachments",
                           data={"url": "https://beijing.gov.cn/example", "text": "普通样本"}).json()
    message, = store.detail("sampleadmin", cid)["messages"]
    assert message["attachments"] == result["items"]
    assert message["routes"] == result["routes"]
    policy, unknown = result["routes"]
    assert policy["alsoImport"] == {"lib": "policy"}
    assert unknown["action"] == "ask" and "alsoImport" not in unknown


def test_visible_custom_manifest():
    rule = {"ext": ["csv"], "match": "巡检"}
    apps = [{"id": "hidden", "available": False, "accepts": [rule]},
            {"id": "inspection", "available": True, "accepts": [rule]}]
    assert prepare("file", "巡检.csv", b"x", apps)[1]["app"] == "inspection"
    assert prepare("file", "普通.csv", b"x", apps)[1]["action"] == "ask"


def sample_pdf(text):
    """用 ToUnicode 把 # 映射为「号」，构造包含可提取文号的单页 PDF。"""
    def stream(data):
        return b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 6 0 R >>",
        stream(b"BT /F1 12 Tf 20 100 Td (" + text + b") Tj ET"),
        stream(b"begincmap 1 begincodespacerange <00> <FF> endcodespacerange "
               b"1 beginbfrange <20> <7E> <0020> endbfrange "
               b"1 beginbfchar <23> <53F7> endbfchar endcmap"),
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(b"%d 0 obj\n" % index + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(b"xref\n0 7\n0000000000 65535 f \n")
    for offset in offsets:
        data.extend(b"%010d 00000 n \n" % offset)
    data.extend(b"trailer << /Size 7 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % xref)
    return bytes(data)


def _has_working_pdftotext():
    if shutil.which("pdftotext") is None:
        return False
    try:
        result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "1", "-enc", "UTF-8", "-", "-"],
            input=sample_pdf(b"sample"),
            capture_output=True,
            timeout=4,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.parametrize(("text", "app"), [(b"[2026]8#", "policy"), (b"sample", None)])
def test_pdf_body(text, app):
    if not _has_working_pdftotext():
        pytest.skip("需要可用的 pdftotext 才能核验 PDF 正文文号")
    item, route = prepare("file", "材料.pdf", sample_pdf(text), MANIFESTS)
    assert route["app"] == app
    if app:
        assert item["kind"] == "policy" and route["alsoImport"] == {"lib": "policy"}
    else:
        assert item["kind"] == "unknown" and route["action"] == "ask"


@pytest.mark.parametrize("multipart", [True, False])
@pytest.mark.parametrize("over", [0, 1])
def test_chinese_form_limit(clients, multipart, over):
    reopen, _, cid = clients
    size = MAX_BYTES + over
    text = "中" * (size // 3) + "a" * (size % 3)
    fields = {"files": {"text": (None, text)}} if multipart else {"data": {"text": text}}
    response = reopen().post(f"/api/v1/conversations/{cid}/attachments", **fields)
    if over:
        assert response.status_code == 413 and response.json()["error"]["code"] == "FILE_TOO_LARGE"
    else:
        assert response.status_code == 200 and response.json()["items"][0]["text"] == text


@pytest.mark.parametrize("failure", ["second_file", "message"])
def test_rollback_and_retry(clients, failure):
    reopen, store, cid = clients
    client = reopen()
    base = f"/api/v1/conversations/{cid}/attachments"
    table = "jkq_attachment_content" if failure == "second_file" else "jkq_messages"
    condition = "when (select count(*) from jkq_attachment_content)=1" if failure == "second_file" else ""
    with store.transaction(write=True):
        store.db.execute(f"create trigger fail_write before insert on {table} {condition} "
                         "begin select raise(abort, '模拟写入失败'); end")
    files = [("files[]", ("一.txt", b"one")), ("files[]", ("二.txt", b"two"))]
    with pytest.raises(sqlite3.IntegrityError, match="模拟写入失败"):
        client.post(base, files=files)
    assert store.db.execute("select count(*) from jkq_attachment_content").fetchone() == (0,)
    assert store.detail("sampleadmin", cid)["messages"] == []
    with store.transaction(write=True):
        store.db.execute("drop trigger fail_write")
    assert client.post(base, files=files).status_code == 200
    assert store.db.execute("select count(*) from jkq_attachment_content").fetchone() == (2,)
    assert len(store.detail("sampleadmin", cid)["messages"]) == 1


def test_deleted_while_uploading(clients, monkeypatch):
    from jkq.attachments import service

    reopen, store, cid = clients
    client = reopen()
    base = f"/api/v1/conversations/{cid}/attachments"
    ready, deleted = Event(), Event()
    original = service.prepare

    def prepare(*args):
        ready.set()
        assert deleted.wait(5)
        return original(*args)

    monkeypatch.setattr(service, "prepare", prepare)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(client.post, base, files={"files[]": ("文件.txt", b"test")})
        assert ready.wait(5)
        store.set_deleted("sampleadmin", cid, deleted=True)
        deleted.set()
        assert future.result().status_code == 404
    assert store.db.execute("select count(*) from jkq_attachment_content").fetchone() == (0,)
    store.set_deleted("sampleadmin", cid, deleted=False)
    assert store.detail("sampleadmin", cid)["messages"] == []

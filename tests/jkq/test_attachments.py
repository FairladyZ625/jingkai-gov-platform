import json
from urllib.parse import unquote

import pytest

from jkq.attachments.service import MAX_BYTES, InputError, fallback_apps, prepare

BASE = "/api/v1/conversations/demo/attachments"
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


class Conversations:
    """可重开的消息文件模拟 #21 的两个公共方法。"""
    def __init__(self, path):
        self.path = path

    def detail(self, owner, cid):
        if (owner, cid) != ("sampleadmin", "demo"):
            raise KeyError(cid)
        return {"messages": json.loads(self.path.read_text()) if self.path.exists() else []}

    def append_message(self, owner, cid, **message):
        history = self.detail(owner, cid)["messages"]
        self.path.write_text(json.dumps(history + [message]))


@pytest.fixture
def clients(tmp_path, request):
    pytest.importorskip("fastapi")
    from haiknow_core.main import current_user
    from jkq.attachments.routes import install
    make_client = request.getfixturevalue("make_client")
    store = Conversations(tmp_path / "history.json")

    def reopen(user="sampleadmin"):
        client = make_client()
        install(client.app, client.app.state.platform, current_user, store,
                app_id="sample-app", project="sample-project", not_found=KeyError)
        assert client.post("/api/auth/login", json={"user_id": user}).is_success
        return client
    return reopen, store


def test_persisted_message_and_download(clients):
    reopen, store = clients
    name = "经开〔2026〕8号 政策.pdf"
    data = b"%PDF-1.4\n" + bytes(range(256))
    result = reopen().post(BASE, files={"files[]": (name, data)})
    assert result.is_success, result.text
    item, = result.json()["items"]
    route, = result.json()["routes"]
    assert route["app"] == "policy" and route["alsoImport"]["lib"] == "policy"
    message, = Conversations(store.path).detail("sampleadmin", "demo")["messages"]
    assert (message["attachments"], message["routes"]) == ([item], [route])
    after = reopen()
    assert after.get(BASE).json()["items"] == [item]
    download = after.get(item["url"])
    assert download.content == data
    assert unquote(download.headers["Content-Disposition"].split("''")[1]) == name
    outsider = reopen("sampleoperator")
    for response in (outsider.get(BASE), outsider.get(item["url"]),
                     outsider.post(BASE, data={"text": "样本"})):
        assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(("field", "value", "kind"), [
    ("url", "https://kfqgw.beijing.gov.cn/example", "policy"),
    ("text", "关于实施办法的说明", "policy"),
    ("url", "https://example.org/sample", "unknown"),
])
def test_paste(clients, field, value, kind):
    response = clients[0]().post(BASE, data={field: value})
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
    client = clients[0]()
    result = client.post(BASE, files=[("files[]", ("a.txt", b"x")), ("files[]", (name, bytes(size)))])
    assert result.status_code == status
    assert result.json()["error"]["code"] == code
    assert any("\u4e00" <= c <= "\u9fff" for c in result.json()["error"]["message"])
    assert client.get(BASE).json() == {"items": []}


def test_multi_attachment_suggestions_share_one_message(tmp_path):
    from types import SimpleNamespace
    from jkq.attachments.service import attachments, publish

    parts = [("url", "链接", "https://beijing.gov.cn/example"),
             ("text", "粘贴文本", "普通样本")]
    store = Conversations(tmp_path / "history.json")
    result = publish(SimpleNamespace(id="sampleadmin"), "demo", parts, store, None,
                     fallback_apps, "sample-app", "sample-project")
    history = Conversations(store.path).detail("sampleadmin", "demo")
    assert len(history["messages"]) == 1
    assert attachments(history) == result["items"]
    assert history["messages"][0]["routes"] == result["routes"]
    policy, unknown = result["routes"]
    assert policy["alsoImport"] == {"lib": "policy"}
    assert unknown["action"] == "ask" and "alsoImport" not in unknown

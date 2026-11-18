import pytest

from haiknow_core.store import Store
from jkq.conversations.store import ConversationNotFound, ConversationStore


BASE = "/api/v1/conversations"
PANEL = {"app": "policy", "route": "detail", "params": {"id": "PI-03"}}


@pytest.fixture
def conversation_client(request):
    pytest.importorskip("fastapi", reason="平台接口在安装 requirements-dev 的 core job 验证")
    from haiknow_core.main import current_user
    from jkq.conversations.routes import install

    client = request.getfixturevalue("make_client")()
    store = install(client.app, client.app.state.platform, current_user)
    return client, store


def test_durable_history_and_message(tmp_path):
    store = ConversationStore(Store(tmp_path))
    first = store.create("a", "政策", "policy")
    cid = first["id"]
    second = store.create("a")
    foreign = store.create("b")
    store.set_panel("a", cid, PANEL)
    fields = dict(role="assistant", content="文" * 20000,
                  cards=[{"type": "policy-match", "index": i} for i in range(10)],
                  citations=[{"fileId": "POL:PI-03", "name": "公开政策", "snippet": "条文"}],
                  model="sample", toolCalls=[{"tool": "policy.match", "args": {"id": 1}}])
    prompt = store.append_message("a", cid, role="user", content="问题")
    assert prompt["cards"] == prompt["citations"] == prompt["toolCalls"] == []
    reply = store.append_message("a", cid, **fields)
    assert {key: reply[key] for key in fields} == fields

    reopened = ConversationStore(Store(tmp_path))
    detail = reopened.detail("a", cid)
    assert detail["messages"] == [prompt, reply]
    assert detail["item"] == {**first, "panel": PANEL, "updated": reply["at"]}
    assert reopened.history("a", 1, 0) == {"items": [detail["item"]], "total": 2}
    assert reopened.history("a", 1, 1) == {"items": [second], "total": 2}
    assert reopened.history("a", 1, 2) == {"items": [], "total": 2}
    for inaccessible in (foreign["id"], "missing"):
        with pytest.raises(ConversationNotFound):
            store.append_message("a", inaccessible, role="user", content="问题")
    reopened.set_deleted("a", cid, deleted=True)
    assert store.history("a") == {"items": [second], "total": 1}
    with pytest.raises(ConversationNotFound):
        store.append_message("a", cid, role="user", content="问题")
    reopened.set_deleted("a", cid, deleted=False)
    assert store.detail("a", cid)["messages"] == [prompt, reply]


@pytest.mark.parametrize(("field", "value"), [
    ("cards", {"type": "policy-match"}),
    ("cards", {}),
    ("citations", "公开政策"),
    ("citations", ""),
    ("toolCalls", {"tool": "policy.match"}),
    ("toolCalls", False),
])
def test_append_rejects_non_array_without_changing_history(tmp_path, field, value):
    store = ConversationStore(Store(tmp_path))
    cid = store.create("a")["id"]
    prompt = store.append_message("a", cid, role="user", content="问题",
                                  cards=None, citations=None, toolCalls=None)
    assert prompt["cards"] == prompt["citations"] == prompt["toolCalls"] == []
    before = store.detail("a", cid)

    with pytest.raises(ValueError, match=field):
        store.append_message("a", cid, role="assistant", content="答复", **{field: value})

    assert store.detail("a", cid) == before


def test_authenticated_routes(conversation_client):
    from fastapi.testclient import TestClient

    alice, store = conversation_client
    other_tab = TestClient(alice.app)
    bob = TestClient(alice.app)
    anonymous = alice.get(BASE)
    assert (anonymous.status_code, anonymous.json()["error"]["code"]) == (401, "UNAUTHENTICATED")
    for client, uid in ((alice, "sampleoperator"), (other_tab, "sampleoperator"), (bob, "sampleadmin")):
        assert client.post("/api/auth/login", json={"user_id": uid}).status_code == 200
    item = alice.post(BASE, json={"app": "policy", "title": "政策"}).json()["item"]
    assert set(item) == {"id", "title", "app", "updated", "panel"}
    cid = item["id"]
    url = f"{BASE}/{cid}"
    message = store.append_message("sampleoperator", cid, role="user", content="条文")
    assert alice.patch(url, json={"panel": PANEL}).json()["item"]["panel"] == PANEL
    detail = other_tab.get(url).json()
    assert detail["item"]["panel"] == PANEL
    assert detail["messages"] == [message]
    assert alice.get(BASE, params={"limit": 0}).json() == {"items": [], "total": 1}
    for query in ({"limit": -1}, {"offset": -1}, {"limit": 2**63}):
        invalid = alice.get(BASE, params=query)
        assert (invalid.status_code, invalid.json()["error"]["code"]) == (422, "CHECK_FAILED")
    assert bob.get(BASE).json() == {"items": [], "total": 0}
    missing = bob.get(f"{BASE}/missing")
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "NOT_FOUND")
    for response in (bob.get(url), bob.patch(url, json={"panel": None}), bob.delete(url)):
        assert (response.status_code, response.json()) == (404, missing.json())
    assert alice.delete(url).status_code == 204
    assert other_tab.get(url).json() == missing.json()
    assert alice.get(BASE).json() == {"items": [], "total": 0}
    denied = bob.post(f"{url}/restore")
    assert (denied.status_code, denied.json()) == (404, missing.json())
    assert other_tab.post(f"{url}/restore").json()["item"]["panel"] == PANEL
    assert alice.get(url).json()["messages"] == [message]
    assert alice.get(BASE).json()["items"][0]["id"] == cid
    assert alice.patch(url, json={"panel": None}).json()["item"]["panel"] is None


def test_invalid_body_returns_check_failed_without_changing_history(conversation_client):
    client, store = conversation_client
    assert client.post("/api/auth/login", json={"user_id": "sampleoperator"}).status_code == 200
    nested_panel = {**PANEL, "params": {"id": "PI-03", "nested": [None, {"分数": 1.5, "说明": "政策😀", "可见": True}]}}
    created = client.post(BASE, json={"title": "政策😀", "panel": nested_panel})
    assert created.status_code == 200
    item = created.json()["item"]
    assert item["panel"] == nested_panel
    cid = item["id"]
    url = f"{BASE}/{cid}"
    store.append_message("sampleoperator", cid, role="user", content="条文")
    before_list = client.get(BASE).json()
    before_detail = client.get(url).json()

    # 使用原始 JSON 检查框架解码后的值，包括客户端默认序列化器拒绝的值。
    invalid_panels = [
        r'{"app":"\ud800","route":"detail","params":{}}',
        r'{"app":"policy","route":"\ud800","params":{}}',
        r'{"app":"policy","route":"detail","params":{"nested":[{"text":"\ud800"}]}}',
        r'{"app":"policy","route":"detail","params":{"nested":[{"\ud800":"text"}]}}',
        r'{"app":"policy","route":"detail","params":{"nested":[{"score":1e999}]}}',
    ]
    invalid_creates = [r'{"title":"\ud800"}', r'{"app":"\ud800"}']
    invalid_updates = ['{"panel":' + panel + '}' for panel in invalid_panels]
    headers = {"Content-Type": "application/json"}
    expected = {"error": {"code": "CHECK_FAILED", "message": "请求字段缺失或格式不正确", "details": {}}}
    for method, path, bodies in (("POST", BASE, invalid_creates + invalid_updates),
                                 ("PATCH", url, invalid_updates)):
        for body in bodies:
            response = client.request(method, path, content=body, headers=headers)
            assert (response.status_code, response.json()) == (422, expected), (method, body)
            assert client.get(BASE).json() == before_list
            assert client.get(url).json() == before_detail

    updated_panel = {**nested_panel, "route": "search"}
    updated = client.patch(url, json={"panel": updated_panel})
    assert updated.status_code == 200
    assert updated.json()["item"]["panel"] == updated_panel
    after = client.get(url).json()
    assert after["item"]["panel"] == updated_panel
    assert after["messages"] == before_detail["messages"]

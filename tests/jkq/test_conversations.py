import pytest

from haiknow_core.store import Store
from jkq.conversations.store import ConversationNotFound, ConversationStore


BASE = "/api/v1/conversations"
PANEL = {"app": "policy", "route": "detail", "params": {"id": "PI-03"}}


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


def test_authenticated_routes(request):
    pytest.importorskip("fastapi", reason="平台接口在安装 requirements-dev 的 core job 验证")
    from fastapi.testclient import TestClient
    from haiknow_core.main import current_user
    from jkq.conversations.routes import install

    alice = request.getfixturevalue('make_client')()
    store = install(alice.app, alice.app.state.platform, current_user)
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

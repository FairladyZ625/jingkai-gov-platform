import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("fastapi", reason="消息路由验证需要 requirements-dev.txt")

from fastapi.testclient import TestClient
from haiknow_core.main import current_user
from haiknow_core.store import Store
from haiknow_sdk import DataError
from starlette.requests import ClientDisconnect

from jkq.conversations.routes import install as install_conversations
from jkq.conversations.store import ConversationStore
from jkq.orchestrator.persistence import finish_turn, start_turn
from jkq.orchestrator.ports import ModelTurn, ToolCall
from jkq.orchestrator.routes import install


BASE = "/api/v1/conversations"
OWNER = "sampleoperator"
POLICY_RESULT = {"results": [{"id": "PI-01", "title": "演示条款", "level": "check"}]}
SOURCES = [{"id": "KB-1", "title": "公开演示政策", "snippet": "该示例用于测试出处。", "n": 1}]


class ScriptedGateway:
    def __init__(self):
        self.script = []
        self.requests = []

    async def __call__(self, request, **payload):
        self.requests.append(payload)
        assert self.script, "这轮不应继续调用模型"
        return self.script.pop(0)


class BridgeStub:
    def __init__(self):
        self.catalog = {
            "policy.match": False, "policy.search": False, "enterprise.get": False,
            "enterprise.search": False, "meeting.commit_todos": True, "kb.ask": False,
            "kb.search": False, "test.publish": True, "document.submit": False,
        }
        self.calls = []
        self.results = {
            "policy.match": POLICY_RESULT,
            "policy.search": {"items": [{"id": "PI-01"}]},
            "enterprise.get": {"item": {"id": "E002"}},
            "enterprise.search": {"items": [{"id": "E002"}]},
            "kb.ask": {"confidence": "high", "answer": "政策原文见 [1]。", "citations": SOURCES},
        }

    def tools(self, user):
        assert user.id == OWNER
        return {"items": [
            {"name": name, "app": name.partition(".")[0], "write": write}
            for name, write in self.catalog.items()
        ]}

    async def call_from_chat(self, request, app_id, tool, args):
        assert request.session.get("uid") == OWNER
        self.calls.append((app_id, tool, args))
        assert not self.catalog[tool], "写工具不得进入执行入口"
        result = self.results[tool]
        if isinstance(result, Exception):
            raise result
        return {"tool": tool, "result": result}


@pytest.fixture
def connected(make_client):
    client = make_client()
    client.app.state.conversations = install_conversations(client.app, client.app.state.platform, current_user)
    bridge, gateway = BridgeStub(), ScriptedGateway()
    client.app.state.apps_bridge = bridge
    install(client.app, current_user, gateway=gateway)
    assert client.post("/api/auth/login", json={"user_id": OWNER}).status_code == 200
    cid = client.post(BASE, json={}).json()["item"]["id"]
    return client, f"{BASE}/{cid}/messages", bridge, gateway


def test_rule_calls_tool_without_gateway_and_uses_previous_match_for_override(connected):
    client, url, bridge, gateway = connected
    first = client.post(url, json={"text": "书香里文化能申请哪些支持？", "files": [{"id": "F1"}]})
    assert first.status_code == 200
    assert first.json()["user"]["files"] == [{"id": "F1"}]
    assert first.json()["reply"]["intent"] == "policy"
    second = client.post(url, json={"text": "补填数据采购额 30 万"}).json()["reply"]
    assert bridge.calls == [
        ("policy", "policy.match", {"entId": "E001"}),
        ("policy", "policy.match", {"entId": "E001", "overrides": {"dataPurchase": 300000}}),
    ]
    assert second["cards"][0]["deepLink"] == {"app": "policy", "params": {"entId": "E001"}}
    assert not gateway.requests
    assert client.get(url.removesuffix("/messages")).json()["messages"][-1] == second


def test_policy_followup_with_unknown_target_requests_clarification(connected):
    client, url, bridge, gateway = connected
    reply = client.post(url, json={"text": "补填数据采购额 30 万"}).json()["reply"]
    assert reply["intent"] == "policy"
    assert "哪家企业" in reply["content"]
    assert not bridge.calls and not gateway.requests


def test_model_tool_name_and_args_sequence_snapshot(connected):
    client, url, bridge, gateway = connected
    gateway.script = [
        ModelTurn(("尚未执行的模型草稿",), (ToolCall("enterprise.search", {"q": "星河"}, "a"),)),
        ModelTurn(calls=(ToolCall("policy.match", {"entId": "E002"}, "b"),)),
        ModelTurn(("找到企业。", "请查看适用政策。"), model="configured-local", route_note="走本地"),
    ]
    response = client.post(url, json={"text": "看看星河的办理情况", "model": "configured-route"})
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert json.dumps(reply["toolCalls"], ensure_ascii=False, sort_keys=True) == (
        '[{"args": {"q": "星河"}, "status": "ok", "tool": "enterprise.search"}, '
        '{"args": {"entId": "E002"}, "status": "ok", "tool": "policy.match"}]'
    )
    assert bridge.calls == [
        ("enterprise", "enterprise.search", {"q": "星河"}),
        ("policy", "policy.match", {"entId": "E002"}),
    ]
    assert reply["content"] == "找到企业。请查看适用政策。"
    assert [card["type"] for card in reply["cards"]] == ["enterprise-list", "policy-match"]
    assert (reply["model"], reply["routeNote"]) == ("configured-local", "走本地")
    assert [payload["model"] for payload in gateway.requests] == ["configured-route"] * 3
    assert [payload["classification"] for payload in gateway.requests] == ["internal", "confidential", "confidential"]
    assert not {"kb.search", "admin.export"}.intersection(gateway.requests[0]["tools"])
    assert gateway.requests[1]["messages"][-2]["tool_calls"][0]["id"] == "a"
    last_tools = [item for item in gateway.requests[-1]["messages"] if item["role"] == "tool"]
    assert [(item["tool_call_id"], json.loads(item["content"])) for item in last_tools] == [
        ("a", {"items": [{"id": "E002"}]}), ("b", POLICY_RESULT),
    ]


@pytest.mark.parametrize("confidence", ["high", "none"])
def test_kb_uses_citations_or_reports_no_source_without_model(connected, confidence):
    client, url, bridge, gateway = connected
    bridge.results["kb.ask"]["confidence"] = confidence
    text = "知识库里有没有关于火星基地的政策？"
    reply = client.post(url, json={"text": text}).json()["reply"]
    assert bridge.calls == [("kb", "kb.ask", {"q": text})]
    assert not gateway.requests
    if confidence == "none":
        assert (reply["content"], reply["citations"], reply["cards"]) == (
            "知识库里没有找到能回答这个问题的原文。", [], [],
        )
    else:
        assert reply["citations"] == [{"fileId": "KB-1", "name": "公开演示政策", "snippet": SOURCES[0]["snippet"]}]
        assert reply["cards"][0]["deepLink"] == {"app": "kb", "params": {"fileId": "KB-1"}}


def test_model_selected_kb_cannot_substitute_its_answer(connected):
    client, url, bridge, gateway = connected
    gateway.script = [ModelTurn(("模型草稿",), (ToolCall("kb.ask", {"q": "相关背景"}),))]
    bridge.results["kb.ask"] = {"confidence": "none"}
    reply = client.post(url, json={"text": "多说一点相关的背景"}).json()["reply"]
    assert reply["content"] == "知识库里没有找到能回答这个问题的原文。"
    assert reply["toolCalls"][0]["status"] == "ok"
    assert len(gateway.requests) == 1


@pytest.mark.parametrize(("failure", "message"), [
    (DataError("FORBIDDEN", "内部错误详情"), "未能完成请求，当前账号没有权限。"),
    (TimeoutError("内部错误详情"), "未能完成请求，工具响应超时。"),
    (RuntimeError("内部错误详情"), "未能完成请求，工具服务暂不可用。"),
    ({"confidence": "high", "answer": "无引用答案", "citations": []}, "未能完成请求，工具返回了无法使用的结果。"),
])
def test_tool_failure_is_200_and_never_uses_model_to_recover(connected, failure, message):
    client, url, bridge, gateway = connected
    bridge.results["kb.ask"] = failure
    gateway.script = [ModelTurn(("未经核验的草稿",), (ToolCall("kb.ask", {"q": "背景"}),))]
    response = client.post(url, json={"text": "多说一点相关的背景"})
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert reply["content"] == message
    assert reply["toolCalls"] == [{"tool": "kb.ask", "args": {"q": "背景"}, "status": "error"}]
    assert not reply["cards"] and not reply["citations"]
    assert len(gateway.requests) == 1


def test_explicit_app_skips_rule_and_filters_available_tools(connected):
    client, url, bridge, gateway = connected
    gateway.script = [
        ModelTurn(calls=(ToolCall("enterprise.get", {"id": "E002"}),)),
        ModelTurn(("请查看企业档案。",)),
    ]
    response = client.post(url, json={"text": "书香里文化能申请哪些支持？", "app": "enterprise"})
    assert response.status_code == 200
    assert response.json()["reply"]["intent"] == "enterprise"
    assert gateway.requests[0]["tools"] == ["enterprise.get", "enterprise.search"]
    assert bridge.calls == [("enterprise", "enterprise.get", {"id": "E002"})]


def test_model_cannot_call_tools_outside_the_user_supplied_app(connected):
    client, url, bridge, gateway = connected
    gateway.script = [ModelTurn(calls=(ToolCall("policy.match", {"entId": "E001"}),))]
    reply = client.post(url, json={"text": "帮我看看", "app": "enterprise"}).json()["reply"]
    assert reply["toolCalls"][0]["status"] == "error"
    assert not bridge.calls


@pytest.mark.parametrize(("text", "tool", "args"), [
    ("把座谈会的待办派发下去", "meeting.commit_todos", {"meetingId": "MT-1112"}),
    ("送审签", "document.submit", {}),
    ("执行这项工作", "test.publish", {"id": "S-1"}),
])
def test_write_tools_only_create_pending_intent(connected, text, tool, args):
    client, url, bridge, gateway = connected
    if tool == "test.publish":
        gateway.script = [ModelTurn(("已写入",), (ToolCall(tool, args),))]
    reply = client.post(url, json={"text": text}).json()["reply"]
    assert reply["toolCalls"] == [{"tool": tool, "args": args, "status": "pending"}]
    assert reply["content"] == "这项操作需要你确认。"
    assert not bridge.calls


def test_registry_revalidates_read_that_became_write(connected):
    client, url, bridge, gateway = connected
    bridge.results["policy.match"] = {"status": "pending", "reviewId": "TEST-REVIEW"}
    reply = client.post(url, json={"text": "书香里文化能申请哪些支持？"}).json()["reply"]
    assert reply["toolCalls"][0]["status"] == "pending"
    assert reply["toolCalls"][0]["reviewId"] == "TEST-REVIEW"
    assert reply["cards"] == []
    assert not gateway.requests


def test_model_loop_terminates_at_round_limit(connected):
    client, url, bridge, gateway = connected
    gateway.script = [ModelTurn(calls=(ToolCall("enterprise.get", {"id": "E002"}),))] * 5
    reply = client.post(url, json={"text": "继续处理"}).json()["reply"]
    assert len(gateway.requests) == len(bridge.calls) == len(reply["toolCalls"]) == 4
    assert "上限" in reply["content"]


def _events(data):
    for part in data.strip().split("\n\n"):
        kind, payload = part.split("\n", 1)
        yield kind.removeprefix("event: "), json.loads(payload.removeprefix("data: "))


def test_sse_sends_model_deltas_and_cards_and_finishes_persisted_reply(connected):
    client, url, bridge, gateway = connected
    gateway.script = [
        ModelTurn(calls=(ToolCall("enterprise.get", {"id": "E002"}),)),
        ModelTurn(("查询", "完成。"), model="configured-local"),
    ]
    with client.stream("POST", url, json={"text": "查一查业务记录", "stream": True}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = list(_events(response.read().decode()))
    assert [name for name, _ in events] == ["meta", "tool", "delta", "delta", "card", "done"]
    assert [data["text"] for name, data in events if name == "delta"] == ["查询", "完成。"]
    assert events[-2][1]["deepLink"] == {"app": "enterprise", "params": {"entId": "E002"}}
    done = events[-1][1]
    assert (done["messageId"], done["reply"]["content"], done["reply"]["incomplete"]) == (
        events[0][1]["messageId"], "查询完成。", False,
    )
    assert client.get(url.removesuffix("/messages")).json()["messages"] == [done["user"], done["reply"]]


@pytest.mark.parametrize("spec", ["2.3", "2.4"])
def test_sse_disconnect_keeps_incomplete_assistant(connected, spec):
    client, url, bridge, gateway = connected
    body = json.dumps({"text": "书香里文化能申请哪些支持？", "stream": True}).encode()
    sent = []

    async def drive_asgi():
        disconnect = asyncio.Event()
        body_read = False

        async def receive():
            nonlocal body_read
            if not body_read:
                body_read = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                assert message["status"] == 200
            data = message.get("body", b"")
            if data.startswith(b"event: delta"):
                sent.extend(_events(data.decode()))
                disconnect.set()
                if spec == "2.4":
                    raise OSError("fixture closed the socket")
                await asyncio.Future()
            if data:
                sent.extend(_events(data.decode()))

        prepared = client.build_request("POST", url, content=body, headers={"content-type": "application/json"})
        scope = dict(type="http", asgi={"version": "3.0", "spec_version": spec}, http_version="1.1",
                     method="POST", scheme="http", path=url, root_path="", query_string=b"",
                     headers=[(key.lower(), value) for key, value in prepared.headers.raw], client=("127.0.0.1", 12345), server=("testserver", 80))
        if spec == "2.4":
            with pytest.raises(ClientDisconnect):
                await client.app(scope, receive, send)
        else:
            await client.app(scope, receive, send)

    asyncio.run(drive_asgi())
    assert [name for name, _ in sent] == ["meta", "tool", "delta"]
    history = client.get(url.removesuffix("/messages")).json()["messages"]
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assistant = history[1]
    assert assistant["role"] == "assistant"
    assert assistant["incomplete"] is True
    assert assistant["id"] == sent[0][1]["messageId"]
    assert assistant["content"] == ""


def test_invalid_and_unauthorized_requests_do_not_write_or_call_tools(connected):
    client, url, bridge, gateway = connected
    unauthenticated = TestClient(client.app)
    response = unauthenticated.post(url, json={"text": "你好", "stream": True})
    assert (response.status_code, response.json()["error"]["code"]) == (401, "UNAUTHENTICATED")
    assert unauthenticated.post("/api/auth/login", json={"user_id": "sampleadmin"}).status_code == 200
    response = unauthenticated.post(url, json={"text": "你好"})
    assert (response.status_code, response.json()["error"]["code"]) == (404, "NOT_FOUND")
    response = client.post(url, json={"text": " "})
    assert (response.status_code, response.json()["error"]["code"]) == (422, "CHECK_FAILED")
    response = client.post(url, content=r'{"text":"你好","files":[{"name":"\ud800"}]}',
                           headers={"content-type": "application/json"})
    assert (response.status_code, response.json()["error"]["code"]) == (422, "CHECK_FAILED")
    assert client.get(url.removesuffix("/messages")).json()["messages"] == []
    assert not bridge.calls and not gateway.requests


def test_concurrent_turns_preserve_pairs_and_finalize_independently(tmp_path):
    store = ConversationStore(Store(tmp_path))
    cid = store.create(OWNER)["id"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(lambda text: start_turn(store, OWNER, cid, text, []), ["甲", "乙"])
    finish_turn(store, OWNER, cid, second, {"content": "乙的回复"})
    finish_turn(store, OWNER, cid, first, {"content": "甲的回复"})
    messages = store.detail(OWNER, cid)["messages"]
    observed = {
        (messages[i]["content"], messages[i + 1]["content"], messages[i + 1]["incomplete"])
        for i in range(0, len(messages), 2)
    }
    assert observed == {("甲", "甲的回复", False), ("乙", "乙的回复", False)}
    assert len(store.platform.audit_list("conversations")) == 7

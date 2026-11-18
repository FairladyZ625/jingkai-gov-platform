"""直连对话验收，模型请求始终使用脚本或内存 transport。"""

import json
import os
from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
import anyio
import httpx

from jkq import ai_chat

PATH = "/api/v1/ai/chat"
CHAT = {"messages": [{"role": "user", "content": "公开演练"}]}
TOOL = "policy.match"
ARGS = {"entId": "E001"}
USAGE = {"input": 8, "output": 5}


def chunk(delta, finish=None):
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def script():
    call = {"id": "call-1", "type": "function", "function": {
        "name": TOOL, "arguments": json.dumps(ARGS),
    }}
    first = {**call, "index": 0, "function": {"name": TOOL, "arguments": '{"entId":'}}
    second = {"index": 0, "function": {"arguments": '"E001"}'}}
    return {
        "message": {"content": "已收到", "tool_calls": [call]},
        "chunks": [
            chunk({"content": "已收到"}), chunk({"tool_calls": [first]}),
            chunk({"tool_calls": [second]}, "tool_calls"),
            {"choices": [], "usage": {"prompt_tokens": 8, "completion_tokens": 5}}, "[DONE]",
        ],
    }


@pytest.fixture
def session(make_client, monkeypatch):
    for key in list(os.environ):
        if key == "JKQ_MODEL_PROVIDER" or key.startswith((
            "JKQ_CLOUD_MODEL_", "JKQ_LOCAL_MODEL_", "JKQ_OVERSEAS_MODEL_", "JKQ_DEEPSEEK_MODEL_",
        )):
            monkeypatch.delenv(key)
    monkeypatch.setenv("JKQ_CLOUD_MODEL_BASE_URL", "https://cloud.example.test/v1")
    monkeypatch.setenv("JKQ_CLOUD_MODEL_NAME", "云端测试")
    monkeypatch.setenv("JKQ_CLOUD_MODEL_API_KEY", "fake-test-credential")
    client = make_client()
    client.app.include_router(ai_chat.router)
    with client:
        def forbidden(request):
            pytest.fail(f"意外的模型请求 {request.url.path}")

        service = client.app.state.jkq_models
        service.transport = httpx.MockTransport(forbidden)
        service.providers["mock"]["mock_script"] = script()
        yield client


def login(client):
    assert client.post("/api/auth/login", json={"user_id": "sampleoperator"}).status_code == 200


def register_tool(client):
    def tools(user):
        assert user.id == "sampleoperator"
        return {"items": [{"name": TOOL, "app": "policy", "write": False}]}
    client.app.state.apps_bridge = SimpleNamespace(tools=tools)


def events(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    result = []
    for block in response.text.strip().split("\n\n"):
        event, data = block.splitlines()
        assert event.startswith("event: ") and data.startswith("data: ")
        result.append((event[7:], json.loads(data[6:])))
    return result


def test_unique_route_auth_and_catalog(session):
    assert len([r for r in ai_chat.router.routes if r.path == PATH and "POST" in r.methods]) == 1
    assert set(session.app.openapi()["paths"][PATH]) == {"post"}
    assert session.post(PATH, json=CHAT).status_code == 401
    login(session)
    assert session.get("/api/v1/models").status_code == 200
    assert session.put("/api/v1/models/current", json={"model": "mock"}).json() == {"current": "mock"}
    assert session.patch("/api/v1/models/mock", json={"enabled": False}).status_code == 403
    assert session.post(PATH, json={**CHAT, "mock_script": {}}).status_code == 422


@pytest.mark.parametrize("stream", [False, True])
def test_unknown_tool_before_gateway(session, monkeypatch, stream):
    login(session)
    monkeypatch.setattr(ai_chat, "ConversationGateway", lambda *a, **kw: pytest.fail("提前创建网关"))
    for names in ([TOOL], [TOOL, "hidden.tool"]):
        response = session.post(PATH, json={**CHAT, "stream": stream, "tools": names})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "TOOL_NOT_FOUND"
        register_tool(session)


def test_full_message_and_exact_http_projection(session):
    login(session)
    register_tool(session)
    user = session.app.state.platform.directory.users()["sampleoperator"]
    service = session.app.state.jkq_models
    gateway = ai_chat.ConversationGateway(service.settings, service.store.audit,
        [(service.providers["mock"], service.items()["mock"]["name"])], lambda *_: None,
        transport=service.transport)
    tools = [{"type": "function", "function": {"name": TOOL, "parameters": {"type": "object"}}}]
    message = gateway.chat_message(ai_chat.models.PLATFORM_APP, {**CHAT, "tools": tools}, principal=user)
    assert message == {"content": "已收到", "tool_calls": [{"name": TOOL, "arguments": ARGS}]}
    assert session.put("/api/v1/models/current", json={"model": "mock"}).status_code == 200
    response = session.post(PATH, json={**CHAT, "tools": [TOOL], "stream": False})
    assert response.status_code == 200
    assert response.json() == {"model": service.items()["mock"]["name"], "content": "已收到",
                               "routeNote": "使用模拟模型"}


def test_mock_sse_complete_snapshot(session):
    login(session)
    register_tool(session)
    body = {**CHAT, "model": "mock", "stream": True, "tools": [TOOL]}
    first, second = [session.post(PATH, json=body) for _ in range(2)]
    assert first.content == second.content
    actual = events(first)
    message_id = actual[-1][1]["messageId"]
    assert isinstance(message_id, str) and message_id
    assert actual == [
        ("meta", {"model": session.app.state.jkq_models.items()["mock"]["name"], "routeNote": "使用模拟模型"}),
        ("delta", {"text": "已收到"}), ("tool", {"tool": TOOL, "args": ARGS}),
        ("done", {"messageId": message_id, "usage": USAGE}),
    ]


@pytest.mark.parametrize("stream", [False, True])
def test_confidential_denial_audited_without_outbound(session, stream):
    login(session)
    response = session.post(PATH, json={**CHAT, "model": "cloud", "classification": "confidential",
                                        "stream": stream})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "OUTBOUND_DENIED"
    entry = session.app.state.platform.store.audit_list("platform")[0]
    assert (entry["action"], entry["user"]) == ("ai.outbound_denied", "sampleoperator")


def test_truncated_provider_finishes_with_error(session):
    class Truncated(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield ("data: " + json.dumps(chunk({"content": "收到首块"})) + "\n\n").encode()
            raise httpx.RemoteProtocolError("synthetic truncation")

    seen = []

    def respond(request):
        seen.append(request.url.host)
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=Truncated())

    login(session)
    session.app.state.jkq_models.transport = httpx.MockTransport(respond)
    started = monotonic()
    response = session.post(PATH, json={**CHAT, "model": "cloud", "stream": True})
    assert monotonic() - started < 30
    result = events(response)
    assert result[:2] == [("meta", {"model": "云端测试", "routeNote": ""}), ("delta", {"text": "收到首块"})]
    assert len(result) == 3
    kind, error = result[-1]
    assert kind == "error" and set(error) == {"code", "message"}
    assert error["code"] == "PROVIDER_ERROR" and error["message"]
    assert seen == ["cloud.example.test"]


def test_delta_delivered_before_upstream_finishes_and_disconnect_cancels():
    # TestClient 会缓存响应，直接在 ASGI send 收到首块后断开。
    stopped = Event()

    def stream_message(app, payload, *, principal, on_event, cancelled, timeout):
        on_event("cloud", "演练模型", "delta", {"text": "首块"})
        if cancelled.wait(3):
            stopped.set()
        return {"provider": "cloud", "model": "演练模型", "result": {"mock": False, "usage": USAGE}}

    async def run():
        disconnect = anyio.Event()
        frames = []

        async def receive():
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            frames.append(message)
            if b"event: delta" in message.get("body", b""):
                disconnect.set()

        response = ai_chat.ChatStream(SimpleNamespace(stream_message=stream_message), CHAT, None,
                                      lambda _, model: {"model": model, "routeNote": ""})
        with anyio.fail_after(5):
            await response({"type": "http"}, receive, send)
        assert stopped.is_set()
        assert len(frames) == 3 and frames[-1]["more_body"]

    anyio.run(run)


def test_confidential_stream_uses_local_model_and_registered_definition(session):
    login(session)
    register_tool(session)
    service = session.app.state.jkq_models
    service.providers["local"] = {
        "id": "local", "kind": "openai", "model": "内网演练", "api_key": "",
        "base_url": "https://local.example.test/v1", "allow_outbound": "confidential",
    }
    seen = []

    def respond(request):
        seen.append(request.url.host)
        body = json.loads(request.content)
        assert body["model"] == "内网演练" and "classification" not in body
        tool, = body["tools"]
        assert tool["type"] == "function" and tool["function"]["parameters"]["type"] == "object"
        alias = tool["function"]["name"]
        parts = [chunk({"tool_calls": [{"index": 0, "id": "1", "type": "function",
                  "function": {"name": alias, "arguments": "{}"}}]}, "tool_calls")]
        content = "".join("data: " + json.dumps(part) + "\n\n" for part in parts) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=content)

    service.transport = httpx.MockTransport(respond)
    response = session.post(PATH, json={**CHAT, "model": "cloud", "classification": "confidential",
                                        "stream": True, "tools": [TOOL]})
    result = events(response)
    assert result[:2] == [("meta", {"model": "内网演练", "routeNote": "按密级切换到白名单模型"}),
                          ("tool", {"tool": TOOL, "args": {}})]
    assert len(result) == 3 and result[-1][0] == "done"
    assert seen == ["local.example.test"]

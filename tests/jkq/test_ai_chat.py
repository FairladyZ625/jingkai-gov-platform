"""验证网关消息、§3.2 HTTP/SSE 及 #15 路由边界。"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import monotonic, sleep as wait_briefly

import pytest

pytest.importorskip("fastapi")
import httpx
from anyio import sleep

from haiknow_core.aihub.streaming import ChatRequest
from jkq.ai_chat import chat_message, install

PATH = "/api/v1/ai/chat"
REQUEST = {"messages": [{"role": "user", "content": "匹配演练企业的事项"}]}
TOOL = "policy.match"
ALIAS = "policy_match"
CALL = {"type": "function", "function": {"name": ALIAS, "arguments": '{"entId":"E001"}'}}


class ProviderStream(httpx.AsyncByteStream):
    def __init__(self, *frames, disconnect=False):
        self.frames = frames
        self.disconnect = disconnect
        self.closed = False

    async def __aiter__(self):
        for frame in self.frames:
            yield frame.encode()
        if self.disconnect:
            raise httpx.RemoteProtocolError("sensitive-upstream-detail")

    async def aclose(self):
        self.closed = True


def frame(delta=None, *, finish=None, usage=None):
    choices = [] if delta is None else [{"index": 0, "delta": delta, "finish_reason": finish}]
    return "data: " + json.dumps({"choices": choices, "usage": usage}, ensure_ascii=False) + "\n\n"


def events(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return [(event.removeprefix("event: "), json.loads(data.removeprefix("data: ")))
            for event, data in (part.splitlines() for part in response.text.strip().split("\n\n"))]


def configure(monkeypatch, *, local=False, approve=False):
    prefix = "JKQ_LOCAL_MODEL" if local else "JKQ_CLOUD_MODEL"
    url = "https://local.example.test/v1" if local else "https://cloud.example.test/v1"
    monkeypatch.setenv(prefix + "_BASE_URL", url)
    monkeypatch.setenv(prefix + "_NAME", "local-model" if local else "cloud-model")
    if approve:
        monkeypatch.setenv(prefix + "_CONFIDENTIAL_BASE_URL", url)
    if not local:
        monkeypatch.setenv(prefix + "_API_KEY", "test-placeholder-key")


@pytest.fixture
def client_factory(make_client, isolated_platform, monkeypatch):
    for key in os.environ.keys() & {
        "JKQ_MODEL_PROVIDER",
        *(f"JKQ_CODEX_MODEL_{key}" for key in ("ENABLED", "NAME", "TIMEOUT", "MAX_CONCURRENCY")),
        *(f"JKQ_{provider}_MODEL_{option}"
          for provider in ("CLOUD", "DEEPSEEK", "LOCAL", "LOCAL_BACKUP", "OVERSEAS")
          for option in ("BASE_URL", "NAME", "API_KEY", "CONFIDENTIAL_BASE_URL")),
    }:
        monkeypatch.delenv(key)
    _, apps = isolated_platform
    manifest = apps / "sample-app/app.json"
    published = []
    for app in ("enterprise", "document"):
        source = Path(__file__).resolve().parents[2] / "apps" / app / "app.json"
        published.extend(json.loads(source.read_text(encoding="utf-8"))["tools"])
    manifest.write_text(json.dumps({
        **json.loads(manifest.read_text()),
        "tools": [*published, {"name": TOOL, "desc": "匹配演练事项", "params": {"entId": "string", "tags": "string[]?"}}],
    }), encoding="utf-8")

    def create():
        client = make_client()
        install(client.app)
        return client

    return create


def chat_audit(service):
    return [row["detail"] for row in service.store.audit_list("platform") if row["action"] == "ai.chat"]


def login(client, user="sampleadmin"):
    assert client.post("/api/auth/login", json={"user_id": user}).status_code == 200


def test_gateway_chat_message_and_legacy_text(client_factory):
    with client_factory() as client:
        service = client.app.state.jkq_models
        service.providers["mock"]["chat_script"] = {"content": None, "tool_calls": [CALL]}
        result = chat_message(service, None, REQUEST)
        assert result == {"content": None, "tool_calls": [{"name": ALIAS, "arguments": {"entId": "E001"}}]}
        ai = client.app.state.platform.model.aihub
        assert isinstance(ai.call("sample-app", "chat", REQUEST)["result"], str)


def test_core_gateway_structured_chat(make_client, monkeypatch):
    client = make_client()
    gateway = client.app.state.platform.model.aihub
    provider = {"id": "scripted", "kind": "mock", "allow_outbound": "internal",
                "chat_script": {"content": "演练", "tool_calls": [CALL]}}
    monkeypatch.setattr(gateway, "_route_candidates", lambda *_: [(provider, "scripted-model")])
    assert gateway.call("sample-app", "chat", ChatRequest(REQUEST))["result"] == {
        "content": "演练", "tool_calls": [{"name": ALIAS, "arguments": {"entId": "E001"}}],
    }
    assert isinstance(gateway.call("sample-app", "chat", REQUEST)["result"], str)


def test_non_stream_keeps_model_content_route_note(client_factory):
    with client_factory() as client:
        assert client.post(PATH, json=REQUEST).status_code == 401
        login(client)
        response = client.post(PATH, json={**REQUEST, "stream": False})
        assert response.status_code == 200
        catalog = {item["id"]: item for item in client.get("/api/v1/models").json()["items"]}
        assert set(response.json()) == {"model", "content", "routeNote", "usage", "mock"}
        assert response.json()["model"] == catalog["mock"]["name"]
        assert response.json()["content"] == "[模拟模型] 已收到输入。"
        assert response.json()["routeNote"] == "使用模拟模型"
        assert response.json()["usage"] == {"input": 0, "output": 0}
        assert client.post(PATH, json={**REQUEST, "stream": "true"}).status_code == 422
        assert client.post(PATH, json={**REQUEST, "tools": [{"name": TOOL}]}).status_code == 422


def test_mock_event_snapshot_is_repeatable(client_factory):
    with client_factory() as client:
        login(client)
        service = client.app.state.jkq_models
        service.providers["mock"]["chat_script"] = {"content": "已匹配演练事项", "tool_calls": [CALL]}
        body = {**REQUEST, "stream": True, "tools": [TOOL, TOOL], "temperature": 0.3}
        first = client.post(PATH, json=body)
        assert first.text == client.post(PATH, json=body).text
        assert events(first) == [
            ("meta", {"model": service.items()["mock"]["name"], "routeNote": "使用模拟模型"}),
            ("delta", {"text": "已匹配演练事项"}),
            ("tool", {"tool": TOOL, "args": {"entId": "E001"}}),
            ("done", {"messageId": "M-bf453c66-02f6-58ad-b0b4-7a9851ce9b19", "usage": {"input": 0, "output": 0}}),
        ]


@pytest.mark.parametrize("stream", [False, True])
def test_mock_rejects_invalid_tool_before_delivery(client_factory, stream):
    with client_factory() as client:
        login(client)
        service = client.app.state.jkq_models
        invalid = {"type": "function", "function": {"name": ALIAS, "arguments": "{}"}}
        service.providers["mock"]["chat_script"] = {"content": None, "tool_calls": [CALL, invalid]}
        response = client.post(PATH, json={**REQUEST, "tools": [TOOL], "stream": stream})
        if stream:
            sequence = events(response)
            assert [e for e, _ in sequence] == ["meta", "error"]
            assert sequence[-1][1]["code"] == "PROVIDER_ERROR"
        else:
            assert response.status_code == 502 and response.json()["error"]["code"] == "PROVIDER_ERROR"
        assert [(r["provider"], r["status"]) for r in chat_audit(service)] == [("mock", "provider_error")]


@pytest.mark.parametrize("stream", [False, True])
def test_unregistered_tool_returns_404_before_provider(client_factory, monkeypatch, stream):
    configure(monkeypatch)
    with client_factory() as client:
        login(client)
        service = client.app.state.jkq_models
        service.transport = httpx.MockTransport(lambda _: pytest.fail("未注册工具不应发给模型"))
        response = client.post(PATH, json={**REQUEST, "stream": stream, "tools": ["unknown.tool"]})
        assert response.status_code == 404
        assert response.json()["error"] == {
            "code": "TOOL_NOT_FOUND", "message": "请求包含未注册的工具。", "details": {},
        }


@pytest.mark.parametrize("stream", [False, True])
def test_registered_tool_requires_app_operate(client_factory, stream):
    with client_factory() as client:
        login(client, "sampleobserver")
        response = client.post(PATH, json={**REQUEST, "stream": stream, "tools": [TOOL]})
        assert response.status_code == 403
        error = response.json()["error"]
        assert error["code"] == "FORBIDDEN"
        assert error["details"] == {"app": "sample-app", "need": "operate"}
        audit = client.app.state.platform.store.audit_list("sample-app")
        assert [(row["user"], row["detail"]) for row in audit if row["action"] == "ai.tool_forbidden"] == [
            ("sampleobserver", {"need": "operate"}),
        ]


@pytest.mark.parametrize("stream_usage", [True, False])
def test_provider_tool_fragments_and_usage_are_assembled(client_factory, monkeypatch, stream_usage):
    configure(monkeypatch)
    frames = [
        frame({"role": "assistant"}),
        frame({"content": "已查找"}),
        frame({"tool_calls": [{"index": 0, "function": {"name": "policy_", "arguments": '{"ent'}}]}),
        frame({"tool_calls": [{"index": 0, "function": {"name": "match", "arguments": 'Id":"E001"}'}}]}),
        frame({}, finish="tool_calls"),
    ]
    upstream = ProviderStream()

    def respond(request):
        body = json.loads(request.content)
        options = body.pop("stream_options", None)
        assert options == ({"include_usage": True} if stream_usage else None)
        upstream.frames = list(frames)
        if options and options.get("include_usage"):
            upstream.frames.append(frame(usage={"prompt_tokens": 8, "completion_tokens": 5}))
        upstream.frames.append("data: [DONE]\n\n")
        assert body == {**REQUEST, "stream": True, "model": "cloud-model", "tools": [{
            "type": "function", "function": {"name": ALIAS, "description": "匹配演练事项",
                                           "parameters": {"type": "object", "properties": {
                                               "entId": {"type": "string"},
                                               "tags": {"type": "array", "items": {"type": "string"}},
                                           }, "additionalProperties": False, "required": ["entId"]}},
        }]}
        return httpx.Response(200, stream=upstream)

    with client_factory() as client:
        login(client)
        service = client.app.state.jkq_models
        if not stream_usage:
            service.providers["cloud"]["stream_usage"] = False
        service.transport = httpx.MockTransport(respond)
        result = events(client.post(PATH, json={**REQUEST, "stream": True, "tools": [TOOL]}))
        assert result[:3] == [
            ("meta", {"model": "cloud-model", "routeNote": ""}),
            ("delta", {"text": "已查找"}),
            ("tool", {"tool": TOOL, "args": {"entId": "E001"}}),
        ]
        assert len(result) == 4 and result[3][0] == "done"
        expected_usage = {"input": 8, "output": 5} if stream_usage else {"input": None, "output": None}
        assert result[3][1]["usage"] == expected_usage
        assert chat_audit(service) == [{"model": "cloud-model", "provider": "cloud",
                                        "providerKind": "cloud",
                                        "status": "success", "usage": expected_usage}]
        assert upstream.closed


@pytest.mark.parametrize("disconnect", [False, True], ids=["incomplete-eof", "transport-error"])
def test_midstream_disconnect_reports_error_and_closes(client_factory, monkeypatch, disconnect):
    configure(monkeypatch)
    upstream = ProviderStream(frame({"content": "半句"}), disconnect=disconnect)
    with client_factory() as client:
        login(client)
        service = client.app.state.jkq_models
        service.transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=upstream))
        started = monotonic()
        response = client.post(PATH, json={**REQUEST, "stream": True})
        assert monotonic() - started < 30
        result = events(response)
        assert [event for event, _ in result] == ["meta", "delta", "error"]
        assert result[1][1] == {"text": "半句"}
        assert set(result[2][1]) == {"code", "message"}
        assert result[2][1]["code"] == "PROVIDER_ERROR"
        assert "sensitive-upstream-detail" not in response.text and upstream.closed
        audit = service.store.audit_list("platform")
        assert [row["detail"]["status"] for row in audit if row["action"] == "ai.chat"] == ["provider_error"]


def test_provider_timeout_ends_stream(client_factory, monkeypatch):
    configure(monkeypatch)

    class StalledProvider(ProviderStream):
        async def __aiter__(self):
            yield frame({"content": "已开始"}).encode()
            await sleep(60)

    upstream = StalledProvider()
    with client_factory() as client:
        login(client)
        service = client.app.state.jkq_models
        service.transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=upstream))
        started = monotonic()
        result = events(client.post(PATH, json={**REQUEST, "stream": True}))
        assert monotonic() - started < 30
        assert [event for event, _ in result] == ["meta", "delta", "error"]
        assert result[-1][1]["code"] == "TIMEOUT" and upstream.closed
        assert [(r["provider"], r["status"]) for r in chat_audit(service)] == [("cloud", "timeout")]


@pytest.mark.parametrize("failure", ["503", "connect"])
@pytest.mark.parametrize("stream", [True, False])
def test_fallback_reports_actual_provider(client_factory, monkeypatch, failure, stream):
    configure(monkeypatch)
    with client_factory() as client:
        login(client)
        service = client.app.state.jkq_models

        def fail(request):
            if failure == "connect":
                raise httpx.ConnectError("sensitive-upstream-detail", request=request)
            return httpx.Response(503)

        service.transport = httpx.MockTransport(fail)
        response = client.post(PATH, json={**REQUEST, "stream": stream, "tools": [TOOL]})
        expected_meta = {"model": service.items()["mock"]["name"],
                         "routeNote": "主模型调用失败，已回退，使用模拟模型"}
        if stream:
            result = events(response)
            assert result[0] == ("meta", expected_meta)
            assert [event for event, _ in result] == ["meta", "delta", "done"]
        else:
            assert response.status_code == 200
            body = response.json()
            assert {k: body[k] for k in expected_meta} == expected_meta
            assert body["mock"] and body["tool_calls"] == []
        assert [(r["provider"], r["status"]) for r in chat_audit(service)] == [
            ("mock", "success"), ("cloud", "provider_error"),
        ]


@pytest.mark.parametrize("approved", [False, True])
def test_stream_confidential_obeys_same_outbound_gate(client_factory, monkeypatch, approved):
    configure(monkeypatch)
    configure(monkeypatch, local=True, approve=approved)
    seen = []

    def respond(request):
        seen.append(request.url.host)
        assert request.url.host == "local.example.test"
        assert "classification" not in json.loads(request.content)
        return httpx.Response(200, text=frame({"content": "本地结果"}, finish="stop"))

    with client_factory() as client:
        login(client)
        service = client.app.state.jkq_models
        service.transport = httpx.MockTransport(respond)
        response = client.post(PATH, json={**REQUEST, "classification": "confidential", "stream": True})
        if approved:
            assert events(response)[0] == ("meta", {"model": "local-model", "routeNote": "按密级切换到白名单模型"})
            assert seen == ["local.example.test"]
        else:
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "OUTBOUND_DENIED"
            assert seen == []


@pytest.mark.parametrize("stream", [True, False])
@pytest.mark.parametrize("names", [[TOOL, "unknown.tool"], ["unknown.tool", TOOL]])
def test_unknown_precedes_forbidden(client_factory, stream, names):
    with client_factory() as client:
        login(client, "sampleobserver")
        response = client.post(PATH, json={**REQUEST, "stream": stream, "tools": names})
        assert response.status_code == 404 and response.json()["error"]["code"] == "TOOL_NOT_FOUND"
        store = client.app.state.platform.store
        assert not any(r["action"] == "ai.tool_forbidden" for r in store.audit_list("sample-app"))
        assert not chat_audit(client.app.state.jkq_models)


@pytest.mark.parametrize("stream", [True, False])
@pytest.mark.parametrize("name,args,valid", [
    ("document.polish", {"id": "D1", "style": "formal"}, True),
    ("document.polish", {"id": "D1", "style": "concise"}, True),
    ("document.polish", {"id": "D1", "style": "invalid"}, False),
    ("enterprise.get", {}, False),
    ("enterprise.get", {"id": 1}, False),
    ("unknown.tool", {}, False),
    (TOOL, {"entId": "E001", "tags": ["演练"]}, True),
    (TOOL, {"entId": "E001", "tags": [False]}, False),
])
def test_registered_call_contract(client_factory, monkeypatch, stream, name, args, valid):
    configure(monkeypatch)
    # 第一条合法、第二条非法时，整批工具均不得发出。
    calls = [CALL, {"type": "function", "function": {
        "name": name.replace(".", "_"), "arguments": json.dumps(args),
    }}]
    upstream = ProviderStream(
        frame({"tool_calls": [dict(call, index=i) for i, call in enumerate(calls)]}, finish="tool_calls"),
        "data: [DONE]\n\n",
    )

    def respond(request):
        body = json.loads(request.content)
        declarations = {t["function"]["name"]: t["function"]["parameters"] for t in body["tools"]}
        polish = declarations["document_polish"]
        assert polish["required"] == ["id", "style"]
        assert polish["properties"]["style"] == {"type": "string", "enum": ["formal", "concise"]}
        assert declarations["enterprise_get"]["required"] == ["id"]
        assert declarations[ALIAS]["required"] == ["entId"]
        if stream:
            return httpx.Response(200, stream=upstream)
        return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": calls}}]})

    with client_factory() as client:
        login(client)
        service = client.app.state.jkq_models
        service.transport = httpx.MockTransport(respond)
        started = monotonic()
        response = client.post(PATH, json={**REQUEST, "stream": stream,
                                           "tools": [TOOL, "document.polish", "enterprise.get"]})
        assert monotonic() - started < 30
        if stream:
            sequence = events(response)
            assert upstream.closed
            if valid:
                assert [e for e, _ in sequence] == ["meta", "tool", "tool", "done"]
                assert sequence[1:3] == [("tool", {"tool": TOOL, "args": {"entId": "E001"}}),
                                         ("tool", {"tool": name, "args": args})]
            else:
                assert [e for e, _ in sequence] == ["meta", "error"]
                assert sequence[-1][1]["code"] == "PROVIDER_ERROR"
        elif valid:
            assert response.status_code == 200
            assert response.json()["content"] is None
            assert response.json()["tool_calls"] == [
                {"name": TOOL, "arguments": {"entId": "E001"}}, {"name": name, "arguments": args},
            ]
        else:
            assert response.status_code == 502 and response.json()["error"]["code"] == "PROVIDER_ERROR"
        assert [(r["provider"], r["status"]) for r in chat_audit(service)] == [
            ("cloud", "success" if valid else "provider_error"),
        ]


@pytest.mark.parametrize("finish", [None, "aborted", "insufficient_system_resource"])
def test_role_disconnect_and_failed_finish(client_factory, monkeypatch, finish):
    configure(monkeypatch)
    upstream = ProviderStream(frame({"role": "assistant"}, finish=finish), disconnect=finish is None)
    with client_factory() as client:
        login(client)
        service = client.app.state.jkq_models
        service.transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=upstream))
        started = monotonic()
        response = client.post(PATH, json={**REQUEST, "stream": True})
        assert monotonic() - started < 30 and upstream.closed
        sequence = events(response)
        assert [e for e, _ in sequence] == ["meta", "error"]
        assert sequence[1][1]["code"] == "PROVIDER_ERROR"
        assert "sensitive-upstream-detail" not in response.text
        assert chat_audit(service) == [{"provider": "cloud", "providerKind": "cloud", "model": "cloud-model",
                                        "status": "provider_error", "usage": {"input": None, "output": None}}]


@pytest.mark.parametrize("stream", [False, True])
def test_provider_400_is_permanent(client_factory, monkeypatch, stream):
    configure(monkeypatch)
    with client_factory() as client:
        login(client)
        service = client.app.state.jkq_models
        service.transport = httpx.MockTransport(lambda _: httpx.Response(400, text="sensitive-upstream-detail"))
        started = monotonic()
        response = client.post(PATH, json={**REQUEST, "tools": [TOOL], "stream": stream})
        assert monotonic() - started < 30
        assert response.status_code == 502 and response.json()["error"]["code"] == "PROVIDER_ERROR"
        assert "sensitive-upstream-detail" not in response.text
        assert chat_audit(service) == [{"provider": "cloud", "providerKind": "cloud", "model": "cloud-model",
                                        "status": "provider_error", "usage": {"input": None, "output": None}}]


PUBLIC = {**REQUEST, "classification": "public"}
CLI_MODEL = "synthetic-cli-model"


@pytest.fixture
def fake_codex(client_factory, tmp_path, monkeypatch):
    # CLI_ENV 只传白名单变量。用脚本自身的位置找到控制文件，与子进程 cwd 无关。
    program = tmp_path / ("codex.py" if os.name == "nt" else "codex")
    if os.name != "nt":
        (tmp_path / "python3").symlink_to(sys.executable)
    program.write_text("""#!/usr/bin/env python3
import json
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent
prompt = sys.stdin.buffer.read().decode("utf-8")
with (root / "calls").open("a", encoding="utf-8") as log:
    log.write(json.dumps([sys.argv[1:], prompt]) + "\\n")
sys.stdout.buffer.write((root / "reply").read_bytes())
sys.stdout.buffer.flush()
(root / "started").touch()
deadline = time.monotonic() + 10
while (root / "hold").exists():
    if time.monotonic() >= deadline:
        sys.exit(24)
    time.sleep(0.01)
sys.exit(23 if (root / "fail").exists() else 0)
""", encoding="utf-8")
    program.chmod(0o755)
    if os.name == "nt":
        (tmp_path / "codex.cmd").write_text(f'@"{sys.executable}" "%~dp0codex.py" %*\n')
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("JKQ_CODEX_MODEL_NAME", CLI_MODEL)
    (tmp_path / "reply").write_text("JKQ_CODEX_OK", encoding="utf-8")
    return tmp_path


def select_codex(client, *, fallback=False):
    login(client)
    response = client.put("/api/v1/models/current", json={"model": "codex-cli"})
    assert response.status_code == 200, response.text
    assert response.json()["current"] == "codex-cli"
    if not fallback:
        assert client.patch("/api/v1/models/mock", json={"enabled": False}).status_code == 200


@pytest.fixture
def codex_client(client_factory, fake_codex, monkeypatch):
    monkeypatch.setenv("JKQ_CODEX_MODEL_ENABLED", "1")
    return client_factory


def test_codex_name_alone_leaves_mock_default(client_factory, fake_codex):
    with client_factory() as client:
        login(client)
        items = client.get("/api/v1/models").json()["items"]
        assert "codex-cli" not in {item["id"] for item in items}
        response = client.post(PATH, json=PUBLIC)
        assert response.status_code == 200 and response.json()["mock"] is True
        assert not (fake_codex / "calls").exists()


def test_codex_catalog_selection_and_public_reply(codex_client, fake_codex):
    with codex_client() as client:
        assert client.get("/api/v1/models").status_code == 401
        assert client.post(PATH, json=PUBLIC).status_code == 401
        assert not (fake_codex / "calls").exists()
        select_codex(client, fallback=True)
        catalog = client.get("/api/v1/models").json()
        item = next(item for item in catalog["items"] if item["id"] == "codex-cli")
        assert item["enabled"] and item["name"] == CLI_MODEL
        assert catalog["current"] == "codex-cli"
        response = client.post(PATH, json=PUBLIC)
        assert response.status_code == 200
        data = response.json()
        assert (data["model"], data["content"], data["mock"]) == (CLI_MODEL, "JKQ_CODEX_OK", False)
        argv, prompt = json.loads((fake_codex / "calls").read_text(encoding="utf-8"))
        assert "exec" in argv and argv[argv.index("--model") + 1] == CLI_MODEL
        assert REQUEST["messages"][0]["content"] in prompt


@pytest.mark.parametrize("classification", ["internal", "confidential"])
def test_codex_classification_denied_before_process(codex_client, fake_codex, classification):
    with codex_client() as client:
        select_codex(client)
        response = client.post(PATH, json={**REQUEST, "classification": classification})
        assert response.status_code == 403 and response.json()["error"]["code"] == "OUTBOUND_DENIED"
        assert not (fake_codex / "calls").exists()


@pytest.mark.parametrize("stream", [False, True])
def test_codex_nonzero_discards_stdout(codex_client, fake_codex, stream):
    (fake_codex / "fail").touch()
    with codex_client() as client:
        select_codex(client)
        response = client.post(PATH, json={**PUBLIC, "stream": stream})
        assert (fake_codex / "started").exists()
        assert response.status_code == 502 and response.json()["error"]["code"] == "PROVIDER_ERROR"
        assert "JKQ_CODEX_OK" not in response.text


def test_codex_timeout(codex_client, fake_codex, monkeypatch):
    monkeypatch.setenv("JKQ_CODEX_MODEL_TIMEOUT", "1")
    hold = fake_codex / "hold"
    hold.touch()
    with codex_client() as client:
        select_codex(client)
        start = monotonic()
        try:
            response = client.post(PATH, json=PUBLIC)
        finally:
            hold.unlink()
        assert monotonic() - start < 6
        assert (fake_codex / "started").exists()
        assert response.status_code == 504 and response.json()["error"]["code"] == "TIMEOUT"


def wait_for_stdout(root, request):
    deadline = monotonic() + 5
    while not (root / "started").exists():
        assert monotonic() < deadline, "等待替身写出标准输出超时"
        assert not request.done(), "CLI 启动前请求已返回"
        wait_briefly(0.01)


def test_codex_concurrency_across_requests_and_release(codex_client, fake_codex, monkeypatch):
    monkeypatch.setenv("JKQ_CODEX_MODEL_MAX_CONCURRENCY", "1")
    hold = fake_codex / "hold"
    hold.touch()
    with codex_client() as client, ThreadPoolExecutor(2) as pool:
        select_codex(client)
        first = pool.submit(client.post, PATH, json=PUBLIC)
        try:
            wait_for_stdout(fake_codex, first)
            second = pool.submit(client.post, PATH, json=PUBLIC).result(timeout=3)
            assert second.status_code == 429 and second.json()["error"]["code"] == "QUOTA_EXCEEDED"
            assert len((fake_codex / "calls").read_text(encoding="utf-8").splitlines()) == 1
        finally:
            hold.unlink()
        assert first.result(timeout=5).json()["content"] == "JKQ_CODEX_OK"
        assert client.post(PATH, json=PUBLIC).json()["content"] == "JKQ_CODEX_OK"


def test_codex_stream_waits_for_exit_then_chunks(codex_client, fake_codex):
    reply = "公开🙂" * 113
    (fake_codex / "reply").write_text(reply, encoding="utf-8")
    hold = fake_codex / "hold"
    hold.touch()
    sent = Event()

    # TestClient 会缓存完整响应，在 ASGI send 上观察真实的首个事件。
    def observe(app):
        async def wrapped(scope, receive, send):
            async def observe_send(message):
                if message["type"] == "http.response.body" and message.get("body"):
                    sent.set()
                await send(message)
            await app(scope, receive, observe_send if scope.get("path") == PATH else send)
        return wrapped

    client = codex_client()
    client.app.add_middleware(observe)
    with client, ThreadPoolExecutor(1) as pool:
        select_codex(client)
        request = pool.submit(client.post, PATH, json={**PUBLIC, "stream": True})
        try:
            wait_for_stdout(fake_codex, request)
            assert not sent.wait(0.25), "CLI 退出前已收到响应块"
        finally:
            hold.unlink()
        result = events(request.result(timeout=5))
    assert sent.is_set()
    assert result[0][0] == "meta" and result[0][1]["model"] == CLI_MODEL
    assert result[-1][0] == "done" and result[-1][1]["messageId"]
    chunks = result[1:-1]
    assert all(event == "delta" and 0 < len(data["text"]) <= 128 for event, data in chunks)
    assert "".join(data["text"] for _, data in chunks) == reply


def test_codex_registered_tool_event(codex_client, fake_codex):
    call = {"name": ALIAS, "arguments": {"entId": "E001"}}
    (fake_codex / "reply").write_text(json.dumps({"content": None, "tool_calls": [call]}))
    with codex_client() as client:
        select_codex(client)
        result = events(client.post(PATH, json={**PUBLIC, "stream": True, "tools": [TOOL]}))
        assert [name for name, _ in result] == ["meta", "tool", "done"]
        assert result[1][1] == {"tool": TOOL, "args": call["arguments"]}
        _, prompt = json.loads((fake_codex / "calls").read_text(encoding="utf-8"))
        assert ALIAS in prompt and "entId" in prompt


@pytest.mark.parametrize("reply", [
    "CLI diagnostic",
    '{"content":null,"tool_calls":[{"name":"unknown","arguments":{}}]}',
    '{"content":null,"tool_calls":[{"name":"policy_match","arguments":"{}"}]}',
    '{"content":null,"tool_calls":[{"name":"policy_match","arguments":{}}]}',
    '{"content":42,"tool_calls":[]}',
    '{"content":"ok","tool_calls":{}}',
])
def test_codex_invalid_tool_response(codex_client, fake_codex, reply):
    (fake_codex / "reply").write_text(reply, encoding="utf-8")
    with codex_client() as client:
        select_codex(client)
        response = client.post(PATH, json={**PUBLIC, "tools": [TOOL]})
        assert (fake_codex / "started").exists()
        assert response.status_code == 502 and response.json()["error"]["code"] == "PROVIDER_ERROR"


def test_codex_nonzero_falls_back_to_mock(codex_client, fake_codex):
    (fake_codex / "fail").touch()
    with codex_client() as client:
        select_codex(client, fallback=True)
        response = client.post(PATH, json=PUBLIC)
        assert (fake_codex / "started").exists()
        assert response.status_code == 200
        reply = response.json()
        assert reply["mock"] is True and "已回退" in reply["routeNote"]
        assert "JKQ_CODEX_OK" not in reply["content"]

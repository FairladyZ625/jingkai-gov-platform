"""模型网关用真实会话、SQLite 和无网络的模型 transport 验证。"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# 仓库通用 job 只装 pytest。core job 安装完整依赖并执行本模块。
pytest.importorskip("fastapi")
import httpx
from fastapi import APIRouter, Depends, Request

from haiknow_core.main import current_user
from jkq.models import ChatBody, current_model, router

ROOT = Path(__file__).resolve().parents[2]
CHAT = {"messages": [{"role": "user", "content": "公开演练消息"}]}


@pytest.fixture
def model_client(make_client, monkeypatch):
    for key in os.environ.keys() & {
        "JKQ_MODEL_PROVIDER",
        *(f"JKQ_{provider}_MODEL_{option}" for provider in ("CLOUD", "DEEPSEEK", "LOCAL", "OVERSEAS")
          for option in ("BASE_URL", "NAME", "API_KEY")),
    }:
        monkeypatch.delenv(key)

    def start():
        client = make_client()
        app = client.app

        # 按 #11 显式登记，并在 /me 读取同一份偏好，业务路由优先于 core。
        me = APIRouter()

        @me.get("/api/v1/me")
        def profile(request: Request, user=Depends(current_user)):
            return {"defaultModel": current_model(request, user.id)}

        core_route_count = len(app.router.routes)
        app.include_router(router)
        app.include_router(me)
        app.router.routes[:] = app.router.routes[core_route_count:] + app.router.routes[:core_route_count]

        return client

    return start


def login(client, user="sampleadmin"):
    assert client.post("/api/auth/login", json={"user_id": user}).status_code == 200


def mock_transport(handler):
    return httpx.MockTransport(handler)


def no_request(request):
    pytest.fail(f"不应发出请求：{request.url.host}")


def configure(monkeypatch, provider, host=None, *, key=True):
    prefix = f"JKQ_{provider.upper()}_MODEL"
    monkeypatch.setenv(f"{prefix}_BASE_URL", f"https://{host or provider}.example.test/v1")
    monkeypatch.setenv(f"{prefix}_NAME", f"{provider}-configured-name")
    if key:
        monkeypatch.setenv(f"{prefix}_API_KEY", "fake-test-credential")


def upstream_response(with_usage=True):
    body = {"choices": [{"message": {"content": "收到公开演练请求"}}]}
    if with_usage:
        body["usage"] = {"prompt_tokens": 8, "completion_tokens": 5}
    return httpx.Response(200, json=body)


def test_no_credentials_mock_and_catalog(model_client):
    client = model_client()
    with client:
        client.app.state.jkq_models.transport = mock_transport(no_request)
        for method, path, body in (
            ("GET", "/api/v1/models", None), ("POST", "/api/v1/ai/chat", CHAT),
            ("PUT", "/api/v1/models/current", {"model": "mock"}),
            ("PATCH", "/api/v1/models/mock", {"enabled": False}),
        ):
            assert client.request(method, path, json=body).status_code == 401
        login(client)
        data = client.get("/api/v1/models").json()
        assert set(data) == {"items", "current", "capabilities"}
        assert data["current"] == "auto"
        items = {item["id"]: item for item in data["items"]}
        assert data["capabilities"] == [{"id": "chat", "name": "对话", "route": "auto"}]
        assert items["mock"]["enabled"] is True
        assert items["overseas"]["enabled"] is False
        response = client.post("/api/v1/ai/chat", json=CHAT)
        assert response.status_code == 200
        assert response.json()["mock"] is True
        assert response.json()["model"] == items["mock"]["name"]
        assert "[模拟模型]" in response.json()["content"]
        assert response.json()["usage"] == {"input": 0, "output": 0}


def test_permissions_and_default_persist(model_client, monkeypatch):
    configure(monkeypatch, "overseas")
    client = model_client()
    with client:
        login(client, "sampleoperator")
        denied = client.patch("/api/v1/models/mock", json={"enabled": False})
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "FORBIDDEN"
        response = client.put("/api/v1/models/current", json={"model": "overseas"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "MODEL_DISABLED"
        unknown = client.put("/api/v1/models/current", json={"model": "unknown"})
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "NOT_FOUND"
        assert client.put("/api/v1/models/current", json={"model": "mock"}).json() == {"current": "mock"}
        assert client.get("/api/v1/me").json()["defaultModel"] == "mock"
        login(client)
        assert client.get("/api/v1/me").json()["defaultModel"] == "auto"
        assert client.patch("/api/v1/models/mock", json={"enabled": "false"}).status_code == 422
        assert client.patch("/api/v1/models/auto", json={"enabled": False}).status_code == 404
        assert client.patch("/api/v1/models/cloud", json={"enabled": True}).json()["error"]["code"] == "MODEL_DISABLED"
        assert client.patch("/api/v1/models/overseas", json={"enabled": True}).json()["item"]["enabled"] is True

    restarted = model_client()
    with restarted:
        login(restarted, "sampleoperator")
        assert restarted.get("/api/v1/me").json()["defaultModel"] == "mock"
        login(restarted)
        assert restarted.patch("/api/v1/models/mock", json={"enabled": False}).json()["item"]["enabled"] is False
        login(restarted, "sampleoperator")
        assert restarted.get("/api/v1/me").json()["defaultModel"] == "auto"
        assert restarted.post("/api/v1/ai/chat", json={**CHAT, "model": "mock"}).status_code == 403


def test_confidential_chooses_only_intranet(model_client, monkeypatch):
    configure(monkeypatch, "cloud")
    configure(monkeypatch, "local", key=False)
    seen = []

    def respond(request):
        seen.append(request.url.host)
        assert request.url == httpx.URL("https://local.example.test/v1/chat/completions")
        assert "Authorization" not in request.headers
        payload = json.loads(request.content)
        assert payload == {**CHAT, "model": "local-configured-name"}
        return upstream_response()

    client = model_client()
    with client:
        client.app.state.jkq_models.transport = mock_transport(respond)
        login(client)
        response = client.post("/api/v1/ai/chat", json={**CHAT, "model": "cloud", "classification": "confidential"})
        assert response.status_code == 200
        assert response.json()["model"] == "local-configured-name"
        assert "按密级" in response.json()["routeNote"]
        assert seen == ["local.example.test"]


@pytest.mark.parametrize("disable_all", [False, True])
def test_confidential_denied_before_transport(model_client, monkeypatch, disable_all):
    configure(monkeypatch, "cloud")
    client = model_client()
    with client:
        client.app.state.jkq_models.transport = mock_transport(no_request)
        login(client)
        if disable_all:
            for provider in ("cloud", "mock"):
                assert client.patch(f"/api/v1/models/{provider}", json={"enabled": False}).status_code == 200
        response = client.post("/api/v1/ai/chat", json={**CHAT, "classification": "confidential"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "OUTBOUND_DENIED"
        store = client.app.state.platform.store
        assert store.audit_list("platform")[0]["action"] == "ai.outbound_denied"


@pytest.mark.parametrize("failure", ["timeout", "deadline", "5xx"])
def test_retry_next_and_audit_each_attempt(model_client, monkeypatch, failure):
    configure(monkeypatch, "cloud")
    configure(monkeypatch, "deepseek")
    seen = []

    async def respond(request):
        import anyio

        seen.append(request.url.host)
        assert request.headers["Authorization"] == "Bearer fake-test-credential"
        if request.url.host == "deepseek.example.test":
            if failure == "timeout":
                raise httpx.ReadTimeout("synthetic failure")
            if failure == "deadline":
                await anyio.sleep_forever()
            return httpx.Response(503, text="untrusted provider text")
        return upstream_response()

    monkeypatch.setenv("JKQ_MODEL_PROVIDER", "deepseek")
    client = model_client()
    with client:
        service = client.app.state.jkq_models
        service.transport = mock_transport(respond)
        login(client, "sampleoperator")
        if failure == "deadline":
            user = client.app.state.platform.directory.users()["sampleoperator"]
            body = service.chat(user, ChatBody(**CHAT), app_id="sample-app", timeout=0.25)
            audit_app = "sample-app"
        else:
            response = client.post("/api/v1/ai/chat", json=CHAT)
            assert response.status_code == 200
            body = response.json()
            audit_app = "platform"
        assert body["mock"] is False
        assert body["model"] == "cloud-configured-name"
        assert "已回退" in body["routeNote"]
        assert seen == ["deepseek.example.test", "cloud.example.test"]
        entries = [r for r in service.store.audit_list(audit_app) if r["action"] == "ai.chat"]
        assert [(r["user"], r["app"]) for r in entries] == [("sampleoperator", audit_app)] * 2
        assert entries[0]["detail"] == {
            "provider": "cloud", "model": "cloud-configured-name", "status": "success",
            "usage": {"input": 8, "output": 5},
        }
        assert entries[1]["detail"] == {
            "provider": "deepseek", "model": "deepseek-configured-name",
            "status": "provider_error" if failure == "5xx" else "timeout",
            "usage": {"input": None, "output": None},
        }


@pytest.mark.parametrize("body", [
    {"messages": []}, {**CHAT, "classification": "other"}, {**CHAT, "stream": True},
    {**CHAT, "appId": "forged-app"}, {**CHAT, "temperature": 3},
])
def test_invalid_chat_is_rejected_without_network(model_client, monkeypatch, body):
    configure(monkeypatch, "cloud")
    client = model_client()
    with client:
        client.app.state.jkq_models.transport = mock_transport(no_request)
        login(client)
        response = client.post("/api/v1/ai/chat", json=body)
        assert response.status_code == 422


@pytest.mark.parametrize("status", [302, 401])
def test_provider_rejection_does_not_redirect_or_retry(model_client, monkeypatch, status):
    configure(monkeypatch, "cloud")
    configure(monkeypatch, "deepseek")
    seen = []

    def respond(request):
        seen.append(request.url.host)
        return httpx.Response(status, headers={"Location": "https://other.example.test/"},
                              text="内部服务错误详情")

    client = model_client()
    with client:
        client.app.state.jkq_models.transport = mock_transport(respond)
        login(client)
        response = client.post("/api/v1/ai/chat", json=CHAT)
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "PROVIDER_ERROR"
        assert "内部服务错误详情" not in response.text
        assert seen == ["cloud.example.test"]


def test_missing_codex_skips_without_model_dependencies(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/smoke_model.py"), "--provider", "codex-cli"],
        env={"PATH": str(tmp_path)}, text=True, capture_output=True, check=True,
    )
    assert "跳过：本机没有 codex CLI。" in result.stdout


def test_confidential_failure_does_not_fall_back_to_cloud(model_client, monkeypatch):
    configure(monkeypatch, "cloud")
    configure(monkeypatch, "local", key=False)
    seen = []

    def unavailable(request):
        seen.append(request.url.host)
        return httpx.Response(503)

    with model_client() as client:
        login(client)
        client.app.state.jkq_models.transport = mock_transport(unavailable)
        response = client.post("/api/v1/ai/chat", json={**CHAT, "classification": "confidential"})
        assert response.status_code == 502
        assert seen == ["local.example.test"]


def test_quota_denies_without_second_provider_call(model_client, monkeypatch):
    configure(monkeypatch, "cloud")
    seen = []

    def respond(request):
        seen.append(request.url.host)
        return upstream_response(with_usage=False)

    with model_client() as client:
        login(client)
        service = client.app.state.jkq_models
        service.settings.put_quota("platform", 1)
        service.transport = mock_transport(respond)
        first = client.post("/api/v1/ai/chat", json=CHAT)
        assert first.status_code == 200
        assert first.json()["usage"] == {"input": None, "output": None}
        second = client.post("/api/v1/ai/chat", json=CHAT)
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "QUOTA_EXCEEDED"
        assert seen == ["cloud.example.test"]


def test_local_smoke_reports_only_length(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    requests = []

    class LocalProvider(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            data = upstream_response().content
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    with HTTPServer(("127.0.0.1", 0), LocalProvider) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/smoke_model.py"), "--provider", "local"],
                env={
                    "JKQ_LOCAL_MODEL_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
                    "JKQ_LOCAL_MODEL_NAME": "local-smoke-model",
                },
                cwd=tmp_path, text=True, capture_output=True, timeout=10, check=True,
            )
        finally:
            server.shutdown()
            thread.join()
    assert "local 模型冒烟通过，返回非空文本（8 字符）。" in result.stdout
    assert len(requests) == 1
    path, body = requests[0]
    assert path == "/v1/chat/completions"
    assert body["model"] == "local-smoke-model"

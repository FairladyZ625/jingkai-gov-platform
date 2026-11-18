"""模型网关用真实会话、SQLite 和无网络的模型 transport 验证。"""

import json
import os
import re
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
APP_CHAT = "/api/apps/sample-app/sdk-chat"
LOCAL_URL = "https://local.example.test/v1"


@pytest.fixture
def model_client(make_client, isolated_platform, monkeypatch):
    for key in os.environ.keys() & {
        "JKQ_MODEL_PROVIDER",
        *(f"JKQ_CODEX_MODEL_{key}" for key in ("ENABLED", "NAME", "TIMEOUT", "MAX_CONCURRENCY")),
        *(f"JKQ_{provider}_MODEL_{option}"
          for provider in ("CLOUD", "DEEPSEEK", "LOCAL", "LOCAL_BACKUP", "OVERSEAS")
          for option in ("BASE_URL", "NAME", "API_KEY", "CONFIDENTIAL_BASE_URL")),
    }:
        monkeypatch.delenv(key)

    _, apps = isolated_platform
    with (apps / "sample-app/api/router.py").open("a", encoding="utf-8") as app_router:
        app_router.write('''

from typing import Literal

@router.post("/sdk-chat/{entry}")
def sdk_chat(entry: Literal["ai", "model"], body: dict, ctx: AppContext = Depends(require("operate"))):
    handle = ctx.ai if entry == "ai" else ctx.model
    return {"available": ctx.model.available, "reply": handle.chat(**body)}

@router.post("/sdk-embedding")
def sdk_embedding(ctx: AppContext = Depends(require("operate"))):
    return ctx.ai.embedding("公开演练")
''')

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


def approve_local(monkeypatch):
    monkeypatch.setenv("JKQ_LOCAL_MODEL_CONFIDENTIAL_BASE_URL", LOCAL_URL)


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
    approve_local(monkeypatch)
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


@pytest.mark.parametrize("model", [None, "local"])
def test_confidential_denied_before_transport(model_client, monkeypatch, model):
    configure(monkeypatch, "cloud")
    client = model_client()
    with client:
        client.app.state.jkq_models.transport = mock_transport(no_request)
        login(client)
        body = {**CHAT, "classification": "confidential"}
        if model:
            body["model"] = model
        response = client.post("/api/v1/ai/chat", json=body)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "OUTBOUND_DENIED"
        store = client.app.state.platform.store
        assert [r["action"] for r in store.audit_list("platform") if r["action"].startswith("ai.")] == [
            "ai.outbound_denied",
        ]


def test_confidential_disabled_model_uses_outbound_contract(model_client, monkeypatch):
    configure(monkeypatch, "local", key=False)
    approve_local(monkeypatch)
    with model_client() as client:
        client.app.state.jkq_models.transport = mock_transport(no_request)
        login(client)
        for model in ("local", "mock"):
            assert client.patch(f"/api/v1/models/{model}", json={"enabled": False}).status_code == 200
        login(client, "sampleoperator")
        body = {**CHAT, "model": "local"}
        ordinary = client.post("/api/v1/ai/chat", json=body)
        selection = client.put("/api/v1/models/current", json={"model": "local"})
        for response in (ordinary, selection):
            assert response.status_code == 403 and response.json()["error"]["code"] == "MODEL_DISABLED"

        confidential = client.post("/api/v1/ai/chat", json={**body, "classification": "confidential"})
        assert confidential.status_code == 403
        assert confidential.json()["error"]["code"] == "OUTBOUND_DENIED"
        unknown = client.post("/api/v1/ai/chat", json={**body, "model": "unknown", "classification": "confidential"})
        assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "NOT_FOUND"
        events = [r for r in client.app.state.platform.store.audit_list("platform") if r["action"].startswith("ai.")]
        assert [{"app": r["app"], "user": r["user"], "action": r["action"], "detail": r["detail"]}
                for r in events] == [{
            "app": "platform", "user": "sampleoperator", "action": "ai.outbound_denied",
            "detail": {"capability": "chat", "classification": "confidential"},
        }]


def test_confidential_disabled_selection_can_use_approved_candidate(model_client, monkeypatch):
    configure(monkeypatch, "local", key=False)
    configure(monkeypatch, "cloud")
    approve_local(monkeypatch)
    seen = []

    def respond(request):
        seen.append(request.url.host)
        return upstream_response()

    with model_client() as client:
        client.app.state.jkq_models.transport = mock_transport(respond)
        login(client)
        assert client.patch("/api/v1/models/cloud", json={"enabled": False}).status_code == 200
        response = client.post("/api/v1/ai/chat", json={**CHAT, "model": "cloud", "classification": "confidential"})
        assert response.status_code == 200
        assert response.json()["model"] == "local-configured-name"
        assert "按密级" in response.json()["routeNote"]
        assert seen == ["local.example.test"]


@pytest.mark.parametrize("approved", [None, "http://local.example.test/v1", "https://local.example.test:8443/v1",
                                      "https://local.example.test/v2"], ids=["none", "scheme", "port", "path"])
def test_confidential_primary_requires_approved_endpoint(model_client, monkeypatch, approved):
    configure(monkeypatch, "local", key=False)
    monkeypatch.setenv("JKQ_MODEL_PROVIDER", "local")
    if approved:
        monkeypatch.setenv("JKQ_LOCAL_MODEL_CONFIDENTIAL_BASE_URL", approved)
    requests = []

    def respond(request):
        requests.append(request.url)
        return upstream_response()

    with model_client() as client:
        client.app.state.jkq_models.transport = mock_transport(respond)
        login(client, "sampleoperator")
        response = client.post("/api/v1/ai/chat", json={**CHAT, "classification": "confidential"})
        assert requests == []
        assert response.status_code == 403 and response.json()["error"]["code"] == "OUTBOUND_DENIED"
        entries = client.app.state.platform.store.audit_list("platform")
        assert [(r["action"], r["user"]) for r in entries if r["action"].startswith("ai.")] == [
            ("ai.outbound_denied", "sampleoperator"),
        ]


def test_confidential_does_not_send_to_unapproved_local_fallback(model_client, isolated_platform, monkeypatch):
    config_dir, _ = isolated_platform
    (config_dir / "models.yaml").write_text(json.dumps({
        "models": [
            {"id": ident, "kind": "openai", "group": "本地部署", "provider": ident, "env": env}
            for ident, env in (("local", "JKQ_LOCAL_MODEL"), ("local-backup", "JKQ_LOCAL_BACKUP_MODEL"))
        ],
        "confidential_providers": ["local", "local-backup"],
    }, ensure_ascii=False), encoding="utf-8")
    configure(monkeypatch, "local", key=False)
    configure(monkeypatch, "local_backup", "backup", key=False)
    monkeypatch.setenv("JKQ_LOCAL_MODEL_CONFIDENTIAL_BASE_URL", "https://LOCAL.EXAMPLE.TEST:443/v1/")
    monkeypatch.setenv("JKQ_LOCAL_BACKUP_MODEL_CONFIDENTIAL_BASE_URL", "https://backup.example.test/v2")
    seen = []

    def unavailable(request):
        seen.append(request.url)
        return httpx.Response(503)

    with model_client() as client:
        client.app.state.jkq_models.transport = mock_transport(unavailable)
        login(client, "sampleoperator")
        response = client.post("/api/v1/ai/chat", json={**CHAT, "classification": "confidential"})
        assert response.status_code == 502 and response.json()["error"]["code"] == "PROVIDER_ERROR"
        assert seen == [httpx.URL(f"{LOCAL_URL}/chat/completions")]
        entries = client.app.state.platform.store.audit_list("platform")
        assert [(r["app"], r["user"], r["detail"]) for r in entries if r["action"] == "ai.chat"] == [
            ("platform", "sampleoperator", {"provider": "local", "model": "local-configured-name",
              "status": "provider_error", "usage": {"input": None, "output": None}}),
        ]


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


@pytest.mark.parametrize("entry", ["ai", "model"])
def test_application_sdk_shares_routing_and_token_audit(model_client, monkeypatch, entry):
    configure(monkeypatch, "cloud")
    configure(monkeypatch, "deepseek")
    requests = []
    messages = [{"role": "user", "name": "demo", "content": [{"type": "text", "text": "公开演练"}]}]
    body = {"messages": messages, "temperature": 0.3, "max_tokens": 20, "timeout": 4}
    path = f"{APP_CHAT}/{entry}"

    def respond(request):
        payload = json.loads(request.content)
        requests.append((request.url.host, payload))
        if request.url.host == "deepseek.example.test":
            return httpx.Response(503)
        return upstream_response()

    client = model_client()
    platform = client.app.state.platform
    original = platform.model
    with client:
        assert platform.model is not original
        client.app.state.jkq_models.transport = mock_transport(respond)
        assert client.post(path, json=body).status_code == 401
        login(client, "sampleoperator")
        assert client.put("/api/v1/models/current", json={"model": "deepseek"}).status_code == 200
        response = client.post(path, json=body)
        assert response.status_code == 200
        result = response.json()
        assert result["available"] is True
        if entry == "ai":
            envelope = result["reply"]
            assert set(envelope) == {"result", "task_id", "capability", "provider", "model", "status", "created_at", "input"}
            assert envelope["result"] == "收到公开演练请求"
            assert envelope["provider"] == "cloud" and envelope["model"] == "cloud-configured-name"
            assert envelope["task_id"] is None and envelope["capability"] == "chat" and envelope["status"] == "success"
            assert envelope["input"]["kind"] == "text" and envelope["input"]["length"] > 0
        else:
            assert result["reply"] == "收到公开演练请求"

        login(client)
        assert client.patch("/api/v1/models/deepseek", json={"enabled": False}).status_code == 200
        login(client, "sampleoperator")
        assert client.post(path, json=body).status_code == 200
        disabled = client.post(path, json={**body, "model": "deepseek-configured-name"})
        assert disabled.status_code == 503
        assert (disabled.json()["error"]["code"] if entry == "ai" else disabled.json()["kind"]) == "not_configured"
        denied = client.post(path, json={**body, "model": "deepseek", "classification": "confidential"})
        assert denied.status_code == 403
        assert (denied.json()["error"]["code"] if entry == "ai" else denied.json()["kind"]) == "outbound_denied"

        assert requests == [
            (f"{ident}.example.test", {"messages": messages, "temperature": 0.3, "max_tokens": 20,
                                      "model": f"{ident}-configured-name"})
            for ident in ("deepseek", "cloud", "cloud")
        ]
        events = [r for r in platform.store.audit_list("sample-app") if r["action"].startswith("ai.")]
        assert [(r["app"], r["user"]) for r in events] == [("sample-app", "sampleoperator")] * 4
        assert [(r["action"], r["detail"]) for r in events] == [
            ("ai.outbound_denied", {"capability": "chat", "classification": "confidential"}),
            *[("ai.chat", {"provider": "cloud", "model": "cloud-configured-name", "status": "success",
                          "usage": {"input": 8, "output": 5}})] * 2,
            ("ai.chat", {"provider": "deepseek", "model": "deepseek-configured-name", "status": "provider_error",
                         "usage": {"input": None, "output": None}}),
        ]
        # #19 用量统计直接汇总网关逐次审计，三个维度与上面的记录一致。
        from jkq.admin.usage import usage_page
        with platform.store._lock:
            db = platform.store._db
            assert usage_page(db, "app")["items"] == [
                {"app": "sample-app", "calls": 3, "input": 16, "output": 10}]
            assert usage_page(db, "model")["items"] == [
                {"model": "cloud-configured-name", "calls": 2, "input": 16, "output": 10},
                {"model": "deepseek-configured-name", "calls": 1, "input": 0, "output": 0}]
            assert usage_page(db, "user")["items"] == [
                {"user": "sampleoperator", "calls": 3, "input": 16, "output": 10}]

        login(client)
        assert client.patch("/api/v1/models/cloud", json={"enabled": False}).status_code == 200
        mock = client.post(path, json=body).json()
        assert mock["available"] is False
        assert (mock["reply"]["result"] if entry == "ai" else mock["reply"]).startswith("[模拟模型]")
        usage = client.get("/api/model/usage").json()
        assert usage["mode"] == "mock" and usage["scope"] == "process"
        if entry == "model":
            assert usage["calls"] == {"sample-app": 5}
            assert usage["usage"] == {"sample-app": {"total": 5, "success": 3, "failure": 2, "mock": 1}}
        else:
            assert usage["calls"] == usage["usage"] == {}
    assert platform.model is original
    assert not hasattr(client.app.state, "jkq_models")


def test_application_sdk_media_and_legacy_options_cannot_bypass_confidential_boundary(model_client):
    with model_client() as client:
        service = client.app.state.jkq_models
        service.transport = mock_transport(no_request)
        login(client)
        assert client.put("/api/v1/admin/ai/providers/legacy-mock", json={
            "kind": "mock", "models": ["legacy-model"], "allow_outbound": "confidential",
        }).status_code == 200
        for capability in ("chat", "embedding"):
            assert client.put(f"/api/v1/admin/ai/routes/{capability}", json={
                "provider": "legacy-mock", "model": "legacy-model",
            }).status_code == 200

        image = "data:image/png;base64,aW1hZ2U="
        ai_media = {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": image}}]}]}
        for entry, body in (("ai", ai_media), ("model", {**CHAT, "images": [image]})):
            legacy = client.post(f"{APP_CHAT}/{entry}", json=body)
            assert legacy.status_code == 200
            result = legacy.json()["reply"]
            assert (result["result"] if entry == "ai" else result).startswith("[模拟模型]")
            denied = client.post(f"{APP_CHAT}/{entry}", json={**body, "classification": "confidential"})
            assert denied.status_code == 400
            error = denied.json()
            assert (error["error"]["code"] if entry == "ai" else error["kind"]) == "bad_input"
            stream = client.post(f"{APP_CHAT}/{entry}", json={**CHAT, "stream": True, "classification": "confidential"})
            assert stream.status_code == 400
        embedding = client.post("/api/apps/sample-app/sdk-embedding")
        assert embedding.status_code == 200
        assert embedding.json()["provider"] == "legacy-mock" and embedding.json()["capability"] == "embedding"


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


def test_default_smoke_skips_without_configuration(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/smoke_model.py")],
        env={}, cwd=tmp_path, text=True, capture_output=True, timeout=10, check=True,
    )
    assert "跳过：未配置模型服务地址。" in result.stdout


def test_confidential_failure_does_not_fall_back_to_cloud(model_client, monkeypatch):
    configure(monkeypatch, "cloud")
    configure(monkeypatch, "local", key=False)
    approve_local(monkeypatch)
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


def test_default_local_smoke_reports_only_length(tmp_path):
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
                [sys.executable, str(ROOT / "scripts/smoke_model.py")],
                env={
                    "JKQ_LOCAL_MODEL_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
                    "JKQ_LOCAL_MODEL_NAME": "local-smoke-model",
                },
                cwd=tmp_path, text=True, capture_output=True, timeout=10, check=True,
            )
        finally:
            server.shutdown()
            thread.join()
    length = re.fullmatch(r"local 模型冒烟通过，返回非空文本（(\d+) 字符）。", result.stdout.strip())
    assert length and int(length[1]) == len(upstream_response().json()["choices"][0]["message"]["content"])
    assert len(requests) == 1
    path, body = requests[0]
    assert path == "/v1/chat/completions"
    assert body["model"] == "local-smoke-model"

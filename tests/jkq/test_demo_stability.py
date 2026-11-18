from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from haiknow_core.aihub.errors import AIError
from jkq import demo
from jkq.auth import AuthError, current_user, _error_response


@pytest.fixture
def instance(tmp_path, monkeypatch):
    app = FastAPI()
    events = []
    app.state.platform = SimpleNamespace(
        config_dir=tmp_path, store=SimpleNamespace(audit=lambda *args: events.append(args)),
        rbac=SimpleNamespace(actions=lambda user, _: user.roles),
    )
    app.state.jkq_models = SimpleNamespace(call=None, providers={})

    @app.exception_handler(AuthError)
    async def auth_error(request, error):
        return _error_response(error)

    monkeypatch.setenv("JKQ_DEMO_MODE", "1")
    return app, events


def test_reset_is_hidden_in_production(instance, monkeypatch):
    app, _ = instance
    monkeypatch.delenv("JKQ_DEMO_MODE")
    demo.install(app)
    assert TestClient(app).post("/api/v1/demo/reset").status_code == 404


def test_reset_requires_admin_and_host_receipt(instance, monkeypatch):
    app, events = instance
    monkeypatch.setenv("JKQ_DEMO_RESET_SOCKET", "/example/demo.sock")
    demo.install(app)
    client = TestClient(app)
    def anonymous():
        raise AuthError(401, "UNAUTHENTICATED", "请先登录")

    app.dependency_overrides[current_user] = anonymous
    url = "/api/v1/demo/reset"
    assert client.post(url).status_code == 401
    user = SimpleNamespace(id="sample", roles=["view"])
    app.dependency_overrides[current_user] = lambda: user
    assert client.post(url).status_code == 403
    user.roles.append("admin")
    requests = []
    def accept(path):
        requests.append(path)
        return {"ok": True}

    monkeypatch.setattr(demo, "request_reset", accept)
    response = client.post(url)
    assert response.status_code == 202 and response.json() == {"ok": True}
    assert requests == ["/example/demo.sock"] and events[-1][2] == "demo.reset.accepted"


@pytest.mark.parametrize("status,body,accepted", [(202, {"ok": True}, True), (200, {"ok": True}, False),
                                                 (202, {"ok": 1}, False), (503, {}, False)])
def test_host_protocol(monkeypatch, status, body, accepted):
    def host(request):
        assert request.method == "POST" and request.url.path == "/reset"
        return httpx.Response(status, json=body)

    monkeypatch.setattr(httpx, "HTTPTransport", lambda *, uds: httpx.MockTransport(host))
    if accepted:
        assert demo.request_reset("/example/demo.sock") == {"ok": True}
    else:
        with pytest.raises(AuthError, match="未能确认"):
            demo.request_reset("/example/demo.sock")


class Service:
    providers = {"live": {"kind": "openai"}, "offline": {"kind": "mock"}}

    def call(self, user, payload, **kwargs):
        if self.providers["live"] and payload.get("error"):
            raise AIError(payload["error"], "模拟上游故障")
        mock = self.providers["live"] is None
        return {"result": {"mock": mock, "content": "模拟回复" if mock else "真实路径"}}, ""


def test_switches_are_independent_and_preserve_access_errors():
    service = Service()
    opts = demo.Options(mock_modules={"meeting"}, rule_intent_first=False)
    demo.bind_demo_models(service, None, opts)
    payload = {"classification": "internal"}
    assert service.call(None, payload, app_id="meeting")[0]["result"]["mock"]
    assert service.call(None, payload, app_id="policy")[0]["result"]["content"] == "真实路径"
    assert "预置结果" in service.call(None, {**payload, "error": "timeout"})[0]["result"]["content"]
    for kind in ("outbound_denied", "quota_exceeded", "model_disabled"):
        with pytest.raises(AIError):
            service.call(None, {**payload, "error": kind})
    with pytest.raises(AIError):
        service.call(None, {"classification": "confidential", "error": "timeout"}, app_id="meeting")
    service = Service()
    demo.bind_demo_models(service, None, demo.Options(preset_on_failure=False))
    with pytest.raises(AIError):
        service.call(None, {**payload, "error": "timeout"})


def test_module_config_changes_only_one_http_module(tmp_path):
    import json
    import subprocess

    config = tmp_path / "config"
    config.mkdir()
    source = "window.JK_CONFIG = {api: {mode: globalMode, modules: {kb: 'http'}}};"
    (config / "app.config.js").write_text(source)
    app = FastAPI()
    demo.install_module_config(app, tmp_path, {"meeting"})
    script = TestClient(app).get("/config/app.config.js").text
    for mode, expected in [("http", {"kb": "http", "meeting": "mock"}), ("mock", {"kb": "http"})]:
        code = f"const window = {{}}, globalMode = '{mode}';\n" + script
        code += "\nconsole.log(JSON.stringify(window.JK_CONFIG.api));"
        result = subprocess.run(["node", "-"], input=code, text=True, capture_output=True, check=True)
        assert json.loads(result.stdout) == {"mode": mode, "modules": expected}

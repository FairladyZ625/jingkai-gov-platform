"""模型网关的离线回归测试：所有 HTTP 都只访问本机或 MockTransport。"""
import asyncio
import base64
import copy
import json
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import httpx

from conftest import ROOT
from haiknow_core.model import ModelGateway
from haiknow_core import model as model_module
from haiknow_core.store import AppFiles
from haiknow_sdk import ModelError

MESSAGES = [{"role": "user", "content": "请总结检验项"}]
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")


def completion(text="桩服务结果"):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@pytest.fixture
def stub(monkeypatch):
    original = httpx.AsyncClient
    requests = []

    def install(handler):
        async def respond(request):
            requests.append(json.loads(request.content))
            result = handler(request)
            return await result if asyncio.iscoroutine(result) else result

        transport = httpx.MockTransport(respond)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw))
        return requests

    return install


@contextmanager
def ark_server(*, stall=0, trickle=False):
    """可观测请求、停顿或逐字节响应的本地 HTTP 桩。"""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"path": self.path, "body": body})
            time.sleep(stall)
            data = json.dumps({"choices": [{"message": {"content": "桩服务真实往返"}}]}).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if trickle:
                    for byte in data:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.02)
                else:
                    self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass  # 客户端超时取消后，桩不再写响应

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api/v3", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def configure(monkeypatch, base="http://ark.test/api/v3"):
    monkeypatch.setenv("HAIKNOW_MODEL_BASE_URL", base)
    monkeypatch.setenv("HAIKNOW_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("HAIKNOW_MODEL_NAME", "test-model")
    return ModelGateway()


def test_httpx_is_runtime_dependency():
    deps = (ROOT / "requirements.txt").read_text().splitlines()
    assert any(line.startswith("httpx") for line in deps), "生产环境只安装 requirements.txt 也必须能导入模型网关"


def test_timeout_is_total_budget_including_retry(monkeypatch):
    # 把 60 秒验收预算缩到 0.3 秒，实测两次请求不得各自重置预算。
    with ark_server(stall=1) as (base, requests):
        gw = configure(monkeypatch, base)
        started = time.monotonic()
        with pytest.raises(ModelError) as error:
            gw.chat("sample-app", [{"role": "user", "content": "测试超时"}], timeout=0.3)
        elapsed = time.monotonic() - started
        print(f"elapsed={elapsed:.3f}s, budget=0.3s, requests={len(requests)}")
        assert elapsed < 0.5, f"重试重置了总预算：{elapsed:.3f}s"
        assert error.value.kind == "timeout"


def test_unconfigured_falls_back_without_http(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda: pytest.fail("模拟模式不得发 HTTP"))
    gw = ModelGateway()
    app = gw.for_app("mock-app")
    assert not app.available
    assert app.chat(MESSAGES).startswith("[模拟模型]")
    assert gw.calls == {"mock-app": 1}
    assert gw.usage() == {"mock-app": {"total": 1, "success": 1, "failure": 0, "mock": 1}}


def test_partial_configuration_reports_error(monkeypatch, stub):
    requests = stub(lambda _: pytest.fail("配置不完整不得发 HTTP"))
    monkeypatch.setenv("HAIKNOW_MODEL_BASE_URL", "http://ark.test/api/v3")
    gw = ModelGateway()
    with pytest.raises(ModelError) as error:
        gw.for_app("partial").chat(MESSAGES)
    assert error.value.kind == "not_configured"
    assert not requests
    assert gw.usage()["partial"]["failure"] == 1


def test_local_http_roundtrip(monkeypatch):
    with ark_server() as (base, requests):
        gw = configure(monkeypatch, base)
        result = gw.for_app("sample-app").chat(MESSAGES)
        print(f"local roundtrip result={result!r}, path={requests[0]['path']}, requests={len(requests)}")
        assert result == "桩服务真实往返"
        assert requests == [{"path": "/api/v3/chat/completions", "body": {"model": "test-model", "messages": MESSAGES}}]


def test_trickling_response_obeys_total_deadline(monkeypatch):
    with ark_server(trickle=True) as (base, _):
        gw = configure(monkeypatch, base)
        started = time.monotonic()
        with pytest.raises(ModelError) as error:
            gw.for_app("slow").chat(MESSAGES, timeout=0.3)
        elapsed = time.monotonic() - started
        print(f"trickle elapsed={elapsed:.3f}s, budget=0.3s")
        assert error.value.kind == "timeout"
        assert elapsed < 0.5


def test_caller_cannot_extend_platform_timeout(monkeypatch, stub):
    # 缩短平台常量加速验收；调用方传大值仍不能取消上限。
    assert model_module.TOTAL_TIMEOUT <= 50
    monkeypatch.setattr(model_module, "TOTAL_TIMEOUT", 0.12)
    async def slow(_):
        await asyncio.sleep(1)
        return completion()
    requests = stub(slow)
    gw = configure(monkeypatch)
    started = time.monotonic()
    with pytest.raises(ModelError) as error:
        gw.chat("capped", MESSAGES, timeout=1000)
    elapsed = time.monotonic() - started
    print(f"capped elapsed={elapsed:.3f}s, platform budget=0.12s, caller budget=1000s")
    assert elapsed < 0.3
    assert error.value.kind == "timeout"
    assert len(requests) == 1


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout_cannot_disable_deadline(monkeypatch, stub, timeout):
    requests = stub(lambda _: pytest.fail("无效超时不得发送请求"))
    gw = configure(monkeypatch)
    with pytest.raises(ValueError, match="timeout"):
        gw.chat("invalid", MESSAGES, timeout=timeout)
    assert not requests


@pytest.mark.parametrize("model", [None, "vision-model"])
def test_model_override_and_options(monkeypatch, stub, model):
    requests = stub(lambda _: completion())
    gw = configure(monkeypatch)
    assert gw.for_app("demo").chat(MESSAGES, model=model, temperature=0.2) == "桩服务结果"
    assert requests[0] == {"model": model or "test-model", "messages": MESSAGES, "temperature": 0.2}


def test_call_model_without_default_name(monkeypatch, stub):
    requests = stub(lambda _: completion())
    configure(monkeypatch)
    monkeypatch.delenv("HAIKNOW_MODEL_NAME")
    app = ModelGateway().for_app("override")
    assert not app.available
    assert app.chat(MESSAGES, model="vision-model") == "桩服务结果"
    assert requests[0]["model"] == "vision-model"


@pytest.mark.parametrize("failure", ["connect", "timeout", 500, 503])
def test_transient_error_retries_once_and_counts_one_call(monkeypatch, stub, failure):
    attempts = 0
    def respond(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if failure == "connect":
                raise httpx.ConnectError("离线桩", request=request)
            if failure == "timeout":
                raise httpx.ReadTimeout("离线桩", request=request)
            return httpx.Response(failure)
        return completion()
    requests = stub(respond)
    gw = configure(monkeypatch)
    assert gw.for_app("retry").chat(MESSAGES) == "桩服务结果"
    assert len(requests) == 2
    assert gw.usage()["retry"] == {"total": 1, "success": 1, "failure": 0, "mock": 0}


def test_attempt_deadline_retries_within_remaining_budget(monkeypatch, stub):
    monkeypatch.setattr(model_module, "ATTEMPT_TIMEOUT", 0.05)
    attempts = 0
    async def respond(_):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await asyncio.sleep(1)
        return completion()
    requests = stub(respond)
    gw = configure(monkeypatch)
    assert gw.chat("retry", MESSAGES, timeout=0.3) == "桩服务结果"
    assert len(requests) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429])
def test_client_error_is_not_retried_or_leaked(monkeypatch, stub, status):
    requests = stub(lambda _: httpx.Response(status, text="private-provider-body test-key"))
    gw = configure(monkeypatch)
    with pytest.raises(ModelError) as error:
        gw.for_app("client-error").chat(MESSAGES)
    assert error.value.kind == "http" and error.value.status_code == status
    assert "test-key" not in str(error.value) and "private-provider-body" not in str(error.value)
    assert len(requests) == 1
    assert gw.usage()["client-error"]["failure"] == 1


@pytest.mark.parametrize("failure,kind", [(503, "http"), ("connect", "http"), ("timeout", "timeout"), ("protocol", "http")])
def test_terminal_network_failure_is_classified(monkeypatch, stub, failure, kind):
    def respond(request):
        if failure == "connect":
            raise httpx.ConnectError("离线桩", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("离线桩", request=request)
        if failure == "protocol":
            raise httpx.RemoteProtocolError("离线桩", request=request)
        return httpx.Response(failure)
    requests = stub(respond)
    gw = configure(monkeypatch)
    with pytest.raises(ModelError) as error:
        gw.for_app("terminal").chat(MESSAGES)
    assert error.value.kind == kind
    assert len(requests) == (1 if failure == "protocol" else 2)
    assert gw.calls == {"terminal": 1}


@pytest.mark.parametrize("body", [None, {}, {"choices": []}, {"choices": [{"message": {"content": None}}]}, {"choices": [{"message": {"content": []}}]}])
def test_bad_response_is_not_retried(monkeypatch, stub, body):
    requests = stub(lambda _: httpx.Response(200, json=body) if body is not None else httpx.Response(200, text="not JSON"))
    gw = configure(monkeypatch)
    with pytest.raises(ModelError) as error:
        gw.for_app("bad").chat(MESSAGES)
    assert error.value.kind == "bad_response"
    assert len(requests) == 1


def test_multimodal_messages_pass_through(monkeypatch, stub):
    requests = stub(lambda _: completion())
    gw = configure(monkeypatch)
    messages = [{"role": "user", "content": [{"type": "text", "text": "识图"}, {"type": "image_url", "image_url": {"url": "https://example.test/image.png"}}]}]
    assert gw.for_app("vision").chat(messages) == "桩服务结果"
    assert requests[0]["messages"] == messages


@pytest.mark.parametrize("data,mime", [(PNG, "image/png"), (b"\xff\xd8\xff\xe0", "image/jpeg"), (b"GIF89a", "image/gif"), (b"RIFF1234WEBP", "image/webp")], ids=["png", "jpeg", "gif", "webp"])
def test_file_and_base64_images_append_without_mutation(monkeypatch, stub, tmp_path, data, mime):
    requests = stub(lambda _: completion())
    gw = configure(monkeypatch)
    files = AppFiles(tmp_path, "vision")
    fid = files.save("image", data)
    encoded = base64.b64encode(data).decode()
    url = f"data:{mime};base64,{encoded}"
    messages = copy.deepcopy(MESSAGES) + [{"role": "assistant", "content": "历史回复"}]
    before = copy.deepcopy(messages)
    app = gw.for_app("vision", files)
    app.chat(messages, images=[fid, encoded, url])
    assert messages == before
    parts = requests[0]["messages"][0]["content"]
    assert parts == [{"type": "text", "text": "请总结检验项"}] + [{"type": "image_url", "image_url": {"url": url}}] * 3
    assert "images" not in requests[0]


def test_images_append_to_existing_parts(monkeypatch, stub):
    requests = stub(lambda _: completion())
    gw = configure(monkeypatch)
    messages = [{"role": "user", "content": [{"type": "text", "text": "原文"}]}]
    before = copy.deepcopy(messages)
    gw.for_app("vision").chat(messages, images=[base64.b64encode(PNG).decode()])
    assert messages == before
    assert len(requests[0]["messages"][0]["content"]) == 2


def test_images_cannot_read_another_app_file(monkeypatch, stub, tmp_path):
    requests = stub(lambda _: pytest.fail("文件隔离检查失败时不得发 HTTP"))
    gw = configure(monkeypatch)
    other = AppFiles(tmp_path, "other")
    fid = other.save("photo.png", PNG)
    app = gw.for_app("vision", AppFiles(tmp_path, "vision"))
    for image in (fid, f"../other/{fid}", str(other.dir / fid)):
        with pytest.raises(FileNotFoundError):
            app.chat(MESSAGES, images=[image])
    assert not requests
    assert gw.usage()["vision"]["failure"] == 3


def test_invalid_image_input_surfaces_own_error(monkeypatch, stub):
    requests = stub(lambda _: pytest.fail("无效图片不得发 HTTP"))
    gw = configure(monkeypatch)
    with pytest.raises(ValueError, match="user"):
        gw.for_app("vision").chat([], images=[base64.b64encode(PNG).decode()])
    with pytest.raises(ValueError, match="PNG"):
        gw.for_app("vision").chat(MESSAGES, images=[base64.b64encode(b"not an image").decode()])
    assert not requests


def test_usage_is_per_app_and_safe_under_concurrency(monkeypatch, stub):
    stub(lambda _: completion())
    gw = configure(monkeypatch)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: gw.for_app(f"app-{i % 2}").chat(MESSAGES), range(20)))
    assert gw.usage() == {f"app-{i}": {"total": 10, "success": 10, "failure": 0, "mock": 0} for i in range(2)}
    snapshot = gw.usage()
    snapshot["app-0"]["total"] = -1
    assert gw.calls["app-0"] == 10


def test_sync_api_can_be_called_from_event_loop(monkeypatch, stub):
    stub(lambda _: completion())
    gw = configure(monkeypatch)
    async def route():
        return gw.for_app("async").chat(MESSAGES)
    assert asyncio.run(route()) == "桩服务结果"


def test_native_tls_error_maps_to_retryable_http(monkeypatch):
    """没有 AI 路由时走旧 ModelGateway；原生 TLS 异常也不能漏成未分类异常。"""
    original = httpx.AsyncClient

    def bad_tls(request):
        raise ssl.SSLError(1, "[SSL: SSLV3_ALERT_BAD_RECORD_MAC] bad record mac")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(bad_tls), **kw))
    gw = configure(monkeypatch)
    with pytest.raises(ModelError) as error:
        gw.for_app("legacy-tls").chat(MESSAGES)
    assert error.value.kind == "http" and error.value.status_code is None
    assert "连接中断" in str(error.value)
    assert "SSLError" not in str(error.value) and "BAD_RECORD_MAC" not in str(error.value)
    assert gw.usage()["legacy-tls"] == {"total": 1, "success": 0, "failure": 1, "mock": 0}

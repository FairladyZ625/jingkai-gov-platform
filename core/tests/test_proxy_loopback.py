"""本机开着代理时，测试内起的回环 HTTP / WebSocket 服务仍直连。

check.py 给测试子进程注入 NO_PROXY；直接 pytest 时由 conftest.py 在 import 阶段注入。
这里同时守 helper 的追加/保留语义，以及坏代理下回环 HTTP 与 WebSocket 真的能通。
"""
from __future__ import annotations

import importlib.util
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from websockets.sync.client import connect
from websockets.sync.server import serve

from conftest import ROOT, ensure_loopback_no_proxy as conftest_ensure

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
BAD_PROXY = "http://127.0.0.1:9"


def _load_check():
    spec = importlib.util.spec_from_file_location("repo_check_proxy", ROOT / "scripts" / "check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load_check()
ENSURE = [pytest.param(conftest_ensure, id="conftest"), pytest.param(check.ensure_loopback_no_proxy, id="check")]


def _entries(value: str) -> set[str]:
    return {e for e in re.split(r"[,\s]+", value) if e}


@pytest.mark.parametrize("ensure", ENSURE)
def test_existing_no_proxy_is_preserved_and_loopback_appended(ensure):
    out = ensure({"NO_PROXY": "corp.example,localhost", "no_proxy": "10.0.0.0/8"})
    assert out["NO_PROXY"] == "corp.example,localhost,127.0.0.1,::1"
    assert out["no_proxy"] == "10.0.0.0/8,127.0.0.1,localhost,::1"
    assert ensure(dict(out)) == out  # 重复调用幂等


@pytest.mark.parametrize("ensure", ENSURE)
def test_loopback_added_when_absent_and_star_left_alone(ensure):
    assert ensure({}) == {"NO_PROXY": "127.0.0.1,localhost,::1", "no_proxy": "127.0.0.1,localhost,::1"}
    assert ensure({"NO_PROXY": "*", "no_proxy": "*"}) == {"NO_PROXY": "*", "no_proxy": "*"}


def test_check_child_env_keeps_host_env_and_adds_loopback():
    env = check._test_env(ADMIN_AI_JS="core/web/admin-ai.js")
    assert env["ADMIN_AI_JS"] == "core/web/admin-ai.js"
    if "PATH" in os.environ:
        assert env["PATH"] == os.environ["PATH"]
    for key in ("NO_PROXY", "no_proxy"):
        entries = _entries(env[key])
        assert "*" in entries or LOOPBACK <= entries, f"{key} 没有回环地址：{env[key]!r}"


def test_check_child_env_keeps_star_no_proxy(monkeypatch):
    """NO_PROXY=* 已覆盖全部回环，helper 不应改写它；check.py 子进程同样保留。"""
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    env = check._test_env()
    assert _entries(env["NO_PROXY"]) == {"*"}
    assert _entries(env["no_proxy"]) == {"*"}


class _Pong(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"pong"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 测试输出保持安静
        pass


def _echo(socket):
    with socket:
        for message in socket:
            socket.send("echo:" + message)


def test_loopback_http_and_websocket_bypass_bad_proxy(monkeypatch):
    # websockets>=13 的 sync connect 默认 proxy=True，会读 NO_PROXY 与代理 env；WS 支路真实覆盖绕过。
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, BAD_PROXY)
    for key in ("NO_PROXY", "no_proxy"):
        entries = _entries(os.environ.get(key, ""))
        assert "*" in entries or LOOPBACK <= entries, f"{key} 没有回环地址：{os.environ.get(key)!r}"

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Pong)
    http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    http_thread.start()
    ws_server = serve(_echo, "127.0.0.1", 0)
    ws_thread = threading.Thread(target=ws_server.serve_forever, daemon=True)
    ws_thread.start()
    try:
        http_port = httpd.server_address[1]
        assert httpx.get(f"http://127.0.0.1:{http_port}/ping", timeout=5).text == "pong"

        ws_port = ws_server.socket.getsockname()[1]
        with connect(f"ws://127.0.0.1:{ws_port}", open_timeout=5) as socket:
            socket.send("hi")
            assert socket.recv(timeout=5) == "echo:hi"
    finally:
        ws_server.shutdown()
        ws_thread.join(5)
        httpd.shutdown()
        httpd.server_close()
        http_thread.join(5)

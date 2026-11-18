import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("fastapi", reason="仓库轻量 CI 只安装 pytest，Core 检查覆盖知识库模块")

from jkq.kb.importer.public_url import PublicURLError, PublicURLReader, TOTAL_TIMEOUT

PUBLIC = "https://example.invalid/a"
PUBLIC_IP = "8.8.8.8"
FORBIDDEN = [
    "http://localhost", "http://127.0.0.1", "http://10.2.3.4", "http://172.31.2.3",
    "http://192.168.2.3", "file:///example", "http://169.254.1.1", "http://100.64.0.1",
    "http://[::1]", "http://[::ffff:127.0.0.1]", "http://[fe80::1]", "http://224.0.0.1",
    "http://[ff02::1]", "http://[64:ff9b::a00:1]", "http://fake:pass@example.invalid/",
    "https://@example.invalid/", "http://[invalid", "http://example.invalid:0",
]


@dataclass
class Response:
    status_code: int
    headers: dict = field(default_factory=dict)
    body: bytes = b"OK"
    charset_encoding: str = "utf-8"

    async def aiter_raw(self):
        yield self.body


@pytest.mark.parametrize("url", FORBIDDEN)
@pytest.mark.parametrize("redirect", [False, True], ids=["direct", "redirect"])
def test_forbidden_addresses_never_reach_transport(url, redirect):
    resolve = AsyncMock(return_value=[PUBLIC_IP])
    opened = []

    @asynccontextmanager
    async def request(target):
        opened.append(target.url)
        yield Response(302, {"location": url})

    reader = PublicURLReader(resolve=resolve, open_response=request)
    with pytest.raises(PublicURLError) as denied:
        asyncio.run(reader.read(PUBLIC if redirect else url))
    assert (denied.value.status, denied.value.code) == (400, "URL_NOT_ALLOWED")
    assert opened == ([PUBLIC] if redirect else [])
    assert resolve.await_count == int(redirect)


@pytest.mark.parametrize("addresses", [
    ["10.2.3.4"], [PUBLIC_IP, "192.168.4.3"], ["::ffff:172.31.0.2"], ["fc00::21"],
])
@pytest.mark.parametrize("redirect", [False, True], ids=["direct", "redirect"])
def test_dns_private_or_mixed_answers_refused(addresses, redirect):
    resolved = AsyncMock(side_effect=([[PUBLIC_IP], addresses] if redirect else [addresses]))
    opened = []

    @asynccontextmanager
    async def request(target):
        opened.append(str(target.address))
        yield Response(307, {"location": "https://other.invalid/target"})

    with pytest.raises(PublicURLError) as denied:
        asyncio.run(PublicURLReader(resolve=resolved, open_response=request).read(PUBLIC))
    assert denied.value.code == "URL_NOT_ALLOWED"
    assert opened == ([PUBLIC_IP] if redirect else [])


def test_reresolve_same_hostname_each_hop_and_only_allow_validated_addresses():
    resolved = AsyncMock(side_effect=[[PUBLIC_IP], ["1.1.1.1"]])
    opened = []

    @asynccontextmanager
    async def request(target):
        opened.append((target.connection_url, target.host))
        if target.url == PUBLIC:
            yield Response(302, {"location": "/final#anchor"})
        else:
            yield Response(200, {"content-type": "text/plain"}, "第一条 读取正文。".encode())

    page = asyncio.run(PublicURLReader(resolve=resolved, open_response=request).read(PUBLIC))
    assert page.text == "第一条 读取正文。"
    assert page.url == "https://example.invalid/final"
    assert opened == [("https://8.8.8.8:443/a", "example.invalid"),
                      ("https://1.1.1.1:443/final", "example.invalid")]
    assert resolved.await_count == 2


@pytest.mark.parametrize("phase", ["dns", "redirect", "body"])
def test_total_timeout_covers_every_await(phase):
    assert TOTAL_TIMEOUT == 15
    awaited = []

    async def stall(where):
        awaited.append(where)
        await asyncio.Event().wait()

    async def resolve(host, port):
        if phase == "dns" or (phase == "redirect" and host == "second.invalid"):
            await stall(phase)
        return [PUBLIC_IP]

    class SlowBody(Response):
        async def aiter_raw(self):
            await stall("body")
            yield b""

    @asynccontextmanager
    async def request(target):
        if phase == "redirect":
            yield Response(302, {"location": "https://second.invalid/"})
        else:
            yield SlowBody(200, {"content-type": "text/plain"})

    with pytest.raises(PublicURLError) as denied:
        asyncio.run(PublicURLReader(resolve=resolve, open_response=request, timeout=0.05).read(PUBLIC))
    assert (denied.value.status, denied.value.code) == (504, "URL_FETCH_TIMEOUT")
    assert awaited == [phase]


def test_all_hops_share_one_timeout_scope():
    scopes = []

    @asynccontextmanager
    async def timeout(delay):
        scopes.append(delay)
        yield

    resolve = AsyncMock(return_value=[PUBLIC_IP])

    @asynccontextmanager
    async def request(target):
        if target.url == PUBLIC:
            yield Response(302, {"location": "/final"})
        else:
            yield Response(200, {"content-type": "text/plain"})

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(asyncio, "timeout", timeout)
        asyncio.run(PublicURLReader(resolve=resolve, open_response=request).read(PUBLIC))
    assert scopes == [15]
    assert resolve.await_count == 2


@pytest.mark.parametrize("response", [
    Response(503), Response(302), Response(200, {"content-type": "image/png"}),
    Response(200, {"content-type": "text/plain"}, b""),
    Response(200, {"content-type": "text/plain", "content-encoding": "gzip"}),
])
def test_public_response_failure_has_no_upstream_payload(response):
    @asynccontextmanager
    async def request(target):
        yield response

    resolve = AsyncMock(return_value=[PUBLIC_IP])
    with pytest.raises(PublicURLError) as error:
        asyncio.run(PublicURLReader(resolve=resolve, open_response=request).read(PUBLIC))
    assert (error.value.status, error.value.code) == (502, "URL_FETCH_FAILED")


def test_http_transport_pins_tcp_ip_and_verifies_original_tls_name(monkeypatch):
    pytest.importorskip("httpx")
    from httpcore._backends.auto import AutoBackend
    from httpcore._backends.mock import AsyncMockStream

    events = []

    class Stream(AsyncMockStream):
        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            events.append(("tls", server_hostname, ssl_context.check_hostname, ssl_context.verify_mode))
            return self

        async def write(self, buffer, timeout=None):
            events.append(("write", buffer))

    async def connect(self, host, port, **kwargs):
        events.append(("tcp", host, port))
        if host == PUBLIC_IP:
            return Stream([b"HTTP/1.1 302 Found\r\nLocation: https://second.invalid/final\r\n"
                           b"Content-Length: 0\r\n\r\n"])
        return Stream([b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nOK"])

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9000")
    monkeypatch.setattr(AutoBackend, "connect_tcp", connect)
    resolve = AsyncMock(side_effect=[[PUBLIC_IP], ["1.1.1.1"]])
    page = asyncio.run(PublicURLReader(resolve=resolve).read(PUBLIC))
    assert page.text == "OK" and page.url == "https://second.invalid/final"
    assert [event for event in events if event[0] == "tcp"] == [
        ("tcp", PUBLIC_IP, 443), ("tcp", "1.1.1.1", 443),
    ]
    assert [event for event in events if event[0] == "tls"] == [
        ("tls", "example.invalid", True, 2), ("tls", "second.invalid", True, 2),
    ]
    requests = [event[1] for event in events if event[0] == "write"]
    assert any(b"GET /a HTTP/1.1\r\nHost: example.invalid\r\n" in request for request in requests)
    assert any(b"GET /final HTTP/1.1\r\nHost: second.invalid\r\n" in request for request in requests)

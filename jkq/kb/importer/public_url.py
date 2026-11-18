"""公网页面读取。每跳独立解析，HTTP 连接使用已校验的数字地址。"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

TOTAL_TIMEOUT = 15
MAX_REDIRECTS = 3
MAX_BYTES = 2 * 1024 * 1024
REDIRECTS = {301, 302, 303, 307, 308}


class PublicURLError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


def _not_allowed():
    return PublicURLError(400, "URL_NOT_ALLOWED", "只允许读取公开的 HTTP 或 HTTPS 网页地址")


def _fetch_failed(message="无法读取公开网页，请检查网址或改用粘贴正文"):
    return PublicURLError(502, "URL_FETCH_FAILED", message)


@dataclass(frozen=True)
class _Target:
    url: str
    host: str
    authority: str
    port: int
    address: ipaddress.IPv4Address | ipaddress.IPv6Address

    @property
    def connection_url(self):
        parts = urlsplit(self.url)
        host = f"[{self.address}]" if self.address.version == 6 else str(self.address)
        return urlunsplit(parts._replace(netloc=f"{host}:{self.port}"))


@dataclass(frozen=True)
class PublicPage:
    url: str
    title: str
    text: str


def _check_url_text(url):
    if (not isinstance(url, str) or not url or len(url) > 8192
            or re.search(r"[\\\s\x00-\x1f\x7f\ud800-\udfff]", url)):
        raise _not_allowed()


async def _resolve(host, port):
    result = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in result]


def _public_ip(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise _not_allowed() from None
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if (not address.is_global or address.is_multicast or address.is_reserved
            or (address.version == 6 and (address.scope_id or address.is_site_local or address.sixtofour))):
        raise _not_allowed()
    return address


async def _target(url, resolve):
    _check_url_text(url)
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise _not_allowed() from None
    if parts.scheme not in ("http", "https") or not host or parts.username is not None or "%" in host or port == 0:
        raise _not_allowed()

    default_port = 443 if parts.scheme == "https" else 80
    port = port or default_port
    host = host.removesuffix(".")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        addresses = [_public_ip(literal)]
        host = str(literal)
    else:
        try:
            host = host.encode("idna").decode("ascii").lower().removesuffix(".")
        except UnicodeError:
            raise _not_allowed() from None
        if (parts.netloc.startswith("[") or len(host) > 253 or "." not in host
                or host.endswith((".localhost", ".local", ".internal", ".lan"))
                or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                       for label in host.split("."))):
            raise _not_allowed()
        addresses = [_public_ip(address) for address in await resolve(host, port)]
        if not addresses:
            raise _fetch_failed("域名无法解析")

    authority = f"[{host}]" if ":" in host else host
    if port != default_port:
        authority = f"{authority}:{port}"
    url = urlunsplit(parts._replace(netloc=authority, path=parts.path or "/", fragment=""))
    return _Target(url, host, authority, port, addresses[0])


@asynccontextmanager
async def _open_response(target):
    import httpx

    # 每跳使用独立的直连传输，不继承代理、Cookie 或跨主机的 TLS 连接。
    try:
        request = httpx.Request(
            "GET", target.connection_url,
            headers={"Host": target.authority, "Accept": "text/html, application/xhtml+xml, text/plain",
                     "Accept-Encoding": "identity", "User-Agent": "HAiKnowBot/1.0"},
            extensions={"sni_hostname": target.host},
        )
        async with httpx.AsyncHTTPTransport(trust_env=False) as transport:
            response = await transport.handle_async_request(request)
            try:
                yield response
            finally:
                await response.aclose()
    except httpx.TimeoutException:
        raise TimeoutError from None
    except (httpx.RequestError, httpx.InvalidURL):
        raise _fetch_failed() from None


async def _read_page(target, response):
    if not 200 <= response.status_code < 300:
        raise _fetch_failed()
    content_type = response.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type not in ("", "text/html", "application/xhtml+xml", "text/plain"):
        raise _fetch_failed("网页格式不支持，请改用文件或粘贴正文")
    if response.headers.get("content-encoding", "identity").lower().strip() != "identity":
        raise _fetch_failed("网页返回了不支持的正文编码")

    raw = bytearray()
    async for block in response.aiter_raw():
        if len(raw) + len(block) > MAX_BYTES:
            raise _fetch_failed("网页正文超过读取上限")
        raw.extend(block)
    try:
        body = raw.decode(response.charset_encoding or "utf-8", errors="replace")
    except LookupError:
        body = raw.decode("utf-8", errors="replace")

    title = ""
    if content_type != "text/plain":
        from haiknow_core.aihub.reader import extract, looks_blocked

        try:
            page = extract(body)
        except (AssertionError, ValueError):
            raise _fetch_failed("网页正文无法解析") from None
        if page["truncated"]:
            raise _fetch_failed("网页正文超过读取上限")
        if len(page["text"]) < 500 and looks_blocked(body):
            raise _fetch_failed("网页需要验证，无法读取")
        title, body = page["title"], page["text"]
    if not body.strip():
        raise _fetch_failed("网页没有可导入的正文")
    return PublicPage(target.url, title, body)


class PublicURLReader:
    def __init__(self, *, resolve=_resolve, open_response=_open_response, timeout=TOTAL_TIMEOUT):
        self._resolve = resolve
        self._open_response = open_response
        self._timeout = timeout

    async def read(self, url):
        try:
            async with asyncio.timeout(self._timeout):
                target = await _target(url, self._resolve)
                for remaining in range(MAX_REDIRECTS, -1, -1):
                    async with self._open_response(target) as response:
                        if response.status_code not in REDIRECTS:
                            return await _read_page(target, response)
                        location = response.headers.get("location")
                    if not location:
                        raise _fetch_failed("网页跳转缺少目标地址")
                    _check_url_text(location)
                    try:
                        next_url = urljoin(target.url, location)
                    except ValueError:
                        raise _not_allowed() from None
                    target = await _target(next_url, self._resolve)
                    if not remaining:
                        raise _fetch_failed("网页跳转次数超过上限")
        except TimeoutError:
            raise PublicURLError(504, "URL_FETCH_TIMEOUT", "读取网页超时，请稍后重试") from None
        except socket.gaierror:
            raise _fetch_failed("域名无法解析") from None
        except OSError:
            raise _fetch_failed() from None

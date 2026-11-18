"""平台内置网页读取器：只读公网 http/https，抽正文段落并给出可回溯的摘要。

不新增依赖：拉取用 httpx，正文抽取用标准库 html.parser。
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .errors import AIError

MAX_BYTES = 2 * 1024 * 1024
MAX_CHARS = 20000
MAX_REDIRECTS = 3
USER_AGENT = 'HAiKnowBot/1.0 (+platform builtin reader)'
BLOCK_TAGS = {
    'p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'td', 'th', 'blockquote',
    'pre', 'figcaption', 'dd', 'dt', 'caption',
}
SKIP_TAGS = {'script', 'style', 'noscript', 'template', 'svg', 'iframe', 'object', 'head'}
CONTENT_TYPES = ('text/html', 'application/xhtml+xml', 'text/plain')
BLOCK_MARKERS = ('captcha', '验证码', '人机验证', '安全验证', 'cf-challenge', 'just a moment')


def _host_key(host):
    """主机名按 DNS 大小写、末尾根点及 IDNA 统一；不接受网址、端口或通配符。"""
    if not isinstance(host, str) or not host:
        raise AIError('bad_input', '授权主机必须是非空的精确主机名列表。')
    try:
        return ipaddress.ip_address(host).compressed
    except ValueError:
        pass
    try:
        host = host.encode('idna').decode('ascii').lower().removesuffix('.')
    except UnicodeError:
        raise AIError('bad_input', '授权主机名无效。') from None
    if len(host) > 253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                              for label in host.split('.')):
        raise AIError('bad_input', '授权主机名不能包含协议、端口、路径或通配符。')
    return host


def check_url(url: str, *, allowed_hosts=None) -> str:
    """只放行公网 http/https；本地名、私网/链路本地 IP 与解析到内网的域名一律拒绝。"""
    if not isinstance(url, str) or len(url) > 8192:
        raise AIError('bad_input', '网页地址无效。')
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:  # 畸形 IPv6（如 http://[::1）与非法端口
        raise AIError('bad_input', '网页地址无效。') from None
    if parts.scheme not in ('http', 'https') or not host or parts.username or parts.password:
        raise AIError('bad_input', '只允许读取公网 http/https 地址。')
    host = host.lower().rstrip('.')
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.lan')):
        raise AIError('bad_input', '不允许读取内网地址。')
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        addresses = None
    if addresses and any(not address.is_global for address in addresses):
        raise AIError('bad_input', '不允许读取内网地址。')
    if allowed_hosts is not None and _host_key(host) not in allowed_hosts:
        raise AIError('outbound_denied', '网页主机不在授权范围内。')
    if addresses is None:
        try:
            infos = socket.getaddrinfo(host, port or (443 if parts.scheme == 'https' else 80), type=socket.SOCK_STREAM)
        except socket.gaierror:
            raise AIError('bad_input', '域名无法解析，不能读取。') from None
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not addresses or any(not address.is_global for address in addresses):
        raise AIError('bad_input', '不允许读取内网地址。')
    return url


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ''
        self.blocks: list[dict] = []
        self._buffer: list[str] = []
        self._offset = 0
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag == 'title':
            self._in_title = True
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag == 'title':
            self._in_title = False
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        self._buffer.append(data)

    def close(self):
        super().close()
        self._flush()

    def _flush(self):
        text = re.sub(r'\s+', ' ', ''.join(self._buffer)).strip()
        self._buffer = []
        if text:
            self.blocks.append({'index': len(self.blocks), 'offset': self._offset, 'text': text})
            self._offset += len(text) + 1


def extract(html: str) -> dict:
    parser = _Extractor()
    parser.feed(html)
    parser.close()
    blocks = parser.blocks
    body = '\n'.join(block['text'] for block in blocks)
    truncated = len(body) > MAX_CHARS
    if truncated:
        body = body[:MAX_CHARS]
        blocks = [block for block in blocks if block['offset'] < MAX_CHARS]
    return {'title': re.sub(r'\s+', ' ', parser.title).strip(), 'blocks': blocks, 'text': body, 'truncated': truncated}


def looks_blocked(html: str) -> bool:
    sample = html[:5000].lower()
    return any(marker in sample for marker in BLOCK_MARKERS)


def failed(final_url, reason, *, status=None, title='', sha256='', reader='1'):
    return {
        'finalUrl': final_url, 'title': title, 'sha256': sha256, 'fetchedAt': time.time(),
        'status': 'failed', 'reason': reason, 'reader': {'name': 'builtin', 'version': reader},
        'blocks': [], 'text': '', 'truncated': False, 'httpStatus': status, 'mock': False,
    }


async def fetch_page(client, url, model, *, allowed_hosts=None):
    """读取一个公网页面；失败也返回结构，不用异常表达站点状态。"""
    if allowed_hosts is not None:
        if not isinstance(allowed_hosts, list) or not allowed_hosts:
            raise AIError('bad_input', '授权主机必须是非空的精确主机名列表。')
        allowed_hosts = {_host_key(host) for host in allowed_hosts}
    current = check_url(url, allowed_hosts=allowed_hosts)
    for _ in range(MAX_REDIRECTS + 1):
        request = client.build_request('GET', current, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1'})
        response = await client.send(request, stream=True)
        try:
            if response.is_redirect and response.headers.get('location'):
                current = check_url(urljoin(current, response.headers['location']), allowed_hosts=allowed_hosts)
                continue
            if response.status_code in (401, 403, 429):
                return failed(current, 'blocked', status=response.status_code, reader=model)
            if response.status_code in (404, 410):
                return failed(current, 'not_found', status=response.status_code, reader=model)
            if response.status_code >= 400:
                return failed(current, 'http_error', status=response.status_code, reader=model)
            chunks, size, overflow = [], 0, False
            async for chunk in response.aiter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_BYTES:
                    overflow = True
                    break
            raw = b''.join(chunks)[:MAX_BYTES]
            content_type = (response.headers.get('content-type') or '').split(';')[0].strip().lower()
            digest = hashlib.sha256(raw).hexdigest()
            if content_type and content_type not in CONTENT_TYPES:
                return failed(current, 'unsupported_content_type', status=response.status_code, sha256=digest, reader=model)
            charset = response.charset_encoding or 'utf-8'
            try:
                html = raw.decode(charset, errors='replace')
            except LookupError:
                html = raw.decode('utf-8', errors='replace')
            page = extract(html)
            if looks_blocked(html) and len(page['text']) < 500:
                return failed(current, 'blocked', status=response.status_code, sha256=digest, title=page['title'], reader=model)
            if not page['text']:
                return failed(current, 'no_content', status=response.status_code, sha256=digest, title=page['title'], reader=model)
            return {
                'finalUrl': current, 'title': page['title'], 'sha256': digest, 'fetchedAt': time.time(),
                'status': 'partial' if page['truncated'] or overflow else 'complete',
                'reason': 'truncated' if page['truncated'] or overflow else None,
                'reader': {'name': 'builtin', 'version': model},
                'blocks': page['blocks'], 'text': page['text'],
                'truncated': page['truncated'] or overflow, 'httpStatus': response.status_code, 'mock': False,
            }
        finally:
            await response.aclose()
    return failed(current, 'redirect_limit', reader=model)

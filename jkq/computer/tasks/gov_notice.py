"""经开区官网只读任务。确认和一步导入由运行器、知识库分别注入。"""
from __future__ import annotations

import asyncio
import base64
from fnmatch import fnmatchcase
from http.client import HTTPException, IncompleteRead
from html.parser import HTMLParser
import re
import mimetypes
import socket
from threading import Lock
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import quote, urldefrag, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SITE = "https://kfqgw.beijing.gov.cn"
COLUMN = SITE + "/zwgkkfq/tzgg/"
ROBOTS = SITE + "/robots.txt"
AGENT = "HAiKnowBot"
MAX_BYTES = 8 * 1024 * 1024
ARTICLE = re.compile(r"/zwgkkfq/tzgg/\d{6}/t\d{8}_\d+\.html")
FILES = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|zip|ofd|wps)$", re.I)


class NoticeError(Exception):
    """本步失败，主演示可继续。"""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def _get(url):
    from haiknow_core.aihub.reader import check_url, looks_blocked

    try:
        check_url(url, allowed_hosts={urlsplit(SITE).hostname})
    except RuntimeError as exc:
        dns = exc.__context__
        if isinstance(dns, socket.gaierror) and dns.errno == socket.EAI_AGAIN:
            raise dns from exc
        raise
    return _http_get(url, looks_blocked)


def _http_get(url, looks_blocked):
    request = Request(url, headers={"User-Agent": AGENT}, method="GET")
    try:
        response = build_opener(_NoRedirect).open(request, timeout=15)
    except HTTPError as error:
        with error:
            return error.code, b""
    with response:
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise NoticeError("响应超过大小上限")
        length = response.headers.get("Content-Length")
        if length is not None and (not length.isascii() or not length.isdecimal() or
                                   (length.lstrip("0") or "0") != str(len(body))):
            raise IncompleteRead(body)
        media = response.headers.get_content_type()
        path = urlsplit(url).path
        if FILES.search(path):
            expected = mimetypes.guess_type(path)[0]
            if not body or media not in {expected, "application/octet-stream"}:
                raise NoticeError("附件为空或响应类型不符")
            if body.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                raise NoticeError("附件返回网页")
        elif media == "text/html":
            sample = body.decode("utf-8", errors="replace")
            if looks_blocked(sample) and "div_zhengwen" not in sample and '<ul class="list">' not in sample:
                raise NoticeError("官网返回验证页面")
        return response.status, body


_HIDDEN = {"script", "style", "noscript", "template", "iframe", "svg"}


class _Page(HTMLParser):
    """仅从栏目列表、原文正文及其附件区取内容。"""

    def __init__(self, url, body):
        super().__init__()
        self.url = url
        self.list_depth = self.body_depth = 0
        self.hidden = 0
        self.row = None
        self.rows = []
        self.text = []
        self.files = []
        self.feed(body.decode("utf-8-sig"))
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag in _HIDDEN:
            self.hidden += 1
        if self.hidden:
            return
        if tag == "br" and self.body_depth:
            self.text.append("\n")
        attrs = dict(attrs)
        if tag == "ul" and (self.list_depth or "list" in (attrs.get("class") or "").split()):
            self.list_depth += 1
        if tag == "div" and (self.body_depth or attrs.get("id") == "div_zhengwen"):
            self.body_depth += 1
        if tag == "li" and self.list_depth:
            self.row = {"date": "", "title": "", "url": ""}
        if tag != "a" or not attrs.get("href"):
            return
        try:
            url = urldefrag(urljoin(self.url, attrs["href"])).url
        except ValueError:
            return
        if not url.startswith(SITE + "/"):
            return
        path = urlsplit(url).path
        if self.row is not None and ARTICLE.fullmatch(path):
            self.row.update(url=SITE + path, title=attrs.get("title") or "")
        if self.body_depth and FILES.search(path) and url not in self.files:
            self.files.append(url)

    def handle_endtag(self, tag):
        if self.hidden:
            if tag in _HIDDEN:
                self.hidden -= 1
            return
        if tag == "li" and self.row is not None:
            if all(self.row.values()):
                self.rows.append(self.row)
            self.row = None
        if tag == "ul" and self.list_depth:
            self.list_depth -= 1
        if tag == "div" and self.body_depth:
            self.body_depth -= 1
        if tag in ("p", "div") and self.body_depth:
            self.text.append("\n")

    def handle_data(self, data):
        if self.hidden:
            return
        if self.row is not None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data.strip()):
            self.row["date"] = data.strip()
        if self.body_depth:
            self.text.append(data)


def _normalized(path):
    # RFC 9309 §2.2.2：非 ASCII 转义，已转义的保留字符与字面字符不同。
    def canonical(match):
        char = chr(int(match[0][1:], 16))
        if char.isascii() and (char.isalnum() or char in "-._~"):
            return char
        return match[0].upper()
    return re.sub(r"%[0-9a-fA-F]{2}", canonical, quote(path, safe="/%:;@&=+$,!~*'()?#[]"))


class _Rules:
    def __init__(self, body):
        groups = []
        agents, directives = [], []
        for line in body.decode("utf-8-sig").splitlines():
            field, sep, value = line.partition("#")[0].partition(":")
            field, value = field.strip().lower(), value.strip()
            if not sep:
                continue
            if field == "user-agent":
                if directives:
                    groups.append((agents, directives))
                    agents, directives = [], []
                agents.append(value.lower())
            elif agents:
                directives.append((field, value))
        groups.append((agents, directives))
        selected = [d for a, d in groups if AGENT.lower() in a]
        if not selected:
            selected = [d for a, d in groups if "*" in a]
        self.interval = 2
        self.patterns = []
        for group in selected:
            for field, value in group:
                if field in ("allow", "disallow") and value.startswith("/"):
                    path = _normalized(value.removesuffix("$"))
                    pattern = path.replace("[", "[[]").replace("?", "[?]")
                    if not value.endswith("$"):
                        pattern += "*"
                    self.patterns.append((pattern, len(path), field == "allow"))
                elif field == "crawl-delay" and re.fullmatch(r"[0-9]{1,9}", value):
                    self.interval = max(self.interval, int(value))
                elif field == "request-rate" and re.fullmatch(r"[1-9][0-9]{0,8}/[0-9]{1,9}", value):
                    count, seconds = map(int, value.split("/"))
                    self.interval = max(self.interval, seconds / count)

    def allows(self, url):
        target = _normalized(url[len(SITE):])
        matches = ((length, allow) for pattern, length, allow in self.patterns
                   if fnmatchcase(target, pattern))
        return max(matches, default=(0, True))[1]


class _SiteRequests:
    """当前单进程运行器的所有席位共用一个官网出口。"""
    def __init__(self, clock=monotonic, wait=sleep):
        self.lock = Lock()
        self.clock = clock
        self.wait = wait
        self.next_at = 0
        self.interval = 2

    def fetch(self, get, entry):
        with self.lock:
            delay = self.next_at - self.clock()
            if delay > 0:
                self.wait(delay)
            entry["at"] = self.clock()
            try:
                status, body = get(entry["url"])
                if entry["url"] == ROBOTS and status in (200, 404, 410):
                    rules = _Rules(body if status == 200 else b"")
                    self.interval = rules.interval
                    body = rules
                return status, body
            finally:
                self.next_at = self.clock() + self.interval


_SITE_REQUESTS = _SiteRequests()


async def run_notice(confirm, import_items, *, limit=3, get=_get, requests=_SITE_REQUESTS):
    """confirm(items) 和 import_items(§3.6 payload) 均为异步回调。get 是单次同步 GET。"""
    if type(limit) is not int or limit < 1:
        raise ValueError("通知数量必须为正整数")
    log = []
    rules = None

    async def read(url):
        if url != ROBOTS and not rules.allows(url):
            raise NoticeError("官网规则禁止读取")
        for attempt in range(1, 5):
            entry = {"method": "GET", "url": url, "attempt": attempt}
            log.append(entry)
            try:
                status, body = await asyncio.to_thread(requests.fetch, get, entry)
                entry["result"] = status
            except (OSError, HTTPException) as exc:
                entry["result"] = type(exc).__name__
            except (NoticeError, RuntimeError, UnicodeError) as exc:
                entry["result"] = type(exc).__name__
                if isinstance(exc, NoticeError):
                    raise
                raise NoticeError("官网读取受限") from exc
            else:
                if url == ROBOTS and status in (404, 410):
                    return body
                if status == 200:
                    return body
                if status < 500:
                    break
        raise NoticeError("官网读取失败")

    try:
        rules = await read(ROBOTS)
        listing = _Page(COLUMN, await read(COLUMN))
        items = []
        seen = set()
        for row in sorted(listing.rows, key=lambda row: row["date"], reverse=True):
            url = row["url"]
            if url in seen:
                continue
            seen.add(url)
            article = _Page(url, await read(url))
            text = "".join(article.text).strip()
            if not text and not article.files:
                raise NoticeError("通知正文为空")
            source = {"url": url, "date": row["date"]}
            if text:
                items.append({"name": row["title"], "ext": "txt", "text": text, "source": source})
            for link in article.files:
                data = await read(link)
                filename = urlsplit(link).path.rsplit("/", 1)[1]
                items.append({"name": filename, "ext": filename.rsplit(".", 1)[1].lower(),
                              "contentBase64": base64.b64encode(data).decode("ascii"),
                              "size": len(data), "source": source, "attachmentUrl": link})
            if len(seen) == limit:
                break
        if not items:
            raise NoticeError("栏目中没有可读通知")
    except (NoticeError, UnicodeError) as exc:
        return {"status": "failed", "skipped": True, "error": str(exc), "log": log}
    if not await confirm(items):
        return {"status": "stopped", "skipped": True, "log": log}
    try:
        result = await import_items({"items": items, "from": "computer.notice"})
    except Exception:
        return {"status": "failed", "skipped": True, "error": "知识库导入调用失败", "log": log}
    docs = result.get("docs") if isinstance(result, dict) else None
    skips = result.get("skipped") if isinstance(result, dict) else None
    if not isinstance(docs, list) or not isinstance(skips, list):
        error = "知识库导入结果无效"
    elif len(docs) + len(skips) != len(items) or any(
        not isinstance(item, dict) or item.get("reason") != "已在库中" for item in skips
    ):
        error = "部分资料导入失败" if docs else "资料导入失败"
    else:
        error = None
    if error:
        return {"status": "failed", "skipped": True, "error": error, "result": result, "log": log}
    return {"status": "done", "result": result, "log": log}

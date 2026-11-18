"""经开区官网只读任务。确认和一步导入由运行器、知识库分别注入。"""
from __future__ import annotations

import asyncio
import base64
from html.parser import HTMLParser
import re
from time import monotonic
from urllib.error import HTTPError
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

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

    check_url(url, allowed_hosts={urlsplit(SITE).hostname})
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
        if response.headers.get_content_type() == "text/html":
            sample = body.decode("utf-8", errors="replace")
            if looks_blocked(sample) and "div_zhengwen" not in sample and '<ul class="list">' not in sample:
                raise NoticeError("官网返回验证页面")
        return response.status, body


class _Page(HTMLParser):
    """仅从栏目列表、原文正文及其附件区取内容。"""

    def __init__(self, url, body):
        super().__init__()
        self.url = url
        self.list_depth = self.body_depth = 0
        self.row = None
        self.rows = []
        self.text = []
        self.files = []
        self.feed(body.decode("utf-8-sig"))
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "ul" and (self.list_depth or "list" in attrs.get("class", "").split()):
            self.list_depth += 1
        if tag == "div" and (self.body_depth or attrs.get("id") == "div_zhengwen"):
            self.body_depth += 1
        if tag == "li" and self.list_depth:
            self.row = {"date": "", "title": "", "url": ""}
        if tag != "a" or not attrs.get("href"):
            return
        url = urldefrag(urljoin(self.url, attrs["href"])).url
        if not url.startswith(SITE + "/"):
            return
        path = urlsplit(url).path
        if self.row is not None and ARTICLE.fullmatch(path):
            self.row.update(url=SITE + path, title=attrs.get("title") or "")
        if self.body_depth and FILES.search(path) and url not in self.files:
            self.files.append(url)

    def handle_endtag(self, tag):
        if tag == "li" and self.row is not None:
            if all(self.row.values()):
                self.rows.append(self.row)
            self.row = None
        if tag == "ul" and self.list_depth:
            self.list_depth -= 1
        if tag == "div" and self.body_depth:
            self.body_depth -= 1
        if tag in ("p", "br", "div") and self.body_depth:
            self.text.append("\n")

    def handle_data(self, data):
        if self.row is not None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data.strip()):
            self.row["date"] = data.strip()
        if self.body_depth:
            self.text.append(data)


async def run_notice(confirm, import_items, *, limit=3, get=_get, clock=monotonic, sleep=asyncio.sleep):
    """confirm(items) 和 import_items(§3.6 payload) 均为异步回调。get 是单次同步 GET。"""
    if type(limit) is not int or limit < 1:
        raise ValueError("通知数量必须为正整数")
    log = []
    rules = RobotFileParser()
    interval = 2
    last = None

    async def read(url):
        nonlocal last
        if url != ROBOTS and not rules.can_fetch(AGENT, url):
            raise NoticeError("官网规则禁止读取")
        for attempt in range(1, 5):
            if last is not None:
                await sleep(max(0, last + interval - clock()))
            last = clock()
            entry = {"method": "GET", "url": url, "attempt": attempt, "at": last}
            log.append(entry)
            try:
                status, body = await asyncio.to_thread(get, url)
                entry["result"] = status
            except (OSError, TimeoutError) as exc:
                entry["result"] = type(exc).__name__
            except (NoticeError, RuntimeError) as exc:
                entry["result"] = type(exc).__name__
                raise NoticeError("官网读取受限") from exc
            else:
                if url == ROBOTS and status in (404, 410):
                    return b""
                if status == 200:
                    return body
                if status < 500:
                    break
        raise NoticeError("官网读取失败")

    try:
        rules.parse((await read(ROBOTS)).decode("utf-8-sig").splitlines())
        interval = max(interval, rules.crawl_delay(AGENT) or 0)
        rate = rules.request_rate(AGENT)
        if rate:
            interval = max(interval, rate.seconds / max(1, rate.requests))
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
    result = await import_items({"items": items, "from": "computer.notice"})
    return {"status": "done", "result": result, "log": log}

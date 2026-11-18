import asyncio
from unittest.mock import AsyncMock

import pytest

from jkq.computer.tasks.gov_notice import COLUMN, ROBOTS, _SiteRequests, run_notice


def url(n):
    return COLUMN + f"202611/t20261118_{n}.html"


@pytest.fixture
def site():
    pages = {ROBOTS: (404, b"")}
    rows = []
    for n in (1, 5, 5, 4, 3, 2):
        rows.append(f'<li><a href="{url(n)}" title="演示{n}"></a><span>2026-11-0{n}</span></li>')
        pages[url(n)] = (200, f'<div id="div_zhengwen"><p>正文{n}</p></div>'.encode())
    rows.append('<li><a href="https://example.org/" title="外站"></a><span>2026-12-01</span></li>')
    pages[COLUMN] = (200, ('<form method="POST"></form><ul class="list">' + ''.join(rows) + '</ul>').encode())
    return pages


class Run:
    def __init__(self, site):
        self.site = site
        self.now = 0
        self.requests = _SiteRequests(lambda: self.now, self.sleep)
        self.calls = []
        self.confirm = AsyncMock(return_value=True)
        self.saved = {}

    def get(self, address):
        self.calls.append((self.now, address))
        response = self.site[address]
        if isinstance(response, list):
            response = response.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def sleep(self, seconds):
        self.now += seconds

    async def import_items(self, payload):
        docs, skipped = [], []
        for item in payload["items"]:
            key = (item["source"]["url"], item["name"])
            if key in self.saved:
                skipped.append({"name": item["name"], "reason": "已在库中"})
            else:
                self.saved[key] = item
                docs.append(key)
        return {"docs": docs, "skipped": skipped}

    def execute(self, **kwargs):
        return asyncio.run(run_notice(self.confirm, self.import_items, get=self.get,
                                      requests=self.requests, **kwargs))


def test_latest_sources_and_pipeline_dedup(site):
    run = Run(site)
    first = run.execute()
    assert first["status"] == "done"
    assert [item["text"] for item in run.saved.values()] == ["正文5", "正文4", "正文3"]
    assert [key[0] for key in run.saved] == [url(5), url(4), url(3)]
    assert run.calls == list(zip(range(0, 10, 2), [ROBOTS, COLUMN, url(5), url(4), url(3)]))
    assert [(e["method"], e["result"]) for e in first["log"]] == [("GET", 404)] + [("GET", 200)] * 4
    repeat = run.execute()["result"]
    assert repeat["docs"] == [] and len(repeat["skipped"]) == 3


def test_attachment_and_transient_failure(site):
    file = COLUMN + "202611/demo.pdf"
    site[url(5)] = (200, b'<div id="div_zhengwen"><a href="demo.pdf">PDF</a></div>')
    site[file] = [(503, b""), (200, b"abc")]
    run = Run(site)
    result = run.execute(limit=1)
    assert [e["result"] for e in result["log"]][-2:] == [503, 200]
    attachment = run.saved[url(5), "demo.pdf"]
    assert attachment["attachmentUrl"] == file and attachment["contentBase64"] == "YWJj"


@pytest.mark.parametrize("failure", [OSError(), (503, b"")])
def test_unavailable_skips_after_three_retries(site, failure):
    site[COLUMN] = failure
    run = Run(site)
    result = run.execute()
    assert result["status"] == "failed" and result["skipped"]
    assert run.calls[1:] == [(n, COLUMN) for n in (2, 4, 6, 8)]
    assert len(result["log"]) == 5
    run.confirm.assert_not_awaited()
    assert not run.saved


def test_site_rules_and_form_only_page(site):
    site[ROBOTS] = (200, b"User-agent: *\nCrawl-delay: 4\nDisallow: /zwgkkfq/tzgg/202611/")
    run = Run(site)
    assert run.execute()["status"] == "failed"
    assert run.calls == [(0, ROBOTS), (4, COLUMN)]
    site[ROBOTS] = (404, b"")
    site[COLUMN] = (200, b'<form action="/submit"></form>')
    assert run.execute()["skipped"]
    assert not run.saved


def test_refusal_and_invalid_limit(site):
    run = Run(site)
    run.confirm.return_value = False
    assert run.execute()["status"] == "stopped" and not run.saved
    with pytest.raises(ValueError):
        run.execute(limit=0)


@pytest.mark.parametrize("status", [302, 403, 429])
def test_redirect_or_block_ends_without_import(site, status):
    site[url(4)] = (status, b"")
    run = Run(site)
    result = run.execute()
    assert result["status"] == "failed" and result["skipped"]
    assert result["log"][-1]["result"] == status
    assert len(run.calls) == 4 and not run.saved


def test_short_column_imports_available_notices(site):
    site[COLUMN] = (200, (f'<ul class="list"><li><a title="演示" href="{url(2)}"></a>'
                          '<span>2026-11-02</span></li></ul>').encode())
    run = Run(site)
    assert run.execute()["status"] == "done"
    assert list(run.saved) == [(url(2), "演示")]


@pytest.mark.parametrize(("rule", "forbidden"), [
    ("Disallow: /zwgkkfq/tzgg/", COLUMN),
    ("Disallow: /*.pdf$", COLUMN + "202611/test.pdf"),
])
def test_robots_denies_before_get(site, rule, forbidden):
    site[ROBOTS] = (200, f"User-agent: *\nAllow: /\n{rule}".encode())
    site[url(5)] = (200, b'<div id="div_zhengwen"><a href="test.pdf">PDF</a></div>')
    run = Run(site)
    assert run.execute()["error"] == "官网规则禁止读取"
    assert forbidden not in [address for _, address in run.calls]
    run.confirm.assert_not_awaited()


def test_concurrent_runs_share_default_site_spacing(site):
    from time import monotonic

    times = []

    def unavailable(address):
        assert address == ROBOTS
        times.append(monotonic())
        return 403, b""

    async def concurrent():
        return await asyncio.gather(*(run_notice(None, None, get=unavailable) for _ in range(2)))

    assert all(result["skipped"] for result in asyncio.run(concurrent()))
    assert len(times) == 2 and times[1] - times[0] >= 2


@pytest.mark.parametrize("valid_row", [True, False])
def test_malformed_rows_and_article_markup(site, valid_row):
    malformed = b'<ul class></ul><ul class="list"><li><a href="http://[">bad</a></li></ul>'
    site[COLUMN] = (200, malformed + (site[COLUMN][1] if valid_row else b""))
    site[url(5)] = (200, b'<div id="div_zhengwen">One<br>Two<script>bad</script><style>bad</style></div>')
    run = Run(site)
    result = run.execute(limit=1)
    if valid_row:
        assert result["status"] == "done"
        assert run.saved[url(5), "演示5"]["text"] == "One\nTwo"
    else:
        assert result["status"] == "failed" and result["skipped"]
        assert result["log"][-1]["url"] == COLUMN


@pytest.mark.parametrize(("docs", "reasons", "error"), [
    ([], ["已在库中"] * 3, None),
    ([], ["解析失败"] * 3, "资料导入失败"),
    (["doc"], ["解析失败", "已在库中"], "部分资料导入失败"),
    ([], [], "资料导入失败"),
])
def test_import_outcomes(site, docs, reasons, error):
    run = Run(site)
    reply = {"docs": docs, "chunks": len(docs), "skipped": [{"reason": r} for r in reasons]}
    run.import_items = AsyncMock(return_value=reply)
    result = run.execute()
    assert result["status"] == ("failed" if error else "done")
    assert result.get("error") == error
    assert result["result"] == reply and len(result["log"]) == 5


@pytest.fixture
def transport(monkeypatch):
    import io
    from http.client import HTTPResponse
    from unittest.mock import Mock
    from jkq.computer.tasks import gov_notice

    opener = Mock()
    monkeypatch.setattr(gov_notice, "build_opener", lambda *args: opener)

    def respond(request, timeout):
        assert request.get_method() == "GET"
        raw = replies[request.full_url]
        sock = Mock()
        sock.makefile.return_value = io.BytesIO(raw)
        response = HTTPResponse(sock)
        response.begin()
        return response

    replies = {}
    opener.open.side_effect = respond
    return replies, lambda address: gov_notice._http_get(address, lambda text: False), opener


@pytest.mark.parametrize(("media", "body", "length", "attempts", "status"), [
    ("application/pdf", b"%PDF-1.4", 8, 1, "done"),
    ("application/pdf", b"%PDF-1.4", 60, 4, "failed"),
    ("application/pdf", b"", 0, 1, "failed"),
    ("text/html", b"<html>notice", 12, 1, "failed"),
    ("application/octet-stream", b"<html>notice", 12, 1, "failed"),
])
def test_real_response_attachment(site, transport, media, body, length, attempts, status):
    replies, get, _ = transport
    file = COLUMN + "202611/test.pdf"
    site[url(5)] = (200, b'<div id="div_zhengwen"><a href="test.pdf">PDF</a></div>')
    for address, (code, data) in site.items():
        replies[address] = f"HTTP/1.1 {code} Response\r\nContent-Length: {len(data)}\r\n\r\n".encode() + data
    replies[file] = f"HTTP/1.1 200 OK\r\nContent-Type: {media}\r\nContent-Length: {length}\r\n\r\n".encode() + body
    run = Run(site)
    run.get = get
    result = run.execute(limit=1)
    assert result["status"] == status
    assert bool(run.saved) == (status == "done")
    logs = [e for e in result["log"] if e["url"] == file]
    assert [e["at"] for e in logs] == list(range(6, 6 + attempts * 2, 2))
    if attempts == 4:
        assert all(e["result"] == "IncompleteRead" for e in logs)


@pytest.mark.parametrize(("temporary", "attempts"), [(True, 4), (False, 1)])
def test_preflight_dns(site, transport, monkeypatch, temporary, attempts):
    import socket

    pytest.importorskip("fastapi")
    from jkq.computer.tasks.gov_notice import _get

    _, _, opener = transport

    def resolve(*a, **kw):
        if temporary:
            raise socket.gaierror(socket.EAI_AGAIN, "temporary failure")
        return [(0, 0, 0, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    run = Run(site)
    run.get = _get
    result = run.execute()
    assert result["status"] == "failed" and result["skipped"]
    assert len(result["log"]) == attempts
    assert [e["at"] for e in result["log"]] == list(range(0, attempts * 2, 2))
    opener.open.assert_not_called()


def _notice_runs(site):
    from jkq.computer.runs import Runs

    class Unused:
        url = "http://127.0.0.1:1/"

        async def __call__(self, run):
            raise AssertionError("通知任务不应启动模拟站运行器")

    pages = site

    def get(address):
        response = pages[address]
        if isinstance(response, list):
            response = response.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    now = 0

    def clock():
        return now

    def wait(seconds):
        nonlocal now
        now += seconds

    return Runs(Unused.url, Unused(), lambda *args: None, fetch=get,
                site_requests=_SiteRequests(clock, wait))


async def _wait_status(run, status, timeout=2):
    import asyncio
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if run.data["status"] == status:
            return run.snapshot()
        if run.job.done() and run.data["status"] != status:
            raise AssertionError(f"任务已结束为 {run.data['status']}: {run.data.get('error')}")
        await asyncio.sleep(0.01)
    raise AssertionError(f"等待 {status} 超时，当前为 {run.data['status']}")


def test_runner_waits_for_import_confirm(site):
    import asyncio
    from jkq.computer.runs import ComputerError

    async def scenario():
        runs = _notice_runs(site)
        run = runs.start("owner", "王敏", {"task": "notice", "ent": None, "from": "api"}, None, lambda: True)
        item = await _wait_status(run, "waiting")
        assert item["pending"]["kind"] == "import"
        assert item["notice"]["count"] == 3
        assert item["task"] == "notice"
        with pytest.raises(ComputerError, match="确认类型"):
            run.confirm("approve", "submit")
        run.confirm("approve", "import")
        await run.job
        done = run.snapshot()
        assert done["status"] == "done"
        assert len(done["result"]["docs"]) == 3
        assert all(entry["method"] == "GET" for entry in done["requests"])
        # 第二次运行走桩去重
        again = runs.start("owner", "王敏", {"task": "notice", "ent": None, "from": "api"}, "k2", lambda: True)
        await _wait_status(again, "waiting")
        again.confirm("approve", "import")
        await again.job
        assert again.snapshot()["result"]["docs"] == []
        assert len(again.snapshot()["result"]["skipped"]) == 3
        assert {item["reason"] for item in again.snapshot()["result"]["skipped"]} == {"已在库中"}
        await runs.close()

    asyncio.run(scenario())


def test_runner_decline_stops_without_import(site):
    import asyncio

    async def scenario():
        runs = _notice_runs(site)
        run = runs.start("owner", "王敏", {"task": "notice", "ent": None, "from": "api"}, None, lambda: True)
        await _wait_status(run, "waiting")
        run.confirm("decline", "import")
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(run.job, 2)
        item = run.snapshot()
        assert item["status"] == "stopped"
        assert item.get("result") is None
        await runs.close()

    asyncio.run(scenario())


def test_runner_marks_unreachable_as_failed_and_skipped(site):
    import asyncio

    async def scenario():
        site[ROBOTS] = OSError("官网不可达")
        runs = _notice_runs(site)
        run = runs.start("owner", "王敏", {"task": "notice", "ent": None, "from": "api"}, None, lambda: True)
        await asyncio.wait_for(run.job, 2)
        item = run.snapshot()
        assert item["status"] == "failed" and item.get("skipped") is True
        assert item["error"]["details"]["skipped"] is True
        assert item.get("result") is None
        await runs.close()

    asyncio.run(scenario())

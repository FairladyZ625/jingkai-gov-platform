import asyncio
from unittest.mock import AsyncMock

import pytest

from jkq.computer.tasks.gov_notice import COLUMN, ROBOTS, run_notice


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

    async def sleep(self, seconds):
        self.now += seconds

    async def import_items(self, payload):
        docs, skipped = [], []
        for item in payload["items"]:
            key = (item["source"]["url"], item["name"])
            if key in self.saved:
                skipped.append(key)
            else:
                self.saved[key] = item
                docs.append(key)
        return {"docs": docs, "skipped": skipped}

    def execute(self, **kwargs):
        return asyncio.run(run_notice(self.confirm, self.import_items, get=self.get,
                                      clock=lambda: self.now, sleep=self.sleep, **kwargs))


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

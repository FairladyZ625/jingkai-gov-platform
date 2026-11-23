"""经办人和领导使用同一个合成录音入口，历史副本不删除。"""

from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from tests.demo_http.password_ui import login

BASE = "/api/apps/meeting/meetings"
SAMPLE = {"source": "demo", "sampleId": "park-service-v1"}
TITLE = "【合成演示】园区服务清单核对"
LEGACY = "【示例】文化企业座谈会录音_1117"


def sign_in(client, server, username):
    response = client.post("/api/v1/auth/login", json={"username": username, "password": server.password})
    assert response.is_success


@pytest.mark.parametrize("server", [()], indirect=True)
def test_existing_clean_copies_collapse_without_removing_records(server):
    with httpx.Client(base_url=server.url) as client:
        sign_in(client, server, "wangmin")
        copies = []
        for _ in range(2):
            response = client.post(BASE, data={"source": "demo", "title": LEGACY})
            assert response.status_code == 201
            copies.append(response.json()["item"]["id"])
        assert len(set(copies)) == 2
        main = client.get(BASE).json()
        examples = [item for item in main["items"] if item.get("sampleId") == SAMPLE["sampleId"]]
        assert len(examples) == 1 and examples[0]["title"] == TITLE
        assert examples[0]["id"] in copies
        for key in copies:
            assert client.get(f"{BASE}/{key}").is_success

        def create(user):
            with httpx.Client(base_url=server.url) as identity:
                sign_in(identity, server, user)
                response = identity.post(BASE, data=SAMPLE)
                assert response.is_success
                return response.json()["item"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, ("wangmin", "liyang")))
        assert [row["id"] for row in results] == [examples[0]["id"]] * 2
        assert results[0]["duration"] == "00:11" and results[0]["type"] == "专题推进会"
        assert client.get(BASE).json()["total"] == main["total"]


@pytest.mark.parametrize("server", [()], indirect=True)
def test_http_home_suggestion_opens_the_matching_sample(server):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as engine, engine.chromium.launch() as browser:
        page = browser.new_page(base_url=server.url, viewport={"width": 1440, "height": 900})
        page.goto("/")
        login(page, "liyang", server.password)
        action = page.get_by_role("button", name="把园区服务清单的合成录音整理成纪要")
        action.click(timeout=5000)
        paper = page.locator('[data-op="meeting.minutes"]')
        playwright.expect(paper.locator('h3')).to_have_text(TITLE + "纪要", timeout=30000)
        playwright.expect(paper).to_contain_text("核对园区服务清单")
        assert page.request.get("/api/apps/meeting/transcription/demo").ok


@pytest.mark.parametrize("server", [("enterprise",)], indirect=True)
def test_concurrent_first_open_creates_only_one_canonical_archive(server):
    def create(username):
        with httpx.Client(base_url=server.url) as client:
            sign_in(client, server, username)
            result = client.post(BASE, data=SAMPLE)
            assert result.is_success
            return result.status_code, result.json()["item"]["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        (left, right) = list(pool.map(create, ("wangmin", "liyang")))
    assert {left[0], right[0]} == {200, 201} and left[1] == right[1]
    with httpx.Client(base_url=server.url) as client:
        sign_in(client, server, "wangmin")
        original = {"source": "demo", "title": "单独保留的排练会议"}
        ids = [client.post(BASE, data=original).json()["item"]["id"] for _ in range(2)]
        assert len(set(ids)) == 2
        visible = {row["id"] for row in client.get(BASE).json()["items"]}
        assert set(ids + [left[1]]).issubset(visible)

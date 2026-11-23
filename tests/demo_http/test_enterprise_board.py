"""用本地 HTTP 演示实例验证企业诉求布局和空台账，不预填企业。"""

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def empty_enterprise_seed():
    from jkq.demo import seed

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(seed, "demo_rows", lambda root: [])
        yield


@pytest.fixture
def page(server):
    with sync_playwright() as engine, engine.chromium.launch() as browser:
        page = browser.new_page(base_url=server.url, viewport={"width": 1440, "height": 900})
        page.goto("/")
        assert page.evaluate("JK_CONFIG.api.mode") == "http"
        page.locator('[data-op="login.user"]').fill("admin")
        page.locator('[data-op="login.pass"]').fill(server.password)
        page.locator('[data-op="login.go"]').click()
        page.locator('.quick-apps [data-app="enterprise"]').click()
        yield page


@pytest.mark.parametrize("server", [()], indirect=True)
def test_board_keeps_all_statuses_inside_visible_panel(page):
    page.get_by_role("button", name="诉求看板", exact=False).click()
    headings = page.locator(".ent-board .ent-colh")
    expect(headings).to_have_text(["待分派0", "办理中0", "待补材料0", "已办结0"])
    for width, columns_in_first_row in ((1440, 4), (1280, 2)):
        page.set_viewport_size({"width": width, "height": 900})
        board = page.locator(".ent-board")
        assert board.evaluate("board => board.scrollWidth === board.clientWidth")
        bounds = board.bounding_box()
        boxes = [cell.bounding_box() for cell in headings.all()]
        assert sum(abs(box["y"] - boxes[0]["y"]) < 1 for box in boxes) == columns_in_first_row
        assert all(box["x"] + box["width"] <= bounds["x"] + bounds["width"] + 1 for box in boxes)


@pytest.mark.parametrize("server", [()], indirect=True)
def test_empty_ledger_can_create_and_filter_can_reset(page):
    reply = page.request.get("/api/apps/enterprise/companies")
    assert reply.ok and reply.json()["total"] == 0
    page.get_by_role("button", name="台账", exact=True).click()
    expect(page.get_by_text("还没有企业", exact=True)).to_be_visible(timeout=3000)
    expect(page.get_by_role("button", name="清空筛选")).to_have_count(0)
    expect(page.get_by_role("button", name="导入", exact=True)).to_be_enabled()
    page.get_by_role("button", name="新建企业", exact=True).click()
    title = page.get_by_text("新建企业档案", exact=True)
    expect(title).to_be_visible()
    page.locator(".modal #nn").fill("台账验收示例企业")
    with page.expect_response(lambda res: res.request.method == "POST" and res.url.endswith("/companies")) as created:
        page.get_by_role("button", name="创建", exact=True).click()
    assert created.value.ok
    expect(title).to_be_hidden()
    page.get_by_role("button", name="台账", exact=True).click()
    query = page.locator('[data-op="enterprise.list-q"]')
    query.fill("不会命中的检索条件")
    expect(page.get_by_text("没有符合条件的企业", exact=True)).to_be_visible()
    page.get_by_role("button", name="清空筛选").click()
    expect(query).to_have_value("")
    expect(page.locator(".ent-tbl").get_by_text("台账验收示例企业")).to_be_visible()

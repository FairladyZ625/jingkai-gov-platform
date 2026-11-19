from tests.demo_http.password_ui import login, wait_segment
"""专用 CI 验收入口，缺浏览器或缺上游均失败。"""

import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.parametrize("server", [("meeting",)], indirect=True)
def test_one_module_uses_mock(server):
    with sync_playwright() as engine, engine.chromium.launch() as browser:
        page = browser.new_page()
        page.goto(server.url)
        response = page.request.post(server.url + "/api/v1/auth/login",
                                     data={"username": "wangmin", "password": server.password})
        assert response.ok
        assert page.evaluate("JK_CONFIG.api.mode") == "http"
        # 让真实适配器把登录角色同步到浏览器 mock，再仅观察这两次业务调用。
        page.evaluate("JKHttp.get('/api/v1/auth/session')")
        paths = []
        page.on("request", lambda req: paths.append(urlsplit(req.url).path))
        observed = page.evaluate("""async () => {
            const mock = [];
            const original = JKAPI.request.bind(JKAPI);
            JKAPI.request = (...args) => { mock.push(args[1]); return original(...args); };
            const meeting = await JKApi.meeting.list();
            const profile = await JKApi.me.get();
            return {mock, meetings: Array.isArray(meeting.items), username: profile.user.username};
        }""")
        assert observed == {"mock": ["/api/apps/meeting/meetings"], "meetings": True, "username": "wangmin"}
        assert "/api/v1/me" in paths and "/api/apps/meeting/meetings" not in paths


@pytest.mark.parametrize("server", [()], indirect=True)
def test_browser_walks_twelve_segments(server):
    with sync_playwright() as engine, engine.chromium.launch() as browser:
        page = browser.new_page()
        page.set_default_timeout(15000)
        page.goto(server.url)
        assert page.evaluate("JK_CONFIG.api.mode") == "http"
        assert not page.evaluate("Object.values(JK_CONFIG.api.modules || {}).includes('mock')")
        page.evaluate("""() => {
            window.demoMockCalls = [];
            JKAPI.request = (method, path) => {
                demoMockCalls.push(path);
                throw Error('HTTP 验收发现 mock 请求');
            };
        }""")
        login(page, "wangmin", server.password)
        page.locator("#btn-demo").wait_for()
        assert page.evaluate("JKShell.S.me.username") == "wangmin"
        titles = page.evaluate("JK_DEMO_SCRIPT.map(s => s.title)")
        required = [
            ("开场", None),
            ("政策兑现", r"/api/apps/policy/match$"),
            ("企业走访", r"/api/apps/enterprise/proposals/[^/]+/decision$"),
            ("会议纪要", r"/api/apps/meeting/meetings/[^/]+/todos/commit$"),
            ("公文协作", r"/api/apps/document/drafts/[^/]+/submit$"),
            ("知识库", r"/api/v1/kb/ask$"),
            ("技能中心", r"/api/v1/skills/[^/]+/(share|publish)$"),
            ("电脑操作", r"/api/apps/computer/runs/[^/]+/confirm$"),
            ("审签", r"/api/v1/reviews/[^/]+/decisions$"),
            ("外部协作者", r"/api/apps/enterprise/companies/[^/]+$"),
            ("管理后台", r"/api/v1/audit$"),
            ("浅色主题", None),
        ]
        assert titles == [title for title, _ in required]
        # 始终调用真实 fetch。只保留业务回执的关联 ID，不保存会话或请求正文。
        page.evaluate("""() => {
            window.demoNetwork = [];
            window.demoThemes = [];
            const fetch = window.fetch.bind(window);
            window.fetch = async (...args) => {
                const segment = JKDemo.state.i;
                const reply = await fetch(...args);
                const path = new URL(reply.url).pathname;
                if (path.startsWith('/api/') && reply.ok) {
                    const json = await reply.clone().json().catch(() => ({}));
                    demoNetwork.push({segment, path, reviewId: json.review?.id,
                        draftId: json.review?.ref, approved: json.item?.decision?.decision});
                }
                return reply;
            };
            const observer = new MutationObserver(() => {
                if (JKDemo.state.on && JKDemo.state.i === 11)
                    demoThemes.push(document.documentElement.dataset.theme);
            });
            observer.observe(document.documentElement, {attributes:true, attributeFilter:['data-theme']});
        }""")
        page.locator("#btn-demo").click()
        for index, (title, pattern) in enumerate(required):
            wait_segment(page, index, server.password)
            assert page.evaluate("JKDemo.state.i") > index, f"{title} 提前退出"
            if pattern:
                paths = page.evaluate("i => demoNetwork.filter(r => r.segment === i).map(r => r.path)", index)
                assert any(re.fullmatch(pattern, path) for path in paths), f"{title} 缺少 HTTP 业务回执"
        assert page.evaluate("JKDemo.state.i") == 12 and not page.evaluate("demoMockCalls")
        assert set(page.evaluate("demoThemes")) >= {"light", "dark"}
        assert page.evaluate("JKShell.S.me.username") == "wangmin"
        submitted, decided = page.evaluate("""() => [
            demoNetwork.find(r => r.segment === 4 && r.reviewId && r.draftId),
            demoNetwork.find(r => r.segment === 8 && r.approved === 'approve')]""")
        assert submitted and decided and decided["path"] == f"/api/v1/reviews/{submitted['reviewId']}/decisions"
        draft = page.request.get(server.url + "/api/apps/document/drafts/" + submitted["draftId"])
        assert draft.ok and draft.json()["item"]["status"] == "已定稿"

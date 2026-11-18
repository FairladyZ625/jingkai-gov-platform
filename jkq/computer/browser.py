"""执行固定的本地模拟申报，截屏前遮盖页面上的敏感控件。"""

import re
from urllib.parse import urlsplit

from .runs import ComputerError, Run, now


MASK = (
    'input[type="password"], [data-sensitive], [autocomplete="one-time-code"], '
    '[data-op="captcha"], #captcha .code, [aria-label="演练码"]'
)
PROTECTED = {"verify": "otp", "sign": "sign", "pay": "pay", "submit": "submit"}


def mock_url(value: str) -> str:
    """只接受部署指定的 IPv4 回环站点与精确端口。"""
    try:
        parts = urlsplit(value)
        port = parts.port
        if (port and parts.scheme == "http" and parts.netloc == f"127.0.0.1:{port}"
                and value in (f"http://127.0.0.1:{port}", f"http://127.0.0.1:{port}/")):
            return f"http://127.0.0.1:{port}/"
    except ValueError:
        pass
    raise ComputerError("OUTBOUND_DENIED", "模拟站地址必须是带端口的本地回环 HTTP 根地址")


class BrowserSession:
    def __init__(self, page, run: Run, url: str):
        self.page = page
        self.run = run
        self.url = url
        self.host = urlsplit(url).netloc
        self.denial: ComputerError | None = None
        self.approved: str | None = None

    def check(self) -> None:
        if self.denial is not None:
            raise self.denial
        self.run.check()

    async def block(self, abort) -> None:
        self.denial = ComputerError("OUTBOUND_DENIED", "已拦截白名单外或重定向的网页请求")
        try:
            await abort()
        finally:
            self.run.reject_pending(self.denial)

    async def route(self, route) -> None:
        parts = urlsplit(route.request.url)
        if (self.denial is not None or parts.scheme != "http" or parts.netloc != self.host
                or route.request.method != "GET"):
            await self.block(route.abort)
            return
        response = await route.fetch(max_redirects=0, timeout=10_000)
        try:
            if 300 <= response.status < 400 or response.headers.get("refresh"):
                await self.block(route.abort)
                return
            await route.fulfill(response=response)
        finally:
            await response.dispose()

    async def block_websocket(self, socket) -> None:
        await self.block(socket.close)

    def op(self, name: str):
        return self.page.locator(f'[data-op="{name}"]')

    async def capture(self, title: str, kind: str | None = None) -> None:
        self.check()
        png = await self.page.screenshot(mask=[self.page.locator(MASK)], mask_color="#000000",
                                         animations="disabled", timeout=10_000)
        self.check()
        await self.run.capture(title, png, kind=kind)
        self.check()
        self.approved = kind

    async def click(self, name: str) -> None:
        self.check()
        if name in PROTECTED:
            if self.approved != PROTECTED[name]:
                raise ComputerError("LOCKED", "敏感操作必须先通过人工确认")
            self.approved = None
        await self.op(name).click()

    async def apply(self) -> dict:
        await self.page.goto(self.url, wait_until="load")
        self.check()
        await self.page.get_by_text("经开区 · 模拟政务站", exact=True).wait_for()
        await self.capture("打开模拟登录页")
        await self.click("login")
        await self.op("service").select_option(label="模拟企业备案")
        await self.capture("选择模拟企业备案")
        await self.click("apply-next")
        await self.click("upload")
        await self.capture("选用预设演示附件")
        await self.click("upload-next")
        await self.capture("打开验证码核验页", "otp")
        # 只读取模拟站直接显示的演练码，在人工许可后填写。
        code = await self.page.locator("#captcha .code").inner_text(timeout=10_000)
        self.check()
        await self.op("captcha").fill(code)
        await self.click("verify")
        await self.page.locator("#confirm").wait_for()
        if await self.op("sign").is_visible():
            await self.capture("打开模拟签章页", "sign")
            await self.click("sign")
        if await self.op("pay").is_visible():
            await self.capture("打开模拟付款页", "pay")
            await self.click("pay")
        await self.capture("核对申报资料", "submit")
        await self.click("submit")
        await self.page.locator("#done").wait_for()
        receipt = await self.page.locator("#receipt").inner_text()
        if not re.fullmatch(r"SIM-[0-9A-F]{8}", receipt):
            raise ComputerError("CHECK_FAILED", "模拟站未返回有效的受理编号")
        result = {"no": receipt, "at": now()}
        self.run.record_result(result)
        await self.capture("记录模拟申报受理回执")
        return result


class PlaywrightRunner:
    def __init__(self, url: str, *, channel: str | None = None):
        self.url = mock_url(url)
        self.channel = channel

    async def __call__(self, run: Run) -> dict:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(channel=self.channel, timeout=15_000)
            try:
                context = await browser.new_context(service_workers="block", accept_downloads=False,
                                                    viewport={"width": 1024, "height": 768})
                page = await context.new_page()
                page.set_default_timeout(10_000)
                session = BrowserSession(page, run, self.url)
                await context.route("**/*", session.route)
                await context.route_web_socket("**/*", session.block_websocket)
                try:
                    return await session.apply()
                except Exception:
                    session.check()
                    raise
            finally:
                await browser.close()

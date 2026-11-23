import asyncio
from base64 import b64decode
from contextlib import asynccontextmanager, contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import os
from pathlib import Path
import re
import shutil
from threading import Thread
import time
from types import SimpleNamespace

import pytest

from jkq.computer.browser import BrowserSession, PlaywrightRunner, mock_url
from jkq.computer.runs import ComputerError, PREFIX, Run, Runs, TIMEOUT_SECONDS


MOCK_SITE = Path(__file__).resolve().parents[2] / "deploy/mock-gov/site"
ARGS = {"task": "apply", "ent": None, "from": ""}
PNG_PATTERN = r'<img alt="步骤截图" src="data:image/png;base64,([A-Za-z0-9+/=]+)">'


def allow():
    return True


def audit_stub(*_):
    pass


@pytest.mark.parametrize("kind", ["otp", "sign", "pay", "submit"])
def test_each_gate_decline_stops_without_applying(kind):
    async def scenario():
        entered = asyncio.Event()
        actions = []

        async def runner(run):
            entered.set()
            await run.capture("模拟操作", b"png", kind=kind)
            actions.append(kind)
            return {"no": "SIM-1234ABCD"}

        service = Runs("http://127.0.0.1:8090/", runner, audit_stub)
        run = service.start("owner", "演示经办人", ARGS, None, allow)
        await entered.wait()
        assert run.snapshot()["status"] == "waiting"
        assert run.snapshot()["pending"] == {"kind": kind, "step": 0}
        with pytest.raises(ComputerError, match="确认类型"):
            run.confirm("approve", "otp" if kind != "otp" else "submit")
        assert actions == []
        run.confirm("decline", None)
        await service.close()
        assert run.snapshot()["status"] == "stopped"
        assert run.snapshot()["result"] is None
        assert actions == []
        with pytest.raises(ComputerError, match="没有可以确认"):
            run.confirm("approve", kind)

    asyncio.run(scenario())


def test_approval_once_and_revocation_during_wait():
    async def scenario():
        entered = asyncio.Event()
        next_gate = asyncio.Event()
        permitted = True
        actions = []
        audit = []

        async def runner(run):
            entered.set()
            await run.capture("验证码", b"png", kind="otp")
            actions.append("otp")
            next_gate.set()
            await run.capture("提交", b"png", kind="submit")
            actions.append("submit")
            return {}

        runs = Runs("http://127.0.0.1:8090/", runner, lambda *event: audit.append(event))
        run = runs.start("owner", "演示经办人", ARGS, "same", lambda: permitted)
        assert runs.start("owner", "演示经办人", ARGS, "same", allow) is run
        with pytest.raises(ComputerError, match="幂等键"):
            runs.start("owner", "演示经办人", {**ARGS, "ent": "E001"}, "same", allow)
        with pytest.raises(ComputerError, match="不存在"):
            runs.get("someone-else", run.data["id"])
        with pytest.raises(ComputerError, match="席位"):
            runs.start("owner", "演示经办人", ARGS, "another", allow)
        await entered.wait()
        run.confirm("approve", "otp")
        with pytest.raises(ComputerError, match="没有可以确认"):
            run.confirm("approve", "otp")
        await next_gate.wait()
        assert actions == ["otp"]
        permitted = False
        with pytest.raises(ComputerError, match="失去操作权限"):
            run.confirm("approve", "submit")
        runs.set_allowed("admin", "zcdx", False)
        await runs.close()
        assert run.snapshot()["status"] == "stopped"
        assert actions == ["otp"]
        assert [action for _, action, _ in audit].count("computer.confirm.approve") == 1

    asyncio.run(scenario())


def test_wall_clock_timeout_includes_waiting_and_discards_confirmation():
    async def scenario():
        entered = asyncio.Event()
        cleanup = asyncio.Event()
        release = asyncio.Event()

        async def runner(run):
            entered.set()
            try:
                await run.capture("确认材料", b"png", kind="submit")
            finally:
                cleanup.set()
                await release.wait()
            pytest.fail("超时后不应执行提交")

        assert TIMEOUT_SECONDS == 600
        assert Runs("", runner, audit_stub, timeout=601).timeout == 600
        service = Runs("http://127.0.0.1:8090/", runner, audit_stub, timeout=0.1)
        run = service.start("owner", "演示经办人", ARGS, None, allow)
        await entered.wait()
        assert run.snapshot()["status"] == "waiting"
        await asyncio.wait_for(cleanup.wait(), 2)
        assert not run.job.done()
        data = run.snapshot()
        assert data["status"] == "failed"
        assert "超时" in data["error"]["message"]
        assert data["pending"] is data["result"] is None
        assert "超时" in data["log"][-1]["text"]
        with pytest.raises(ComputerError, match="没有可以确认"):
            run.confirm("approve", "submit")
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await run.job

    asyncio.run(scenario())


@pytest.mark.parametrize("address", [
    "https://127.0.0.1:8090/", "http://localhost:8090/", "http://127.0.0.1/",
    "http://127.0.0.1:8090/?x=1", "http://127.0.0.1:8090@localhost/",
    "http://127.0.0.1:8090.evil.example/", "http://[::1]:8090/",
])
def test_configuration_rejects_addresses_outside_local_mock(address):
    with pytest.raises(ComputerError) as error:
        mock_url(address)
    assert error.value.error["code"] == "OUTBOUND_DENIED"


def test_guard_checks_destination_and_method_before_sending():
    class Route:
        def __init__(self, url, method):
            self.request = SimpleNamespace(url=url, method=method)
            self.aborted = False

        async def abort(self):
            self.aborted = True

        async def fetch(self, **_):
            pytest.fail("拒绝的请求不得联网")

    async def scenario():
        for url, method in [
            ("http://127.0.0.1:8091/", "GET"), ("http://192.0.2.10/", "GET"),
            ("file:///tmp/example.txt", "GET"), ("http://127.0.0.1:8090/", "POST"),
        ]:
            run = SimpleNamespace(reject_pending=lambda _: None)
            session = BrowserSession(None, run, "http://127.0.0.1:8090/")
            route = Route(url, method)
            await session.route(route)
            assert route.aborted
            with pytest.raises(ComputerError, match="已拦截"):
                session.check()

    asyncio.run(scenario())


def test_browser_blocks_protected_click_without_exact_approval():
    async def scenario():
        run = Run("owner", {"status": "running"}, asyncio.get_running_loop().time() + 1,
                  audit_stub, allow)
        session = BrowserSession(None, run, "http://127.0.0.1:8090/")
        session.approved = "otp"
        for target in ("submit", "sign", "pay"):
            with pytest.raises(ComputerError, match="必须先"):
                await session.click(target)

    asyncio.run(scenario())


@contextmanager
def api_client(runner, *, timeout=TIMEOUT_SECONDS, audit=audit_stub):
    fastapi = pytest.importorskip("fastapi")
    client_module = pytest.importorskip("fastapi.testclient")
    from jkq.computer.api import create_router

    def user(request: fastapi.Request):
        role = request.headers.get("x-fixture-user")
        if role is None:
            raise fastapi.HTTPException(status_code=401)
        return SimpleNamespace(id=role, name="演示经办人", roles=(role,))

    runs = Runs(runner.url, runner, audit, timeout=timeout)
    app = fastapi.FastAPI()
    app.include_router(create_router(runs, user, lambda _, actor: (
        {"view", "operate", "admin"} if actor.id in {"admin", "partner"} else {"view", "operate"}
    )))

    @asynccontextmanager
    async def lifespan(_):
        try:
            yield
        finally:
            await runs.close()

    app.router.lifespan_context = lifespan
    with client_module.TestClient(app, headers={"x-fixture-user": "member"}) as client:
        yield client


def test_api_permissions_and_task_discovery():
    async def unused(_):
        pytest.fail("权限测试无需启动浏览器")

    unused.url = "http://127.0.0.1:8090/"
    with api_client(unused) as client:
        partner = {"x-fixture-user": "partner"}
        for method, route, body in [
            ("GET", "/tasks", None), ("PATCH", "/systems/zcdx", {"allowed": False}),
            ("POST", "/match", {"text": "申报 E001"}), ("GET", "/runs", None),
            ("GET", "/runs/some-id", None), ("POST", "/runs", {"task": "apply"}),
            ("PATCH", "/runs/some-id", {"status": "stopped"}),
            ("POST", "/runs/some-id/confirm", {"decision": "decline"}),
        ]:
            denied = client.request(method, PREFIX + route, json=body, headers=partner)
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "FORBIDDEN"
        discovered = client.get(PREFIX + "/tasks").json()
        assert discovered["items"][0]["id"] == "apply"
        assert discovered["systems"][0]["allowed"] is True
        assert client.post(PREFIX + "/match", json={"text": "给 E001 填写申报表"}).json() == {
            "task": discovered["items"][0], "entId": "E001",
        }
        assert client.post(PREFIX + "/match", json={"text": "帮我算数"}).json()["task"] is None
        denied = client.patch(PREFIX + "/systems/zcdx", json={"allowed": False})
        assert denied.status_code == 403
        system = client.patch(PREFIX + "/systems/zcdx", json={"allowed": False},
                              headers={"x-fixture-user": "admin"})
        assert system.json()["item"]["allowed"] is False
        assert client.post(PREFIX + "/runs", json={"task": "apply"}).status_code == 403
        assert client.post(PREFIX + "/runs", json={"task": "status"}).status_code == 404


def test_install_uses_core_session_and_audit(request):
    pytest.importorskip("fastapi")
    from haiknow_core.main import current_user
    from jkq.computer.api import install

    client = request.getfixturevalue("make_client")()
    install(client.app, current_user, url="http://127.0.0.1:8090/")
    with client:
        no_session = client.get(PREFIX + "/tasks")
        assert no_session.status_code == 401
        assert no_session.json()["error"]["code"] == "UNAUTHENTICATED"
        assert client.post("/api/auth/login", json={"user_id": "sampleadmin"}).status_code == 200
        saved = client.patch(PREFIX + "/systems/zcdx", json={"allowed": False})
        assert saved.status_code == 200
        [entry] = client.app.state.platform.store.audit_list("computer")
        assert entry["action"] == "computer.system.update"
        assert entry["detail"] == {"systemId": "zcdx", "allowed": False, "via": "computer"}


@contextmanager
def local_site(path, *, redirect=None):
    class SiteHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            requests.append(self.path)
            if redirect and self.path == "/":
                self.send_response(302)
                self.send_header("Location", redirect)
                self.end_headers()
                return
            if self.path in {"/signed", "/submitted", "/paid"}:
                self.send_response(204)
                self.end_headers()
                return
            super().do_GET()

    requests = []
    with ThreadingHTTPServer(("127.0.0.1", 0), partial(SiteHandler, directory=path)) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/", requests
        finally:
            server.shutdown()
            thread.join()


def browser_runner(url):
    pytest.importorskip("playwright.async_api")
    return PlaywrightRunner(url, channel=os.environ.get("JKQ_TEST_BROWSER_CHANNEL"))


def poll(client, resource, predicate, headers=None):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        response = client.get(resource, headers=headers or {})
        assert response.status_code == 200, response.text
        item = response.json()["item"]
        if predicate(item):
            return item
        if item["status"] in {"failed", "done", "stopped"}:
            pytest.fail(f"任务提前终止：{item['status']} {item.get('error')}")
        time.sleep(0.03)
    pytest.fail("等待运行状态超时")


def begin(client, *, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    response = client.post(PREFIX + "/runs", json={"task": "apply", "ent": "E001"}, headers=headers)
    assert response.status_code == 202, response.text
    return PREFIX + "/runs/" + response.json()["item"]["id"]


def wait_gate(client, resource, kind):
    return poll(client, resource, lambda r: r["status"] == "waiting" and r["pending"]["kind"] == kind)


def approve(client, resource, kind):
    return client.post(resource + "/confirm", json={"decision": "approve", "kind": kind})


def test_real_mock_gov_completes_only_after_approvals_with_evidence():
    audit = []
    with local_site(MOCK_SITE) as (url, requests), api_client(
        browser_runner(url), audit=lambda *event: audit.append(event),
    ) as client:
        resource = begin(client, key="apply-1")
        assert begin(client, key="apply-1") == resource
        waiting = wait_gate(client, resource, "otp")
        assert waiting["result"] is None and waiting["shotCount"] == 4
        assert client.get(resource, headers={"x-fixture-user": "another"}).status_code == 404
        forged = client.patch(resource, json={"status": "stopped", "shot": "<script>", "log": "伪造"})
        assert forged.status_code == 403
        assert approve(client, resource, "submit").status_code == 409
        assert client.get(resource).json()["item"]["pending"]["kind"] == "otp"
        assert approve(client, resource, "otp").status_code == 200
        assert approve(client, resource, "otp").status_code == 409
        waiting = wait_gate(client, resource, "submit")
        assert waiting["result"] is None and waiting["shotCount"] == 5
        assert approve(client, resource, "submit").status_code == 200
        result = poll(client, resource, lambda r: r["status"] == "done")
        assert re.fullmatch(r"SIM-[0-9A-F]{8}", result["result"]["no"])
        assert result["shotCount"] == len(result["steps"]) == len(result["shots"]) == 6
        for step, shot in zip(result["steps"], result["shots"]):
            assert step["status"] == "done"
            assert any(entry["text"].startswith(step["title"]) for entry in result["log"])
            assert b64decode(re.fullmatch(PNG_PATTERN, shot)[1]).startswith(b"\x89PNG\r\n\x1a\n")
        assert result["log"][-1]["text"] == "模拟申报已完成"
        assert all("2468" not in row["text"] for row in result["log"])
        assert set(requests) <= {"/", "/style.css", "/app.js", "/favicon.ico"}
        brief = client.get(PREFIX + "/runs?limit=1").json()
        assert brief["total"] == 1 and "shots" not in brief["items"][0]
        assert sum(action == "computer.confirm.approve" for _, action, _ in audit) == 2


@pytest.fixture
def mock_with_gates(tmp_path):
    site = tmp_path / "site"
    shutil.copytree(MOCK_SITE, site)
    index = site / "index.html"
    index.write_text(
        index.read_text().replace("form-action", "connect-src 'self'; form-action")
        .replace('<button data-op="submit">', '<button data-op="sign">模拟签章</button>'
                 '<button data-op="pay">模拟付款</button><button data-op="submit">')
        .replace("</header>", '<input id="fixture-password" type="password" '
                 'value="demo-only" placeholder="模拟密码"></header>'),
        encoding="utf-8",
    )
    with (site / "app.js").open("a", encoding="utf-8") as js:
        for op, hit in [("sign", "signed"), ("pay", "paid"), ("submit", "submitted")]:
            js.write(f'\nop("{op}").addEventListener("click", () => fetch("/{hit}"));\n')
    with (site / "style.css").open("a", encoding="utf-8") as css:
        for selector, top in [("#fixture-password", 120), ("#captcha .code", 175), ("#digits", 220)]:
            css.write(
                f"\n{selector} {{position: fixed; z-index: 9; left: 12px; top: {top}px; "
                "width: 115px; height: 28px; margin: 0; background: #f00;}\n"
            )
    return site


@pytest.mark.parametrize("decline_at", ["sign", "submit"])
def test_real_sign_and_pay_pause_then_decline_never_submits(mock_with_gates, decline_at):
    with local_site(mock_with_gates) as (url, requests), api_client(browser_runner(url)) as client:
        resource = begin(client)
        wait_gate(client, resource, "otp")
        assert approve(client, resource, "otp").status_code == 200
        wait_gate(client, resource, "sign")
        assert not set(requests) & {"/signed", "/paid", "/submitted"}
        if decline_at == "submit":
            assert approve(client, resource, "sign").status_code == 200
            wait_gate(client, resource, "pay")
            assert "/paid" not in requests
            assert approve(client, resource, "pay").status_code == 200
            wait_gate(client, resource, "submit")
            assert "/signed" in requests and "/paid" in requests
        denied = client.post(resource + "/confirm", json={"decision": "decline"})
        assert denied.status_code == 200
        assert denied.json()["item"]["status"] == "stopped"
        assert client.get(resource).json()["item"]["result"] is None
    assert "/submitted" not in requests
    if decline_at == "sign":
        assert "/signed" not in requests


def test_real_png_masks_password_and_both_captcha_surfaces(mock_with_gates):
    image = pytest.importorskip("PIL.Image")
    with local_site(mock_with_gates) as (url, _), api_client(browser_runner(url)) as client:
        resource = begin(client)
        waiting = wait_gate(client, resource, "otp")
        png = b64decode(re.fullmatch(PNG_PATTERN, waiting["shots"][-1])[1])
        with image.open(BytesIO(png)) as screenshot:
            rgb = screenshot.convert("RGB")
            assert rgb.size == (1024, 768)
            for top in (120, 175, 220):
                assert rgb.getpixel((20, top + 5)) == (0, 0, 0), f"未遮盖测试控件 y={top}"


@pytest.mark.parametrize("via_redirect", [False, True])
def test_real_network_guard_records_denial_without_contacting_other_origin(tmp_path, via_redirect):
    with local_site(tmp_path) as (other, unexpected):
        local = tmp_path / "local"
        local.mkdir()
        (local / "index.html").write_text(f'<script src="{other}"></script>', encoding="utf-8")
        with local_site(local, redirect=other if via_redirect else None) as (url, _):
            with api_client(browser_runner(url)) as client:
                resource = begin(client)
                failed = poll(client, resource, lambda r: r["status"] == "failed")
                assert failed["error"]["code"] == "OUTBOUND_DENIED"
                assert "白名单" in failed["log"][-1]["text"]
        assert unexpected == []


def test_real_network_denial_while_waiting_fails_without_a_decision(mock_with_gates, tmp_path):
    with local_site(tmp_path) as (other, unexpected):
        index = mock_with_gates / "index.html"
        index.write_text(index.read_text().replace("connect-src 'self'", "connect-src *"), encoding="utf-8")
        with (mock_with_gates / "app.js").open("a", encoding="utf-8") as js:
            js.write(f'\nop("upload-next").addEventListener("click", () => '
                     f'setTimeout(() => fetch("{other}").catch(() => {{}}), 1000));\n')
        with local_site(mock_with_gates) as (url, requests), api_client(browser_runner(url)) as client:
            resource = begin(client)
            wait_gate(client, resource, "otp")
            failed = poll(client, resource, lambda r: r["status"] == "failed")
            assert failed["error"]["code"] == "OUTBOUND_DENIED"
            assert failed["pending"] is failed["result"] is None
            assert "白名单" in failed["log"][-1]["text"]
            assert approve(client, resource, "otp").status_code == 409
        assert unexpected == []
        assert "/submitted" not in requests


class FakeRunner:
    url = "http://127.0.0.1:8090/"

    def __init__(self, handler):
        self.handler = handler

    async def __call__(self, run):
        return await self.handler(run)


def test_empty_ent_and_denied_audit():
    recorded = []

    async def finish(run):
        run.record_result({"no": "SIM-AAAAAAAA", "at": "t"})
        return run.data["result"]

    with api_client(FakeRunner(finish), audit=lambda *event: recorded.append(event)) as client:
        created = client.post(PREFIX + "/runs", json={"task": "apply", "ent": ""})
        assert created.status_code == 202
        assert created.json()["item"]["ent"] is None
        poll(client, PREFIX + "/runs/" + created.json()["item"]["id"], lambda r: r["status"] == "done")
        partner = {"x-fixture-user": "partner"}
        denied = client.get(PREFIX + "/tasks", headers=partner)
        assert denied.status_code == 403
        error = denied.json()["error"]
        assert error["code"] == "FORBIDDEN"
        assert error["details"] == {"app": "computer", "need": "view"}
        assert any(action == "computer.denied" and detail["need"] == "view"
                   for _, action, detail in recorded)
        member = client.get(PREFIX + "/tasks")
        member.raise_for_status()
        lost = client.patch(PREFIX + "/systems/zcdx", json={"allowed": False},
                            headers={"x-fixture-user": "member"})
        assert lost.status_code == 403
        assert lost.json()["error"]["details"] == {"app": "computer", "need": "admin"}


def test_receipt_survives_stop_after_submit():
    release = asyncio.Event()

    async def hang_after_receipt(run):
        run.record_result({"no": "SIM-BBBBBBBB", "at": "t"})
        await release.wait()
        return run.data["result"]

    with api_client(FakeRunner(hang_after_receipt)) as client:
        resource = PREFIX + "/runs/" + client.post(PREFIX + "/runs", json={"task": "apply"}).json()["item"]["id"]
        item = poll(client, resource, lambda r: r.get("result"))
        assert item["result"]["no"] == "SIM-BBBBBBBB"
        stopped = client.patch(resource, json={"status": "stopped"})
        assert stopped.status_code == 200
        saved = client.get(resource).json()["item"]
        assert saved["result"]["no"] == "SIM-BBBBBBBB"
        assert saved["status"] in {"done", "stopped"}
        release.set()


def test_other_operator_volume_does_not_drop_records():
    async def finish(run):
        run.record_result({"no": "SIM-CCCCCCCC", "at": "t"})
        return run.data["result"]

    with api_client(FakeRunner(finish)) as client:
        first = client.post(PREFIX + "/runs", json={"task": "apply"},
                            headers={"Idempotency-Key": "keep-me"})
        first.raise_for_status()
        first_id = first.json()["item"]["id"]
        poll(client, PREFIX + "/runs/" + first_id, lambda r: r["status"] == "done")
        other = {"x-fixture-user": "another"}
        for index in range(30):
            created = client.post(PREFIX + "/runs", json={"task": "apply"},
                                  headers={**other, "Idempotency-Key": f"other-{index}"})
            created.raise_for_status()
            poll(client, PREFIX + "/runs/" + created.json()["item"]["id"],
                 lambda r: r["status"] == "done", headers=other)
        assert client.get(PREFIX + "/runs/" + first_id).status_code == 200
        again = client.post(PREFIX + "/runs", json={"task": "apply"},
                            headers={"Idempotency-Key": "keep-me"})
        assert again.json()["item"]["id"] == first_id
        listed = client.get(PREFIX + "/runs?limit=100", headers=other).json()
        assert listed["total"] == 30

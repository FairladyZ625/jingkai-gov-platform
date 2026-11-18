"""只在回环地址运行，模型与账号配置全部来自临时测试环境。"""

import os
import secrets
import socket
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn
    from jkq.app import create_app

    tmp = tmp_path_factory.mktemp("demo-http")
    password = secrets.token_urlsafe(16)
    handler = partial(SimpleHTTPRequestHandler, directory=ROOT / "deploy/mock-gov/site")
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as site, pytest.MonkeyPatch.context() as env:
        for name in tuple(os.environ):
            if name.startswith(("HAIKNOW_", "JKQ_")):
                env.delenv(name)
        for key, value in {
            "HAIKNOW_SECRET": secrets.token_urlsafe(32), "HAIKNOW_DATA_DIR": str(tmp / "data"),
            "HAIKNOW_NO_AUTOAPP": "1", "HAIKNOW_KB_SEED": "1", "JKQ_DEMO_MODE": "1",
            "JKQ_ENTERPRISE_PRIVATE_DB": str(tmp / "enterprise.db"),
            "JKQ_MOCK_GOV_URL": f"http://127.0.0.1:{site.server_port}",
        }.items():
            env.setenv(key, value)
        for role in ("ADMIN", "MEMBER", "PARTNER", "LEADER"):
            env.setenv(f"JKQ_DEMO_{role}_PASSWORD", password)
        from jkq.kb.importer.public_url import PublicPage, PublicURLReader

        async def read_fixture(reader, url):
            assert url == "https://example.invalid/demo-notice"
            return PublicPage(url, "演示导入通知", "第一条 演示材料已受理。")

        env.setattr(PublicURLReader, "read", read_fixture)
        app = create_app()
        site_thread = threading.Thread(target=site.serve_forever, daemon=True)
        site_thread.start()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            instance = uvicorn.Server(uvicorn.Config(app, log_level="error"))
            thread = threading.Thread(target=instance.run, kwargs={"sockets": [listener]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not instance.started:
                    assert thread.is_alive() and time.monotonic() < deadline, "实例启动失败"
                    time.sleep(0.02)
                yield f"http://127.0.0.1:{listener.getsockname()[1]}", password
            finally:
                instance.should_exit = True
                thread.join(10)
                site.shutdown()
                site_thread.join()

"""只在回环地址运行，模型与账号配置全部来自临时测试环境。"""

import json
import os
import re
import shutil
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class DemoServer:
    url: str
    password: str = field(repr=False)
    reset_key: str = field(repr=False)


@pytest.fixture(scope="module")
def server(tmp_path_factory, request):
    import uvicorn
    from jkq.app import create_app

    tmp = tmp_path_factory.mktemp("demo-http")
    password = secrets.token_urlsafe(16)
    reset_key = secrets.token_urlsafe(32)
    handler = partial(SimpleHTTPRequestHandler, directory=ROOT / "deploy/mock-gov/site")
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as site, pytest.MonkeyPatch.context() as env:
        for name in tuple(os.environ):
            if name.startswith(("HAIKNOW_", "JKQ_")):
                env.delenv(name)
        for key, value in {
            "HAIKNOW_SECRET": secrets.token_urlsafe(32), "HAIKNOW_DATA_DIR": str(tmp / "data"),
            "HAIKNOW_NO_AUTOAPP": "1", "HAIKNOW_KB_SEED": "1", "JKQ_DEMO_MODE": "1",
            "JKQ_DEMO_RESET_KEY": reset_key,
            "JKQ_ENTERPRISE_PRIVATE_DB": str(tmp / "enterprise.db"),
            "JKQ_MOCK_GOV_URL": f"http://127.0.0.1:{site.server_port}",
        }.items():
            env.setenv(key, value)
        for role in ("ADMIN", "MEMBER", "PARTNER", "LEADER"):
            env.setenv(f"JKQ_DEMO_{role}_PASSWORD", password)
        if hasattr(request, "param"):
            from deploy.entrypoint import use_same_origin_http
            from jkq.settings import web_directory
            import yaml

            source = Path(os.environ.get("T49_TEST_WEB") or web_directory(ROOT))
            site_dir = shutil.copytree(source, tmp / "web")
            config_dir = shutil.copytree(ROOT / "config", tmp / "config")
            demo_path = config_dir / "demo.yaml"
            options = yaml.safe_load(demo_path.read_text())
            options["mock_modules"] = list(request.param)
            demo_path.write_text(yaml.safe_dump(options, allow_unicode=True))
            env.setenv("HAIKNOW_CONFIG_DIR", str(config_dir))
            env.setenv("JKQ_WEB_DIR", str(site_dir))
            env.setenv("JKQ_DEPLOY_RUNTIME", "1")
            use_same_origin_http(tmp)
            with (site_dir / "config/app.config.js").open("a") as script:
                script.write("\nwindow.JK_CONFIG.demoAccounts.forEach(a => a.password = " +
                             json.dumps(password) + ");\n")
        from jkq.kb.importer.public_url import PublicPage, PublicURLError, PublicURLReader

        # 演示不出外网：接口验收用的虚构网址和知识库段的官网样例网址都由本地快照应答。
        kb_config = (ROOT / "prototype/v4/apps/kb/config.js").read_text(encoding="utf-8")
        sample_url = re.search(r"sampleUrl:\s*'([^']+)'", kb_config)[1]
        pages = {
            "https://example.invalid/demo-notice": ("演示导入通知", "第一条 演示材料已受理。"),
            sample_url: ("数据券申报延期通知（演示快照）", "第一条 数据券申报期限延长，演示快照不访问外网。"),
        }

        async def read_fixture(reader, url):
            if url not in pages:
                raise PublicURLError(502, "URL_FETCH_FAILED", "演示环境不访问外网，请改用粘贴正文")
            return PublicPage(url, *pages[url])

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
                yield DemoServer(f"http://127.0.0.1:{listener.getsockname()[1]}", password, reset_key)
            finally:
                instance.should_exit = True
                thread.join(10)
                site.shutdown()
                site_thread.join()

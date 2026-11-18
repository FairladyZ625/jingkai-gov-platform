"""现有 pytest 作业通过系统 Chrome 执行站点的浏览器契约。"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
from threading import Thread

HERE = Path(__file__).resolve().parent


def test_application_flow(tmp_path):
    for name in ("package.json", "package-lock.json", "flow.mjs"):
        shutil.copy(HERE / name, tmp_path)
    subprocess.run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                   cwd=tmp_path, check=True)
    handler = partial(SimpleHTTPRequestHandler, directory=HERE.parent / "site")
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            subprocess.run(["node", "flow.mjs", f"http://127.0.0.1:{server.server_port}"],
                           cwd=tmp_path, check=True, timeout=90)
        finally:
            server.shutdown()
            thread.join()

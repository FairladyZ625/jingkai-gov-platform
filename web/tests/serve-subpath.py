"""以 /v4/ 为唯一可用入口，防止根路径资源把子路径问题掩盖掉。"""
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


class MountedWeb(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(Path(__file__).resolve().parents[1]), **kwargs)

    def send_head(self):
        target = urlsplit(self.path)
        if not target.path.startswith("/v4/") or ".." in unquote(target.path).split("/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return None
        self.path = self.path.removeprefix("/v4")
        return super().send_head()


if __name__ == "__main__":
    with ThreadingHTTPServer(("127.0.0.1", 8081), MountedWeb) as server:
        server.serve_forever()

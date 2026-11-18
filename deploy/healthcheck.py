"""应用已监听，且本机首管入口已关闭，才允许反代对外发布。"""
from __future__ import annotations

import http.client
import os
import sys


def ready(port: int) -> bool:
    try:
        health = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        health.request("GET", "/api/health")
        if health.getresponse().status != 200:
            return False
        for path in ("/api/v1/auth/bootstrap", "/api/auth/bootstrap"):
            probe = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            probe.request("POST", path, b"{}", {"Content-Type": "application/json"})
            if probe.getresponse().status != 404:
                return False
    except OSError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(0 if ready(int(os.environ.get("APP_PORT", "8000"))) else 1)

"""由运维显式启用的 HTTPS 验收；凭据只从环境传入。"""
import http.client
import json
import os
import time
from http.cookies import SimpleCookie
from urllib.parse import quote

import pytest


@pytest.fixture
def api():
    domain = os.getenv("JKQ_VERIFY_DOMAIN")
    if not domain:
        pytest.skip("未指定验收域名")
    connection = http.client.HTTPSConnection(domain, timeout=15)
    cookies = {}

    def call(method, path, payload=None):
        headers = {"Content-Type": "application/json",
                   "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}
        connection.request(method, path, json.dumps(payload) if payload else None, headers)
        response = connection.getresponse()
        for name, value in response.getheaders():
            if name.lower() == "set-cookie":
                cookies.update({k: v.value for k, v in SimpleCookie(value).items()})
        body = response.read()
        if response.status != 200:
            pytest.fail(f"{method} {path} 返回 {response.status}", pytrace=False)
        return body

    yield call
    connection.close()


def login(api, role):
    prefix = f"JKQ_VERIFY_{role.upper()}_"
    body = api("POST", "/api/v1/auth/login", {
        "username": os.environ[prefix + "USER"],
        "password": os.environ[prefix + "PASSWORD"],
    })
    result = json.loads(body)
    actual = result["role"]
    if (actual.get("id") if isinstance(actual, dict) else actual) != role:
        pytest.fail("登录角色与验收角色不符", pytrace=False)
    if not json.loads(api("GET", "/api/v1/auth/session")).get("user"):
        pytest.fail("会话未生效", pytrace=False)


def test_health(api):
    api("GET", "/api/health")


@pytest.mark.parametrize("role", ["admin", "leader", "member", "partner"])
def test_login(api, role):
    login(api, role)


def test_checkpoint_after_restart(api):
    job = os.getenv("JKQ_VERIFY_JOB")
    if not job:
        pytest.skip("待提供重启前运行中的 job ID")
    login(api, os.environ.get("JKQ_VERIFY_JOB_ROLE", "member"))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = json.loads(api("GET", "/api/v1/jobs/" + quote(job, safe="")))["job"]
        assert result["id"] == job
        if result["status"] == "done":
            return
        assert result["status"] == "running"
        time.sleep(2)
    pytest.fail("重启后的 job 未在两分钟内完成")

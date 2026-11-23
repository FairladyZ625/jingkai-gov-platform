"""与浏览器使用同一协议桩；在无法监听端口的环境也能核验真实工作流。"""
import os
import secrets
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


@pytest.mark.parametrize("mode", ["no-model", "unapproved-endpoint", "approved-protocol"])
def test_skill_trial_and_publication(tmp_path, monkeypatch, mode):
    from jkq.app import create_app
    from tests.demo_http.skill_protocol import MODEL, install

    for key in tuple(os.environ):
        if key.startswith(("HAIKNOW_", "JKQ_")):
            monkeypatch.delenv(key)
    root = Path(__file__).resolve().parents[2]
    password = secrets.token_urlsafe(20)
    for role in ("ADMIN", "MEMBER", "PARTNER", "LEADER"):
        monkeypatch.setenv(f"JKQ_DEMO_{role}_PASSWORD", password)
    for key, value in {"HAIKNOW_CONFIG_DIR": str(root/"config"), "HAIKNOW_DATA_DIR": str(tmp_path/"data"),
                       "JKQ_ENTERPRISE_PRIVATE_DB": str(tmp_path/"fixture.sqlite"), "HAIKNOW_NO_AUTOAPP": "1",
                       "JKQ_DEMO_MODE": "1", "HAIKNOW_SECRET": secrets.token_urlsafe(32)}.items():
        monkeypatch.setenv(key, value)
    app = create_app()
    if mode != "no-model":
        install(app, monkeypatch, approved=mode == "approved-protocol")
    with TestClient(app) as c:
        def post(path, **body):
            result = c.post(path, json=body)
            result.raise_for_status()
            return result.json()
        post("/api/v1/auth/login", username="wangmin", password=password)
        base = "/api/v1/skills"
        answer = post(base+"/draft", text="核对数据券申报材料齐不齐")
        draft = answer["draft"]
        item = post(base, **{k:draft[k] for k in ("name","summary","spec")})["item"]
        path = base+"/"+item["id"]
        job = post(base+"/trial", skill={"name":item["name"],"spec":item["spec"]},
                   inputs={f["key"]:f["sample"] for f in item["spec"]["inputs"]})["job"]
        end = time.monotonic()+5
        while job["status"] == "running":
            assert time.monotonic()<end
            time.sleep(.02)
            job = c.get(base+"/jobs/"+job["id"]).json()["job"]
        assert c.get(path).json()["item"]["status"] == "draft"
        if mode != "approved-protocol":
            assert job["status"] == "failed" and job["errorCode"] == "OUTBOUND_DENIED"
            assert job["result"] is None and c.get(path).json()["item"]["share"]["scope"] == "private"
            return
        assert answer.get("source") != "preset" and job["trial"] and job["status"] == "done"
        assert all(s["status"] == "done" for s in job["steps"])
        assert job["result"]["model"] == MODEL and job["result"]["citations"]
        assert "【CI 内存协议桩】" in job["result"]["markdown"]
        published = post(path+"/publish", share={"scope":"dept","perm":"use"})["item"]
        assert published["status"] == "published" and c.get(path).json()["item"]["share"]["scope"] == "dept"

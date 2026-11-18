"""演示部署的续跑任务。已完成步骤记在平台检查点里，进程换代后不再执行。"""
from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import APIRouter
from haiknow_sdk.preview.jobs import operation

router = APIRouter()
BOOT_NAME = ".jkq-hold-boot"


def boot_token() -> str:
    data = os.environ.get("HAIKNOW_DATA_DIR", "")
    if not data:
        return ""
    try:
        return (Path(data) / BOOT_NAME).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@operation("hold", version="1")
def hold(job, body):
    def saved(key):
        count = job.context.kv.get("hold-saved", 0) + 1
        job.context.kv.put("hold-saved", count)
        return {"count": count, "key": key}

    done = job.step("saved", saved)

    def finish(key):
        current = boot_token()
        seen = job.context.kv.get("hold-boot")
        if seen and current and seen != current:
            return {"saved": done, "key": key}
        if current:
            job.context.kv.put("hold-boot", current)
        while True:
            job.check_cancelled()
            time.sleep(0.05)

    return job.step("finish", finish)

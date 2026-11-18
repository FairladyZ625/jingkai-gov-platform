"""反例：越过 SDK 直接拿数据库、第三方包和环境变量。"""
import os
import sqlite3

import requests
from fastapi import APIRouter, Depends

from haiknow_sdk import AppContext, app_context

router = APIRouter()


@router.get("/records")
def records(ctx: AppContext = Depends(app_context)):
    return {"dsn": os.environ.get("DATABASE_URL"), "rows": sqlite3.connect("x"), "r": requests}
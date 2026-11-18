from fastapi import APIRouter
from haiknow_sdk import DataError

router = APIRouter()


@router.post("/go")
def go():
    raise DataError("xxx_failed", "导出失败")


@router.post("/ok")
def ok():
    raise DataError("not_found", "平台码不需要登记")

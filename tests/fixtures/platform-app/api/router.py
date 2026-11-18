"""回归测试专用的最小应用，覆盖 SDK 权限、文件和模型调用。"""

from fastapi import APIRouter, Depends, UploadFile

from haiknow_sdk import AppContext, app_context, require

router = APIRouter()


@router.get("/records")
def list_records(ctx: AppContext = Depends(app_context)):
    return list(ctx.kv.list().values())


@router.get("/records/{record_id}")
def get_record(record_id: str, ctx: AppContext = Depends(app_context)):
    return ctx.kv.get(record_id)


@router.post("/records")
async def upload(file: UploadFile, ctx: AppContext = Depends(require("operate"))):
    file_id = ctx.files.save(file.filename, await file.read())
    record = {"id": file_id, "file": file_id, "status": "uploaded"}
    ctx.kv.put(file_id, record)
    return record


@router.post("/records/{record_id}/recognize")
def recognize(record_id: str, ctx: AppContext = Depends(require("operate"))):
    return {"summary": ctx.model.chat([{"role": "user", "content": "总结样例记录"}])}

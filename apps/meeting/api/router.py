"""挂载会议工作流和公开参考资料种子入口。"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from haiknow_sdk import KV, PermissionDenied, app_context

from .workflow import error_response, router as workflow_router

router = APIRouter()
router.include_router(workflow_router)

# #36 合入前可单独加载纪要模块；合入后沿用其上传和任务入口。
try:
    from .meetings import __haiknow_jobs__, router as transcription_router
except ModuleNotFoundError as exc:
    if exc.name != f'{__package__}.meetings':
        raise
else:
    upload_routes = APIRouter()
    upload_routes.routes.extend(route for route in transcription_router.routes if route.name != 'get_meeting')
    router.include_router(upload_routes)


def reset_seed(kv: KV, seed_dir: Path) -> None:
    """用完整快照替换本应用的参考资料，保留其他业务数据。"""
    rows = json.loads((seed_dir / "real" / "minutes.json").read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("会议记录参考资料须为对象数组")
    kv.put("reference:minutes", rows)


@router.get("/health")
def health(request: Request):
    try:
        ctx = app_context(request)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        return error_response("UNAUTHENTICATED", "未登录", 401)
    except PermissionDenied as exc:
        details = {"app": exc.app_id, "need": exc.action}
        return error_response("FORBIDDEN", "无权查看此应用", 403, details)
    return {"id": ctx.app_id, "status": "ok"}

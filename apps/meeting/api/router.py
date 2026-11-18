"""会议记录的健康检查与公开参考资料种子入口。"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from haiknow_sdk import KV, PermissionDenied, app_context

router = APIRouter()


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
        return JSONResponse({"error": {"code": "UNAUTHENTICATED", "message": "未登录", "details": {}}}, status_code=401)
    except PermissionDenied as exc:
        details = {"app": exc.app_id, "need": exc.action}
        return JSONResponse({"error": {"code": "FORBIDDEN", "message": "无权查看此应用", "details": details}}, status_code=403)
    return {"id": ctx.app_id, "status": "ok"}

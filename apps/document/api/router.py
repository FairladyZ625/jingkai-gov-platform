"""公文协作的路由及公开参考资料种子入口。"""
import json
from pathlib import Path

from fastapi import APIRouter
from haiknow_sdk import KV

from .drafting_router import DocumentRoute, Viewer, router as drafting_router

router = APIRouter(route_class=DocumentRoute)
router.include_router(drafting_router)


def reset_seed(kv: KV, seed_dir: Path) -> None:
    """用完整快照替换本应用的参考资料，保留其他业务数据。"""
    rows = json.loads((seed_dir / "real" / "gongwen.json").read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("公文协作参考资料须为对象数组")
    kv.put("reference:gongwen", rows)


@router.get("/health")
def health(ctx: Viewer):
    return {"id": ctx.app_id, "status": "ok"}

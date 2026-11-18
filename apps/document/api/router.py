"""公文协作的健康检查与公开参考资料种子入口。"""
import json
from pathlib import Path

from fastapi import APIRouter, Depends
from haiknow_sdk import AppContext, KV, app_context

router = APIRouter()


def reset_seed(kv: KV, seed_dir: Path) -> None:
    """用完整快照替换本应用的参考资料，保留其他业务数据。"""
    rows = json.loads((seed_dir / "real" / "gongwen.json").read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("公文协作参考资料须为对象数组")
    kv.put("reference:gongwen", rows)


@router.get("/health")
def health(ctx: AppContext = Depends(app_context)):
    return {"id": ctx.app_id, "status": "ok"}

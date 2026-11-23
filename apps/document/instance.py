"""经开区启动时安装的存储约束与平台路由。

应用 API 只通过公开 SDK 写版本。受信实例在启动时为其 SQLite 存储安装公文约束。
"""
import sqlite3
from contextlib import closing

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from apps.policy.api.policy_catalog import catalog, item_with_doc

from .api.drafting_router import error
from .api.drafts import RECORD_TYPE

LOCK_FAILURE = "document_draft_locked"
records_guard = APIRouter(prefix="/api/v1/apps/document")


def _public_policy_lookup(policy_id: str) -> dict | None:
    """为公文模板提供公开政策目录只读查询，避免应用 API 直接跨应用导入。"""
    items, docs = catalog()
    item = items.get(policy_id)
    return item_with_doc(item, docs[item["doc"]]) if item else None


@records_guard.post("/records", include_in_schema=False)
@records_guard.put("/records/{identity}", include_in_schema=False)
def use_document_routes():
    return error(405, "METHOD_NOT_ALLOWED", "请使用公文草稿接口写入文稿")


def _reviews_guard(app):
    """平台通用送审入口不做公文核查，公文只能从 /api/apps/document/drafts/{id}/submit 送审。

    其他应用原样交给平台 DataService，行为与 core 的 POST /api/v1/reviews 相同。
    审签决定仍走 #18 的 /api/v1/reviews/{id}/decisions。
    """
    from haiknow_core.main import current_user

    service = app.state.platform.data
    guard = APIRouter(prefix="/api/v1")

    @guard.post("/reviews", status_code=201, include_in_schema=False)
    def submit_review(body: dict = Body(...), user=Depends(current_user)):
        if body.get("appId") == "document":
            return error(405, "METHOD_NOT_ALLOWED", "公文须经核查后送审，请使用公文送审接口",
                         path="/api/apps/document/drafts/{id}/submit")
        return JSONResponse(service.submit_review(user, body, generic_http=True), status_code=201)

    return guard


def _install_storage_guard(platform):
    """补齐记录 SDK 缺少的原子状态前置条件，仅约束本应用文稿。

    节点审批会在原版本上更改状态，单独比较 baseVersion 无法阻止并发定稿后的写入。
    此约束在 DataService 更新 latest 的 SQLite 写事务内核对状态。
    """
    with closing(sqlite3.connect(platform.store.data_dir / "platform.db")) as connection:
        connection.execute(f"""
            CREATE TRIGGER IF NOT EXISTS document_draft_confirmed_guard
            BEFORE UPDATE OF latest ON v1_records
            WHEN OLD.app = 'document' AND EXISTS (
                SELECT 1 FROM v1_states AS state
                JOIN v1_versions AS edition
                  ON edition.record_id = state.record_id AND edition.version = state.version
                WHERE state.record_id = OLD.id AND state.version = OLD.latest
                  AND state.status = 'confirmed'
                  AND json_extract(edition.document, '$.type') = '{RECORD_TYPE}'
            )
            BEGIN
                SELECT RAISE(ABORT, '{LOCK_FAILURE}');
            END
        """)


def install(app):
    """在实例对外监听前调用一次。"""
    app.state.public_policy_lookup = _public_policy_lookup
    _install_storage_guard(app.state.platform)

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request, exc):
        if str(exc) != LOCK_FAILURE:
            raise exc
        return error(409, "LOCKED", "已定稿文稿不能修改，请另存新稿")

    routes = app.router.routes
    count = len(routes)
    app.include_router(records_guard)
    app.include_router(_reviews_guard(app))
    routes[:] = routes[count:] + routes[:count]

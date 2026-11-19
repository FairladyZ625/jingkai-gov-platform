"""演示配置的业务种子：企业台账与公文版本，幂等写入各应用现有存储。

只由 jkq.demo.install 在 JKQ_DEMO_MODE=1 时接线。宿主按快照重置后，
首个请求会重新补齐缺失的种子，已有记录不重复写入。
"""

import json
import threading
from contextlib import contextmanager
from types import SimpleNamespace

from starlette.requests import Request

# 追加演示企业只需在此加 data/seed/demo.json 里的公开示例 ID。E020 知行大模型为政策段主演企业。
DEMO_COMPANY_IDS = ("E001", "E002", "E020", "E014", "E012")
SEED_USER = "u-wangmin"
DOCUMENT_TITLE = "关于对书香里文化房租补贴诉求的答复意见"
DOCUMENT_INPUTS = {"ent": "书香里文化", "issue": "咨询实体书店房租补贴和发展奖励的申报时间",
                   "to": "北京书香里文化发展有限公司：", "sign": "公文演示工作组", "date": "2026年11月13日"}
DOCUMENT_V1_TAIL = "办理情况及后续安排为今年的通知还没出来，出来以后咱们马上告诉你们。"
DOCUMENT_V2_TAIL = "办理情况及后续安排为：年度申报通知发布后，我局将第一时间告知贵单位，并协助准备申报材料。"


def demo_rows(root, ids=DEMO_COMPANY_IDS):
    from apps.enterprise.api.company import Enterprise

    rows = json.loads((root / "data/seed/demo.json").read_text(encoding="utf-8"))["enterprises"]
    by_id = {row["id"]: row for row in rows}
    fields = set(Enterprise.model_fields)
    result = []
    for ent_id in ids:
        row = {key: value for key, value in by_id[ent_id].items() if key in fields}
        if "yearsInZone" in row:
            row["yearsInZone"] = int(round(row["yearsInZone"]))  # 台账字段为整数年
        result.append((ent_id, row))
    return result


def _context(app, app_id, user_id):
    platform = app.state.platform
    request = Request({
        "type": "http", "method": "POST", "path": f"/api/apps/{app_id}/demo-seed", "headers": [],
        "query_string": b"", "app": app,
        "session": {"uid": user_id, "gen": platform.directory.session_gen(user_id)},
    })
    return platform.resolve(request)


@contextmanager
def _fixed_record_id(platform, record_id):
    """core 新建记录总是随机 ID；演示企业需与政策匹配使用的示例 ID 一致。"""
    import haiknow_core.data as core_data

    with platform.store._lock:
        original = core_data.uuid
        core_data.uuid = SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=record_id))
        try:
            yield
        finally:
            core_data.uuid = original


def seed_companies(app, root):
    from apps.enterprise.api.ledger_store import documents, names_by_id, snapshots, write

    platform = app.state.platform
    ctx = _context(app, "enterprise", SEED_USER)
    existing = {doc["id"] for doc in documents(ctx)}
    created = []
    for ent_id, row in demo_rows(root):
        if ent_id in existing:
            continue
        with snapshots(writing=True) as db, _fixed_record_id(platform, ent_id):
            created.append(write(ctx, db, row, names_by_id(ctx))["id"])
    return created


def seed_documents(app):
    from apps.document.api import drafts, templates

    ctx = _context(app, "document", SEED_USER)
    if any(item["title"] == DOCUMENT_TITLE for item in drafts.summaries(ctx)):
        return None
    spec = templates.draft_template("T10", DOCUMENT_INPUTS)
    content = templates.mock_draft(spec, DOCUMENT_INPUTS, [])
    content["title"] = DOCUMENT_TITLE
    content["paragraphs"] = [p for p in content["paragraphs"] if "【待补" not in p] + [DOCUMENT_V1_TAIL]
    draft = drafts.create(ctx, "T10", None, content, [])
    # 初稿第 0 版不进默认历史；显式保存两次，使「我的文稿」里可比对第 1、2 版。
    drafts.save(ctx, draft["id"], content, "")
    revised = dict(content, paragraphs=content["paragraphs"][:-1] + [DOCUMENT_V2_TAIL])
    return drafts.save(ctx, draft["id"], revised, "")["id"]


def seed(app, root):
    return {"companies": seed_companies(app, root), "document": seed_documents(app)}


class DemoSeed:
    """首个请求前补齐演示种子；失败只记日志，不阻断请求。"""

    def __init__(self, app, target, root):
        self.app = app
        self.target = target
        self.root = root
        self.done = False
        self.lock = threading.Lock()

    def ensure(self):
        with self.lock:
            if not self.done:
                try:
                    seed(self.target, self.root)
                finally:
                    self.done = True

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not self.done:
            from starlette.concurrency import run_in_threadpool

            try:
                await run_in_threadpool(self.ensure)
            except Exception:  # noqa: BLE001 种子失败不阻断演示请求
                import logging

                logging.getLogger("jkq.demo").exception("演示种子写入失败")
        await self.app(scope, receive, send)

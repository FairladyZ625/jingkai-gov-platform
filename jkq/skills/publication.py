"""技能发布、审签与评分，共用 CRUD 的技能库和 core 版本审签。"""
import sqlite3
from contextlib import contextmanager
from copy import copy

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from jkq.jobs_api import replace_core_route
from jkq.reviews_api import list_pending, review_view, sdk_review_list

from .api import SkillRoute
from .spec import SkillError, invalid
from .storage import SkillRecords


class TransactionConnection(sqlite3.Connection):
    """core 多个服务方法共用外层事务，只由 transaction 提交。"""

    def __exit__(self, *exc):
        return False


@contextmanager
def transaction(skills):
    scoped = copy(skills)
    scoped.store = copy(skills.store)
    db = sqlite3.connect(skills.store.data_dir / "platform.db", factory=TransactionConnection)
    try:
        db.execute("ATTACH DATABASE ? AS platform", (str(skills.platform.store.data_dir / "platform.db"),))
        scoped.store._db = db
        scoped.records = copy(skills.records)
        scoped.records.store = scoped.store
        db.execute("BEGIN IMMEDIATE")
        yield scoped
        db.commit()
    finally:
        db.close()  # 发生异常时回滚所有记录、投票及审计。


def share_settings(body, previous, users):
    if not isinstance(body, dict):
        invalid("请提供分享设置")
    scope = body.get("scope", previous["scope"])
    perm = body.get("perm", previous["perm"])
    people = body.get("people", previous["people"])
    if scope not in ("private", "people", "dept", "zone") or perm not in ("use", "edit"):
        invalid("分享范围或权限无效")
    if not isinstance(people, list) or any(not isinstance(p, str) or p not in users for p in people):
        invalid("指定人员无效")
    if scope == "people" and not people:
        invalid("请指定分享人员")
    return {"scope": scope, "perm": perm, "people": list(dict.fromkeys(people)) if scope == "people" else []}


def can_review(skills, user):
    return bool({"admin", "leader"}.intersection(user.roles)) and "approve" in skills.platform.rbac.actions(user, "skills")


def set_share(skills, user, sid, body, action):
    with transaction(skills) as tx:
        doc = tx.load(user, sid, edit=True)
        if doc["data"]["authorId"] != user.id and "admin" not in tx.platform.rbac.actions(user, "skills"):
            raise SkillError(403, "FORBIDDEN", "只有作者或管理员可设置分享")
        share = share_settings(body, doc["data"]["share"], tx.platform.rbac.users)
        pending = share["scope"] == "zone"
        changes = {"share": share, "status": "in_review" if pending else "published",
                   "usefulRate": doc["data"].get("usefulRate", 0)}
        item = tx.save(user, doc, changes, action=action)
        review = None
        if pending:
            review = tx.records.submit_review(user, {"appId": "skills", "recordId": sid, "version": doc["version"] + 1})
            review.update(type="skill", ref=sid, app="skills", title="技能上架申请：" + item["name"])
            tx.records._write_review(tx.store._db, review)
        return {"item": item, "review": review}


def decision(skills, user, sid, body, rid=None):
    with transaction(skills) as tx:
        doc = tx.load(user, sid)
        if doc["data"]["authorId"] == user.id:
            raise SkillError(409, "SELF_REVIEW", "作者不能审核自己的技能")
        if not can_review(skills, user):
            raise SkillError(403, "FORBIDDEN", "只有管理员或审签领导可审核")
        choice = body.get("decision")
        reason = body.get("reason", "")
        if choice not in ("approve", "reject") or not isinstance(reason, str) or (choice == "reject" and not reason.strip()):
            invalid("请选择审核结论，驳回时须填写原因")
        row = tx.store._db.execute("SELECT id FROM v1_reviews WHERE record_id=? AND version=?", (sid, doc["version"])).fetchone()
        if not row or (rid and rid != row[0]) or body.get("version", doc["version"]) != doc["version"]:
            raise SkillError(409, "STALE_VERSION", "待审版本已变化，请重新提交或刷新")
        review = tx.records.decide_review(user, row[0], {"version": doc["version"],
            "decision": "confirm" if choice == "approve" else "return", "comment": reason})
        item = save_outcome(tx, user, doc, {"status": "published" if choice == "approve" else "rejected",
                                           "reviewNote": reason}, "skill.review", "approve")
        return item, review


class OutcomeRecords(SkillRecords):
    """内部结果写入仅接受已验证的评分或审签动作及服务端计算的字段。"""

    def __init__(self, source, permission):
        super().__init__(source.store, source.rbac, source.projects, {})
        self.permission = permission

    def app(self, user, app_id, action="view"):
        return super().app(user, app_id, self.permission if action == "operate" else action)


def save_outcome(tx, user, doc, changes, action, permission):
    tx.records = OutcomeRecords(tx.records, permission)
    return tx.save(user, doc, changes, action=action)


def install(app, current_user):
    skills = app.state.skills
    router = APIRouter(prefix="/api/v1/skills", route_class=SkillRoute)
    with skills.store._lock, skills.store._db as db:
        db.execute("""CREATE TABLE IF NOT EXISTS skill_votes (
            skill_id TEXT NOT NULL, user_id TEXT NOT NULL, useful INTEGER NOT NULL,
            PRIMARY KEY(skill_id, user_id))""")

    @router.post("/{sid}/publish")
    def publish(sid: str, body: dict, user=Depends(current_user)):
        return set_share(skills, user, sid, body.get("share"), "skill.publish")

    @router.post("/{sid}/share")
    def share(sid: str, body: dict, user=Depends(current_user)):
        return set_share(skills, user, sid, body, "skill.share")

    @router.post("/{sid}/review")
    def review(sid: str, body: dict, user=Depends(current_user)):
        item, _ = decision(skills, user, sid, body)
        return {"item": item}

    @router.post("/{sid}/rate")
    def rate(sid: str, body: dict, user=Depends(current_user)):
        useful = body.get("useful")
        if not isinstance(useful, bool):
            invalid("有用评价须为布尔值")
        with transaction(skills) as tx:
            doc = tx.load(user, sid)
            if doc["data"]["status"] != "published":
                invalid("只能评价已发布技能")
            db = tx.store._db
            db.execute("""INSERT INTO skill_votes VALUES (?,?,?) ON CONFLICT(skill_id,user_id)
                          DO UPDATE SET useful=excluded.useful""", (sid, user.id, useful))
            count, positive = db.execute("SELECT count(*), sum(useful) FROM skill_votes WHERE skill_id=?", (sid,)).fetchone()
            item = save_outcome(tx, user, doc, {"ratingN": count, "usefulRate": round(100 * positive / count, 1),
                                               "rating": round(3 + 2 * positive / count, 1)}, "skill.rate", "view")
            return {"item": item}

    app.include_router(router)

    def queue(user=Depends(current_user)):
        result = list_pending(app.state.platform.data, user)
        if can_review(skills, user):
            result["items"].extend(list_pending(skills.records, user)["items"])
            result["items"].sort(key=lambda item: item["createdAt"], reverse=True)
        return result

    replace_core_route(app, "/api/v1/reviews", "GET", queue, sdk_review_list)

    def skill_for_review(rid):
        with skills.store._lock:
            return skills.store._db.execute("SELECT record_id FROM v1_reviews WHERE id=?", (rid,)).fetchone()

    async def other_review(request):
        return skill_for_review(request.path_params["rid"]) is None

    def inbox_decision(rid: str, body: dict, user=Depends(current_user)):
        try:
            if type(body.get("version")) is not int or body["version"] < 1:
                invalid("请提供有效的审核版本")
            _, record = decision(skills, user, skill_for_review(rid)[0], body, rid)
        except SkillError as exc:
            return JSONResponse({"error": exc.error}, status_code=exc.status)
        item = review_view(record)
        item["decision"] = {**record["decision"], "decision": body["decision"]}
        return {"item": item}

    replace_core_route(app, "/api/v1/reviews/{rid}/decisions", "POST", inbox_decision, other_review)

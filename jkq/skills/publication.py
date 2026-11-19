"""技能发布、审签与评分，共用 CRUD 的技能库和 core 版本审签。"""
import json
import sqlite3
from contextlib import contextmanager
from copy import copy
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from jkq.jobs_api import replace_core_route
from jkq.reviews_api import list_pending, review_view, sdk_review_list

from .api import SkillCatalog, SkillRoute
from .spec import CONTENT, SkillError, invalid
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
        # 与 CRUD 统一先持技能库锁，再申请 SQLite 写锁。
        with skills.store._lock:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield scoped
                db.commit()
            finally:
                if db.in_transaction:
                    db.rollback()
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
    actions = skills.platform.rbac.actions(user, "skills")
    return bool({"admin", "leader"}.intersection(user.roles)) and {"view", "approve"} <= actions


def submit_review(skills, user, sid, version, name):
    review = skills.records.submit_review(user, {"appId": "skills", "recordId": sid, "version": version})
    review.update(type="skill", ref=sid, app="skills", title="技能上架申请：" + name)
    skills.records._write_review(skills.store._db, review)
    return {**review, "reviewId": review["id"]}


class PublishedSkills(SkillCatalog):
    def __init__(self, catalog):
        self.platform = catalog.platform
        self.store = catalog.store
        self.records = catalog.records

    def approvals(self, doc):
        # 从审核目标读取冻结快照。切换为非全区分享会结束此前的全区发布。
        with self.store._lock:
            rows = self.store._db.execute("""
                SELECT v.document FROM v1_reviews AS r
                JOIN v1_versions AS v ON v.record_id = r.record_id AND v.version = r.version
                WHERE r.record_id = ? AND r.version <= ?
                  AND json_extract(r.document, '$.type') = 'skill'
                  AND json_extract(r.document, '$.status') = 'confirmed'
                  AND json_extract(v.document, '$.data.share.scope') = 'zone'
                  AND r.version > COALESCE((
                      SELECT MAX(version) FROM v1_versions
                      WHERE record_id = r.record_id AND version <= ?
                        AND json_extract(document, '$.data.share.scope') <> 'zone'
                  ), 0)
                ORDER BY r.version
            """, (doc["id"], doc["version"], doc["version"])).fetchall()
        records = (json.loads(raw) for (raw,) in rows)
        return {record["data"]["version"]: record for record in records}

    def manages_zone(self, user, item):
        return user.id == item["authorId"] or "admin" in self.platform.rbac.actions(user, "skills")

    def zone_access(self, user, doc):
        item = doc["data"]
        actions = self.platform.rbac.actions(user, "skills")
        manager = self.manages_zone(user, item)
        public = False
        if item["status"] == "published":
            target = self.approvals(doc).get(item["version"])
            public = target is not None and all(item[key] == target["data"][key] for key in (*CONTENT, "share"))
        editable = "operate" in actions and (manager or (public and item["share"]["perm"] == "edit"))
        return public, manager, editable

    def pending_reviews(self, user, sid=None):
        if not can_review(self, user):
            return []
        with self.store._lock:
            rows = self.store._db.execute("""
                SELECT r.document, v.document FROM v1_reviews AS r
                JOIN v1_records AS s ON s.id = r.record_id AND s.latest = r.version
                JOIN v1_versions AS v ON v.record_id = r.record_id AND v.version = r.version
                JOIN v1_states AS state ON state.record_id = r.record_id AND state.version = r.version
                WHERE s.app = 'skills' AND state.status = 'pending'
                  AND json_extract(r.document, '$.status') = 'pending'
                  AND json_extract(r.document, '$.type') = 'skill'
                  AND json_extract(v.document, '$.data.status') = 'in_review'
                  AND json_extract(v.document, '$.data.share.scope') = 'zone'
                  AND json_extract(v.document, '$.data.deleted') = 0
                  AND (? IS NULL OR s.id = ?)
                ORDER BY r.rowid DESC
            """, (sid, sid)).fetchall()
        return [(json.loads(review), json.loads(doc)) for review, doc in rows]

    def listed(self, user, doc, *, review):
        item = doc["data"]
        if item["share"]["scope"] != "zone":
            return super().listed(user, doc, review=review)
        if user.id == item["authorId"]:
            return True
        public, _, _ = self.zone_access(user, doc)
        return public

    def list_items(self, user, *, mine, review):
        if not review:
            return super().list_items(user, mine=mine, review=False)
        self.records.app(user, "skills")
        items = []
        for pending, doc in self.pending_reviews(user):
            item = self.view(user, doc, history=False)
            if not mine or item["mine"]:
                items.append({**item, "contentVersion": item["version"], "reviewId": pending["id"],
                              "version": pending["version"]})
        return items

    def load(self, user, sid, *, edit=False, deleted=False, review_target=False):
        self.records.app(user, "skills", "operate" if edit else "view")
        doc = self.records.get_record(user, "skills", sid)
        item = doc["data"]
        if item["deleted"] and not deleted:
            raise SkillError(404, "NOT_FOUND", "技能不存在")
        if item["share"]["scope"] == "zone":
            public, manager, editable = self.zone_access(user, doc)
            visible = public or manager or (review_target and any(
                review["version"] == doc["version"] for review, _ in self.pending_reviews(user, sid)
            ))
        else:
            visible, editable = self.access(user, item)
        if not visible or (edit and not editable):
            raise SkillError(403, "FORBIDDEN", "没有该技能的访问权限", app="skills", need="edit" if edit else "view")
        return doc

    def history(self, user, doc):
        item = doc["data"]
        if item["share"]["scope"] != "zone" or self.manages_zone(user, item):
            return super().history(user, doc)
        versions = {}
        for version, record in self.approvals(doc).items():
            item = record["data"]
            at = datetime.fromtimestamp(record["createdAt"], timezone(timedelta(hours=8)))
            versions[version] = {"v": version, "by": record["submitter"], "at": at.isoformat(),
                                 "note": item["note"], **{key: item[key] for key in CONTENT}}
        return versions

    def view(self, user, doc, *, history=True):
        item = super().view(user, doc, history=history)
        if item["share"]["scope"] == "zone":
            _, _, item["canEdit"] = self.zone_access(user, doc)
        return item

    def revise(self, user, sid, body, restore=False):
        with transaction(self) as tx:
            return SkillCatalog.revise(tx, user, sid, body, restore)

    def save(self, user, doc, changes, *, action="skill.update"):
        pending = False
        if doc["data"]["share"]["scope"] == "zone":
            if action in ("skill.update", "skill.restore"):
                pending = bool(self.approvals(doc))
                changes = {**changes, "status": "in_review" if pending else "draft", "reviewNote": ""}
            elif action == "skill.delete" and doc["data"]["status"] == "in_review":
                changes = {**changes, "status": "draft"}
        item = super().save(user, doc, changes, action=action)
        if pending:
            submit_review(self, user, doc["id"], doc["version"] + 1, item["name"])
        return item


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
        review = submit_review(tx, user, sid, doc["version"] + 1, item["name"]) if pending else None
        return {"item": item, "review": review}


def decision(skills, user, sid, body, rid=None):
    with transaction(skills) as tx:
        doc = tx.records.get_record(user, "skills", sid)
        if doc["data"]["authorId"] == user.id:
            raise SkillError(409, "SELF_REVIEW", "作者不能审核自己的技能")
        if not can_review(skills, user):
            raise SkillError(403, "FORBIDDEN", "只有管理员或审签领导可审核")
        choice = body.get("decision")
        reason = body.get("reason", "")
        if choice not in ("approve", "reject") or not isinstance(reason, str) or (choice == "reject" and not reason.strip()):
            invalid("请选择审核结论，驳回时须填写原因")
        review_id, version = body.get("reviewId", rid), body.get("version")
        if not isinstance(review_id, str) or not review_id.strip() or type(version) is not int or version < 1:
            invalid("请提供待审标识和有效的审核版本")
        if (rid is not None and review_id != rid) or not any(
            item["id"] == review_id and item["version"] == version
            for item, _ in tx.pending_reviews(user, sid)
        ):
            raise SkillError(409, "STALE_VERSION", "待审版本已变化，请重新提交或刷新")
        review = tx.records.decide_review(user, review_id, {"version": version,
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
    skills = app.state.skills = PublishedSkills(app.state.skills)
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
        result["items"].extend({**review_view(review), "reviewId": review["id"], "project": doc["project"]}
                               for review, doc in skills.pending_reviews(user))
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
            _, record = decision(skills, user, skill_for_review(rid)[0], body, rid)
        except SkillError as exc:
            return JSONResponse({"error": exc.error}, status_code=exc.status)
        item = review_view(record)
        item["decision"] = {**record["decision"], "decision": body["decision"]}
        return {"item": item}

    replace_core_route(app, "/api/v1/reviews/{rid}/decisions", "POST", inbox_decision, other_review)

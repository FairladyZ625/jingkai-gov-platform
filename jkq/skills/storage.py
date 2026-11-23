"""技能级授权在当前版本判定，内容版本由 core DataService 持久化。"""
import json
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from haiknow_core.data import DataService
from haiknow_core.store import Store

from .spec import CONTENT, SkillError, content_fields, invalid, next_version, validate_spec


class SkillStore(Store):
    """技能记录与标准审计使用同一 SQLite 事务，记录表仍留在专用库。"""

    action = ContextVar("skill_audit_action", default="skill.update")

    def __init__(self, platform_store):
        super().__init__(platform_store.data_dir / "skills")
        self._db.execute("ATTACH DATABASE ? AS platform", (str(platform_store.data_dir / "platform.db"),))

    def audit(self, app_id, user_id, action, detail, *, connection=None):
        super().audit(app_id, user_id, action, detail, connection=connection)
        if connection is not None and action == "v1.record.save":
            connection.execute(
                "INSERT INTO platform.audit(ts, app_id, user_id, action, detail) "
                "SELECT ts, app_id, user_id, ?, detail FROM main.audit WHERE id=last_insert_rowid()",
                (self.action.get(),),
            )


class SkillWorkspace:
    # §3.7 是实例级资源。此库专用于技能，通用项目记录 API 无权访问。
    def require(self, user, project):
        if project != "jkq":
            raise ValueError("技能工作区无效")
        return {"company": "jkq", "products": []}


class SkillRecords(DataService):
    def app(self, user, app_id, action="view"):
        actions = self.rbac.actions(user, "skills")
        if app_id != "skills" or "view" not in actions or action not in actions:
            raise SkillError(403, "FORBIDDEN", "缺少技能中心权限", app="skills", need=action)


class Skills:
    def __init__(self, platform):
        self.platform = platform
        self.store = SkillStore(platform.store)
        self.records = SkillRecords(self.store, platform.rbac, SkillWorkspace(), {})

    def access(self, user, item):
        actions = self.platform.rbac.actions(user, "skills")
        owner = item["authorId"] == user.id
        manager = owner or "admin" in actions
        share = item["share"]
        shared = False
        if item["status"] == "published":
            scope = share["scope"]
            if scope == "dept":
                departments = self.platform.directory.departments_of
                shared = bool(departments(user.id) & departments(item["authorId"]))
            else:
                shared = scope == "zone" or (scope == "people" and user.id in share["people"])
        review = item["status"] == "in_review" and "approve" in actions
        edit = "operate" in actions and (manager or (shared and share["perm"] == "edit"))
        return manager or shared or review, edit

    def load(self, user, sid, *, edit=False, deleted=False, review_target=False):
        self.records.app(user, "skills", "operate" if edit else "view")
        doc = self.records.get_record(user, "skills", sid)
        item = doc["data"]
        if item["deleted"] and not deleted:
            raise SkillError(404, "NOT_FOUND", "技能不存在")
        visible, editable = self.access(user, item)
        if not visible or (edit and not editable):
            raise SkillError(403, "FORBIDDEN", "没有该技能的访问权限", app="skills", need="edit" if edit else "view")
        return doc

    def set_deleted(self, user, sid, deleted):
        doc = self.load(user, sid, edit=True, deleted=not deleted)
        item = doc["data"]
        if item["authorId"] != user.id and "admin" not in self.platform.rbac.actions(user, "skills"):
            raise SkillError(403, "FORBIDDEN", "只有所有者或技能管理员可删除或撤销删除")
        if item["deleted"] == deleted:
            return self.view(user, doc)
        action = "skill.delete" if deleted else "skill.restore_deleted"
        return self.save(user, doc, {"deleted": deleted}, action=action)

    def history(self, user, doc):
        # 一个内容版本的删除、撤销和分享可产生多个存储修订，只展示内容快照。
        with self.store._lock:
            rows = self.store._db.execute(
                "SELECT document FROM v1_versions WHERE record_id=? AND version<=? ORDER BY version",
                (doc["id"], doc["version"]),
            ).fetchall()
        versions = {}
        for (raw,) in rows:
            record = json.loads(raw)
            item = record["data"]
            v = item["version"]
            if v not in versions:
                at = datetime.fromtimestamp(record["createdAt"], timezone(timedelta(hours=8)))
                versions[v] = {"v": v, "by": record["submitter"], "at": at.isoformat(),
                               "note": item["note"], **{k: item[k] for k in CONTENT}}
        return versions

    def view(self, user, doc, *, history=True):
        item = doc["data"]
        return {**{k: v for k, v in item.items() if k != "deleted"},
                "id": doc["id"], "mine": item["authorId"] == user.id,
                "canEdit": self.access(user, item)[1],
                "versions": list(self.history(user, doc).values()) if history else []}

    def create(self, user, body, source=None):
        self.records.app(user, "skills", "operate")
        fields = content_fields(body)
        profile = self.platform.directory.profile(user)
        item = {"name": "未命名技能", "summary": "", "icon": "技", "base": "kb",
                "spec": validate_spec({}), **fields, "author": user.name, "authorId": user.id,
                "dept": "、".join(d["name"] for d in profile["departments"]),
                "kind": "skill", "version": "0.1.0", "status": "draft", "deleted": False,
                "share": {"scope": "private", "perm": "use", "people": []},
                "uses": 0, "rating": 0, "ratingN": 0, "forks": 0,
                "forkOf": source, "note": "复制改编" if source else "新建草稿"}
        doc = self.write(user, {"project": "jkq", "type": "skill", "data": item},
                         "skill.fork" if source else "skill.create")
        return self.view(user, doc)

    def write(self, user, body, action, sid=None):
        token = self.store.action.set(action)
        try:
            return self.records.save_record(user, "skills", body, sid)
        finally:
            self.store.action.reset(token)

    def save(self, user, doc, changes, *, action="skill.update"):
        # baseVersion 同时保护内容和授权快照。并发更新冲突由 core 返回。
        updated = self.write(user, {
            "baseVersion": doc["version"], "data": {**doc["data"], **changes},
        }, action, doc["id"])
        return self.view(user, updated)

    def revise(self, user, sid, body, restore=False):
        doc = self.load(user, sid, edit=True)
        if restore:
            version = body.get("v")
            if not isinstance(version, str):
                invalid("请选择要恢复的版本")
            snapshot = self.history(user, doc).get(version)
            if snapshot is None:
                raise SkillError(404, "NOT_FOUND", "技能版本不存在")
            fields = content_fields(snapshot)
            note = f"恢复版本 {version}"
        else:
            fields = content_fields(body)
            if not fields:
                invalid("请提供要修改的内容")
            note = body.get("note", "修改内容")
            if not isinstance(note, str):
                invalid("版本说明应为文本")
        return self.save(user, doc, {**fields, "version": next_version(doc["data"]["version"]), "note": note},
                         action="skill.restore" if restore else "skill.update")

"""知识库文档存储与 HTTP 投影。删除期限从第一次删除时开始。"""
import json
import time
from collections import Counter
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .seed import documents
from .spaces import NAMES, spaces, visible_spaces

RETENTION = 30 * 24 * 3600


class KbError(Exception):
    def __init__(self, status, code, message, **details):
        self.status = status
        self.error = dict(code=code, message=message, details=details)


def missing():
    return KbError(404, "NOT_FOUND", "资料不存在")


class Patch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default=None, min_length=1)
    tags: list[str] = Field(default=None)
    expire: str = Field(default=None)
    space: Literal["policy", "template", "minutes", "rules", "enterprise"] = Field(default=None)


class Documents:
    def __init__(self, platform):
        self.store = platform.store
        self.rbac = platform.rbac
        with self.store._lock, self.store._db as db:
            self.store.begin_write()
            db.execute("""create table if not exists jkq_kb_docs
                       (id text primary key, doc text not null, deleted real)""")
            db.execute("""create table if not exists jkq_kb_history
                       (id text, version integer, doc text not null, primary key(id, version))""")
            db.executemany("insert into jkq_kb_docs(id,doc) values(?,?) on conflict(id) do nothing",
                           ((d["id"], json.dumps(d, ensure_ascii=False)) for d in documents()))

    def require(self, user, action):
        if action not in self.rbac.actions(user, "kb"):
            self.store.audit("kb", user.id, "denied", {"need": action})
            raise KbError(403, "FORBIDDEN", "没有知识库操作权限", app="kb", need=action)

    def candidates(self, user):
        """#26 检索候选集，集中处理空间权限和软删除。"""
        self.require(user, "view")
        allowed = visible_spaces(user)
        with self.store._lock:
            rows = self.store._db.execute(
                """select doc from jkq_kb_docs where deleted is null
                   and json_extract(doc,'$.space') in (select value from json_each(?)) order by id""",
                (json.dumps(allowed),))
            return [json.loads(raw) for (raw,) in rows]

    def _load(self, db, user, identity, *, restoring=False):
        row = db.execute("select doc,deleted from jkq_kb_docs where id=?", (identity,)).fetchone()
        if not row:
            raise missing()
        doc, deleted = json.loads(row[0]), row[1]
        if doc["space"] not in visible_spaces(user):
            raise missing()
        if deleted is not None and (not restoring or time.time() >= deleted + RETENTION):
            raise missing()
        return doc

    def detail(self, user, identity, version=None):
        self.require(user, "view")
        with self.store._lock:
            db = self.store._db
            current = self._load(db, user, identity)
            doc = current
            if version is not None and version != current["version"]:
                row = db.execute("select doc from jkq_kb_history where id=? and version=?",
                                 (identity, version)).fetchone()
                if not row:
                    raise missing()
                doc = json.loads(row[0])
                if doc["space"] not in visible_spaces(user):
                    raise missing()
            revised = doc["version"] != current["version"]
            text = doc["text"]
            chunks = [dict(i=0, start=0, end=len(text), head=doc["title"])] if text else []
            return dict(**summary(doc), text=text, chunkList=chunks,
                        versions=list(range(1, current["version"] + 1)),
                        sourceState="来源已修订" if revised else doc["status"])

    def change(self, user, identity, action, values=None):
        self.require(user, "operate")
        with self.store._lock, self.store._db as db:
            self.store.begin_write()
            doc = self._load(db, user, identity, restoring=action == "restore")
            if action in ("patch", "replace"):
                if "space" in values and values["space"] not in visible_spaces(user):
                    raise KbError(403, "FORBIDDEN", "不可写入该空间", app="kb", need="operate")
                if action == "replace":
                    db.execute("insert into jkq_kb_history values(?,?,?)",
                               (identity, doc["version"], json.dumps(doc, ensure_ascii=False)))
                    doc["version"] += 1
                doc.update(values)
                db.execute("update jkq_kb_docs set doc=? where id=?",
                           (json.dumps(doc, ensure_ascii=False), identity))
            else:
                db.execute("update jkq_kb_docs set deleted=? where id=?",
                           (time.time() if action == "delete" else None, identity))
            self.store.audit("kb", user.id, action, {"id": identity}, connection=db)
            return doc

    def replace_text(self, user, identity, text):
        """#25 确认新版入库后调用，保留旧版引文。"""
        return self.change(user, identity, "replace", {"text": text})


def summary(doc):
    result = {k: v for k, v in doc.items() if k != "text"}
    return dict(result, spaceName=NAMES[doc["space"]], chunks=int(bool(doc["text"])),
                citationId=f'{doc["id"]}@v{doc["version"]}')


def install(app, platform, current_user):
    service = Documents(platform)
    platform.kb = service
    router = APIRouter(prefix="/api/v1/kb")
    session = Depends(current_user)

    @app.exception_handler(KbError)
    async def kb_error(request, exc):
        return JSONResponse({"error": exc.error}, status_code=exc.status)

    @router.get("/spaces")
    def list_spaces(user=session):
        return {"items": spaces(user, service.candidates(user))}

    @router.get("/libraries")
    def libraries(user=session):
        return {"items": [dict(id=s["id"], name=s["name"], icon=s["icon"], files=s["count"])
                          for s in list_spaces(user)["items"]]}

    @router.get("/docs")
    def listing(space: str = "", status: str = "", kind: str = "", limit: int = Query(50, ge=1),
                offset: int = Query(0, ge=0), user=session):
        filters = {"space": space, "status": status, "kind": kind}
        docs = [d for d in service.candidates(user) if all(not v or d[k] == v for k, v in filters.items())]
        facets = {k: [dict(k=value, n=count) for value, count in
                      Counter(d[k] for d in docs if d[k]).most_common()] for k in filters}
        return dict(hits=[summary(d) for d in docs[offset:offset + limit]], total=len(docs), facets=facets)

    @router.get("/docs/{identity}")
    def detail(identity: str, version: Optional[int] = None, user=session):
        return {"item": service.detail(user, identity, version)}

    @router.get("/files/{identity}")
    def file(identity: str, version: Optional[int] = None, user=session):
        # 对话卡片只传一个 ID，保存 citationId 即可固定引用的版本。
        doc_id, separator, number = identity.rpartition("@v")
        if separator and number.isascii() and number.isdecimal():
            if len(number) > 9 or (version is not None and version != int(number)):
                raise missing()
            doc = service.detail(user, doc_id, int(number))
        else:
            doc = service.detail(user, identity, version)
        return {"item": dict(id=identity, name=doc["title"], no=doc["source"]["docNo"],
                             text=doc["text"], state=doc["sourceState"], url=doc["source"]["url"])}

    @router.patch("/docs/{identity}")
    def patch(identity: str, body: Patch, user=session):
        return {"item": summary(service.change(user, identity, "patch", body.model_dump(exclude_unset=True)))}

    @router.delete("/docs/{identity}")
    def delete(identity: str, user=session):
        doc = service.change(user, identity, "delete")
        return dict(ok=True, item=dict(id=identity, title=doc["title"]))

    @router.post("/docs/{identity}/restore")
    def restore(identity: str, user=session):
        service.change(user, identity, "restore")
        return {"ok": True}

    app.include_router(router)

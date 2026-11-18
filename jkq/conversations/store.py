"""经开区会话扩展。会话、消息和审计共用平台数据库与写事务。"""
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from haiknow_core.migrations import statements
from haiknow_core.store import Store


SCHEMA = """
create table if not exists jkq_conversations (
    id text primary key, owner text not null, title text not null, app text,
    updated text not null, panel text, deleted integer not null default 0
);
create index if not exists jkq_conversations_history
    on jkq_conversations(owner, deleted, updated desc, id desc);
create table if not exists jkq_messages (
    seq integer primary key, conversation_id text not null references jkq_conversations(id),
    document text not null
);
create index if not exists jkq_messages_order on jkq_messages(conversation_id, seq);
"""
FIELDS = "id, title, app, updated, panel"
BEIJING = timezone(timedelta(hours=8))


class ConversationNotFound(LookupError):
    pass


def now():
    return datetime.now(BEIJING).isoformat(timespec="microseconds")


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def item(row):
    cid, title, app, updated, panel = row
    return dict(id=cid, title=title, app=app, updated=updated, panel=json.loads(panel))


class ConversationStore:
    def __init__(self, platform_store: Store):
        self.platform = platform_store
        self.db = platform_store._db
        with self.transaction(write=True):
            for sql in statements(SCHEMA):
                self.db.execute(sql)

    @contextmanager
    def transaction(self, *, write=False):
        with self.platform._lock, self.db:
            if write:
                self.platform.begin_write()
            else:
                self.db.execute("begin")
            yield

    def _owned(self, owner, cid, deleted=False):
        row = self.db.execute(
            f"select {FIELDS} from jkq_conversations where id=? and owner=? and deleted=?",
            (cid, owner, deleted),
        ).fetchone()
        if row is None:
            raise ConversationNotFound()
        return item(row)

    def _audit(self, owner, cid, action, **detail):
        self.platform.audit("conversations", owner, action, {"id": cid, **detail}, connection=self.db)

    def create(self, owner, title="新对话", app=None, panel=None):
        cid = f"C-{uuid4().hex}"
        with self.transaction(write=True):
            self.db.execute(
                "insert into jkq_conversations(id, owner, title, app, updated, panel) values(?,?,?,?,?,?)",
                (cid, owner, title, app, now(), encode(panel)),
            )
            self._audit(owner, cid, "conversation.create")
            return self._owned(owner, cid)

    def history(self, owner, limit=50, offset=0):
        active = "from jkq_conversations where owner=? and deleted=0"
        with self.transaction():
            total = self.db.execute(f"select count(*) {active}", (owner,)).fetchone()[0]
            rows = self.db.execute(
                f"select {FIELDS} {active} order by updated desc, id desc limit ? offset ?",
                (owner, limit, offset),
            )
            return {"items": [item(row) for row in rows], "total": total}

    def detail(self, owner, cid):
        with self.transaction():
            conversation = self._owned(owner, cid)
            rows = self.db.execute(
                "select document from jkq_messages where conversation_id=? order by seq", (cid,)
            )
            return {"item": conversation, "messages": [json.loads(doc) for (doc,) in rows]}

    def set_panel(self, owner, cid, panel):
        with self.transaction(write=True):
            self._owned(owner, cid)
            self.db.execute("update jkq_conversations set panel=?, updated=? where id=?",
                            (encode(panel), now(), cid))
            self._audit(owner, cid, "conversation.panel")
            return self._owned(owner, cid)

    def set_deleted(self, owner, cid, *, deleted):
        with self.transaction(write=True):
            self._owned(owner, cid, deleted=not deleted)
            self.db.execute("update jkq_conversations set deleted=?, updated=? where id=?",
                            (deleted, now(), cid))
            self._audit(owner, cid, "conversation.delete" if deleted else "conversation.restore")
            return self._owned(owner, cid, deleted=deleted)

    def append_message(self, owner, cid, *, role, content, cards=None, citations=None,
                       model=None, toolCalls=None, **metadata):
        """供 #22 编排写入已生成的消息；消息 ID 和时间由服务端分配。"""
        if role not in ("user", "assistant") or not isinstance(content, str):
            raise ValueError("消息角色或正文无效")
        with self.transaction(write=True):
            self._owned(owner, cid)
            at = now()
            msg = dict(metadata, id=f"M-{uuid4().hex}", at=at, role=role, content=content,
                       cards=cards or [], citations=citations or [], model=model, toolCalls=toolCalls or [])
            self.db.execute("insert into jkq_messages(conversation_id, document) values(?,?)",
                            (cid, encode(msg)))
            self.db.execute("update jkq_conversations set updated=? where id=?", (at, cid))
            self._audit(owner, cid, "message.append", messageId=msg["id"], model=model)
            return msg

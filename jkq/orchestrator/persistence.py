"""在 T20 会话事务中原子写入同一次请求的两条消息。"""

import json
from dataclasses import dataclass
from uuid import uuid4

from jkq.conversations.store import ConversationStore, encode, now


@dataclass(frozen=True)
class PendingTurn:
    user: dict
    assistant: dict
    assistant_seq: int
    history: list[dict]


def _new_message(role: str, content: str, at: str, **metadata) -> dict:
    return dict(id=f"M-{uuid4().hex}", role=role, content=content, at=at, model=None,
                cards=[], citations=[], toolCalls=[], **metadata)


def start_turn(store: ConversationStore, owner: str, cid: str, text: str, files: list[dict]) -> PendingTurn:
    with store.transaction(write=True):
        store._owned(owner, cid)
        rows = store.db.execute(
            "select document from jkq_messages where conversation_id=? order by seq desc limit 20",
            (cid,),
        ).fetchall()
        history = [json.loads(document) for (document,) in reversed(rows)]
        at = now()
        user = _new_message("user", text, at, files=files)
        assistant = _new_message("assistant", "", at, incomplete=True)
        for message in (user, assistant):
            inserted = store.db.execute(
                "insert into jkq_messages(conversation_id, document) values (?,?)",
                (cid, encode(message)),
            )
            store._audit(owner, cid, "message.append", messageId=message["id"], model=None)
        store.db.execute("update jkq_conversations set updated=? where id=?", (at, cid))
        return PendingTurn(user, assistant, inserted.lastrowid, history)


def finish_turn(store: ConversationStore, owner: str, cid: str, turn: PendingTurn, fields: dict) -> dict:
    """补全当前请求的占位回复，完整正文、卡片和引用一次提交。"""
    with store.transaction(write=True):
        store._owned(owner, cid)
        message = {**turn.assistant, **fields, "incomplete": False}
        changed = store.db.execute(
            """update jkq_messages set document=?
               where seq=? and conversation_id=? and json_extract(document, '$.id')=?
               and json_extract(document, '$.incomplete')=1""",
            (encode(message), turn.assistant_seq, cid, message["id"]),
        )
        if changed.rowcount != 1:
            raise RuntimeError("待完成的会话回复不存在")
        store.db.execute("update jkq_conversations set updated=? where id=?", (now(), cid))
        store._audit(owner, cid, "message.complete", messageId=message["id"], model=message["model"])
        return {"conversation": store._owned(owner, cid), "user": turn.user, "reply": message}

"""在 T20 会话事务中原子写入同一次请求的两条消息。"""

import json
from dataclasses import dataclass
from uuid import uuid4

from jkq.conversations.store import ConversationNotFound, ConversationStore, encode, now

from .classification import strictest


@dataclass(frozen=True)
class PendingTurn:
    user: dict
    assistant: dict
    assistant_seq: int
    history: list[dict]


def _new_message(role: str, content: str, at: str, **metadata) -> dict:
    return dict(id=f"M-{uuid4().hex}", role=role, content=content, at=at, model=None,
                cards=[], citations=[], toolCalls=[], **metadata)


def start_turn(
    store: ConversationStore, owner: str, cid: str, text: str, files: list[dict],
    *, app: str | None = None, app_classes: dict | None = None, classification: str | None = None,
    mode: str = "general", enterprise_id: str | None = None,
) -> PendingTurn:
    with store.transaction(write=True):
        conversation = store._owned(owner, cid)
        rows = store.db.execute(
            "select document from jkq_messages where conversation_id=? order by seq desc limit 20",
            (cid,),
        ).fetchall()
        history = [json.loads(document) for (document,) in reversed(rows)]
        app_classes = app_classes or {}
        apps = (app_classes.get(app_id) for app_id in {app, conversation["app"]} if app_id is not None)
        prior = (
            "confidential" if message.get("toolCalls") or message.get("files") else message.get("classification")
            for message in history if not message.get("incomplete")
        )
        # 附件引用由客户端提交，未从可信附件存储核验前按机密处理。
        effective = strictest(classification, *apps, *prior, *(["confidential"] if files else []))
        # 只保留连续同岗位、同企业的会话段；切走再切回也不会复活旧企业上下文。
        for index in range(len(history) - 1, -1, -1):
            previous = history[index]
            if (previous.get("mode", "general"), previous.get("enterpriseId")) != (mode, enterprise_id):
                history = history[index + 1:]
                break
        at = now()
        context = {"mode": mode, "enterpriseId": enterprise_id}
        user = _new_message("user", text, at, files=files, classification=effective, **context)
        assistant = _new_message("assistant", "", at, incomplete=True, classification=effective, **context)
        for message in (user, assistant):
            inserted = store.db.execute(
                "insert into jkq_messages(conversation_id, document) values (?,?)",
                (cid, encode(message)),
            )
            store._audit(owner, cid, "message.append", messageId=message["id"], model=None)
        store.db.execute("update jkq_conversations set updated=? where id=?", (at, cid))
        return PendingTurn(user, assistant, inserted.lastrowid, history)


def finish_turn(store: ConversationStore, owner: str, cid: str, turn: PendingTurn, fields: dict) -> dict:
    """提交待完成回复和审计后，返回与历史一致的完整消息。"""
    message = {**turn.assistant, **fields, "incomplete": False}
    if message["toolCalls"]:
        message["classification"] = "confidential"
    with store.transaction(write=True):
        store._owned(owner, cid)
        changed = store.db.execute(
            """update jkq_messages set document=?
               where seq=? and conversation_id=? and json_extract(document, '$.id')=?
               and json_extract(document, '$.incomplete')=1""",
            (encode(message), turn.assistant_seq, cid, message["id"]),
        )
        if changed.rowcount != 1:
            raise ConversationNotFound()
        store.db.execute("update jkq_conversations set updated=max(updated, ?) where id=?",
                         (now(), cid))
        store._audit(owner, cid, "message.complete", messageId=message["id"], model=message["model"])
        conversation = store._owned(owner, cid)
    return {"conversation": conversation, "user": turn.user, "reply": message}

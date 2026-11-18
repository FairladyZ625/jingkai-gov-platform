"""core 拥有企业 ID、项目授权及版本，私库只保存不可变原值快照。"""
import fcntl
import json
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from haiknow_sdk import DataError

from .company import Duplicate, public, validate

PROJECT = "jkq"
TYPE = "enterprise.company"
BEIJING = timezone(timedelta(hours=8))


def documents(ctx):
    return ctx.records.list(project=PROJECT, type=TYPE)["items"]


def document(ctx, company_id, version=None):
    doc = ctx.records.get(company_id, version)
    if doc["project"] != PROJECT or doc["type"] != TYPE:
        raise DataError("not_found", "企业不存在")
    return doc


def item(doc):
    return {**doc["data"]["item"], "id": doc["id"]}


@contextmanager
def snapshots(*, writing):
    path = Path(os.environ["JKQ_ENTERPRISE_PRIVATE_DB"])
    if not path.is_absolute() or path.resolve().is_relative_to(Path(__file__).resolve().parents[3]):
        raise RuntimeError("企业原值库须配置在仓库外的绝对路径")
    # 锁覆盖查重与 core 提交。私库先提交不可变快照，即使进程退出，
    # 已发布的 core 版本也总能找到对应原值，未发布快照不会被读取。
    if not writing:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            yield db
        return
    os.close(os.open(path, os.O_CREAT | os.O_RDWR, 0o600))
    with closing(os.fdopen(os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600), "r+b")) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with closing(sqlite3.connect(path)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS snapshots (ref TEXT PRIMARY KEY, body TEXT NOT NULL)")
            yield db


def original(db, doc):
    ref = doc["data"]["snapshot"]
    result = db.execute("SELECT body FROM snapshots WHERE ref=?", (ref,)).fetchone()
    if result is None:
        raise RuntimeError("企业原值快照缺失")
    return json.loads(result[0])


def write(ctx, db, fields, names, previous=None):
    old = original(db, previous) if previous else {}
    raw = validate({**old, **fields})
    key = raw["name"].strip().casefold()
    if key in names and names[key] != (previous["id"] if previous else None):
        raise Duplicate("企业名称重复")
    projected = public(raw)
    ref = uuid4().hex
    with db:
        db.execute("INSERT INTO snapshots VALUES (?, ?)", (ref, json.dumps(raw, ensure_ascii=False)))
    data = {"snapshot": ref, "item": projected}
    revision = {}
    if previous:
        before = previous["data"]["item"]
        keys = list(fields)
        single = len(keys) == 1
        data["change"] = {
            "at": datetime.now(BEIJING).isoformat(), "by": ctx.user.name, "source": "台账修改",
            "field": keys[0] if single else keys,
            "old": before.get(keys[0]) if single else {k: before.get(k) for k in keys},
            "new": projected[keys[0]] if single else {k: projected[k] for k in keys},
        }
        revision = {"id": previous["id"], "baseVersion": previous["version"]}
    doc = ctx.records.save(project=PROJECT, type=TYPE, data=data, **revision)
    names[key] = doc["id"]
    return item(doc)


def names_by_id(ctx):
    return {doc["data"]["item"]["name"].strip().casefold(): doc["id"] for doc in documents(ctx)}

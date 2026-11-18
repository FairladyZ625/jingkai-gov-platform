"""单文件 SQLite：留痕与按应用隔离的键值；文件按应用分目录存放。"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .migrations import migrate

class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(data_dir / "platform.db", check_same_thread=False)
        try:
            migrate(self._db, data_dir)
        except BaseException:
            self._db.close()
            raise

    def begin_write(self) -> None:
        """在已持锁的读-写入口显式开启写事务。

        sqlite3 默认只在第一条写语句前 BEGIN，前置条件/版本核对等 SELECT 不在事务内；
        BEGIN IMMEDIATE 让核对与后续写入同处一个事务，并对跨进程并发写加锁。
        已处于事务中（嵌套调用）时不重复开启。
        """
        if not self._db.in_transaction:
            self._db.execute('BEGIN IMMEDIATE')

    def app_enabled(self, app_id: str) -> bool:
        with self._lock:
            row = self._db.execute('select enabled from app_control where app_id=?', (app_id,)).fetchone()
        return bool(row[0]) if row else True

    def set_app_enabled(self, app_id: str, enabled: bool, user_id: str) -> None:
        with self._lock, self._db:
            self._db.execute('insert into app_control values (?,?) on conflict(app_id) do update set enabled=excluded.enabled',
                             (app_id, int(enabled)))
            self.audit(app_id, user_id, 'app.enable' if enabled else 'app.disable', {}, connection=self._db)

    # 留痕
    def audit(self, app_id: str, user_id: str, action: str, detail: dict, *, connection=None) -> None:
        """connection 仅供平台已持锁事务使用，让数据写入与留痕一起提交。"""
        if connection is None:
            with self._lock, self._db:
                self.audit(app_id, user_id, action, detail, connection=self._db)
            return
        connection.execute(
            "insert into audit(ts, app_id, user_id, action, detail) values (?,?,?,?,?)",
            (time.time(), app_id, user_id, action, json.dumps(detail, ensure_ascii=False)),
        )

    def audit_list(self, app_id: str | None = None, limit: int = 200) -> list[dict]:
        sql = "select ts, app_id, user_id, action, detail from audit"
        args: tuple = ()
        if app_id:
            sql += " where app_id = ?"
            args = (app_id,)
        sql += " order by id desc limit ?"
        with self._lock:
            rows = self._db.execute(sql, (*args, limit)).fetchall()
        return [
            {"ts": r[0], "app": r[1], "user": r[2], "action": r[3], "detail": json.loads(r[4])}
            for r in rows
        ]

    # 键值
    def kv_get(self, app_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._db.execute(
                "select value from kv where app_id=? and key=?", (app_id, key)
            ).fetchone()
        return json.loads(row[0]) if row else default

    def kv_put(self, app_id: str, key: str, value: Any) -> None:
        with self._lock, self._db:
            self._db.execute(
                "insert into kv(app_id, key, value, updated) values (?,?,?,?) "
                "on conflict(app_id, key) do update set value=excluded.value, updated=excluded.updated",
                (app_id, key, json.dumps(value, ensure_ascii=False), time.time()),
            )

    def kv_list(self, app_id: str, prefix: str = "") -> dict[str, Any]:
        with self._lock:
            rows = self._db.execute(
                "select key, value from kv where app_id=? and key like ? order by updated desc",
                (app_id, prefix.replace("%", r"\%") + "%"),
            ).fetchall()
        return {k: json.loads(v) for k, v in rows}


_SAFE = re.compile(r"[^\w.\-一-鿿]+")


class AppFiles:
    """应用只能读写 data/files/<app_id>/。"""

    def __init__(self, root: Path, app_id: str):
        self.dir = root / "files" / app_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, data: bytes) -> str:
        fid = f"{uuid.uuid4().hex[:12]}-{_SAFE.sub('_', Path(name).name)[:80]}"
        (self.dir / fid).write_bytes(data)
        return fid

    def read(self, file_id: str) -> bytes:
        p = (self.dir / file_id).resolve()
        if p.parent != self.dir.resolve() or not p.is_file():
            raise FileNotFoundError(file_id)
        return p.read_bytes()

    def list(self) -> list[dict]:
        return [
            {"id": p.name, "size": p.stat().st_size}
            for p in sorted(self.dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
            if p.is_file()
        ]


class AppKV:
    def __init__(self, store: Store, app_id: str):
        self._s, self._a = store, app_id

    def get(self, key: str, default: Any = None) -> Any:
        return self._s.kv_get(self._a, key, default)

    def put(self, key: str, value: Any) -> None:
        self._s.kv_put(self._a, key, value)

    def list(self, prefix: str = "") -> dict[str, Any]:
        return self._s.kv_list(self._a, prefix)

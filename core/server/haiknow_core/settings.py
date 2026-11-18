"""AI 配置与持久用量，使用平台数据库的独立表。"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from cryptography.fernet import Fernet

from .migrations import migrate


def load_settings_cipher(data_dir: Path) -> Fernet:
    """加载系统配置共用的主密钥；首次使用时创建。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    key_file = data_dir / 'ai-master.key'
    try:
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'wb') as f:
            f.write(Fernet.generate_key())
    return Fernet(key_file.read_bytes())


def encrypt_setting(cipher: Fernet, value: str) -> bytes:
    return cipher.encrypt(value.encode())


def decrypt_setting(cipher: Fernet, value: bytes) -> str:
    return cipher.decrypt(value).decode()


class AISettings:
    def __init__(self, data_dir: Path):
        self._cipher = load_settings_cipher(data_dir)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(data_dir / 'platform.db', check_same_thread=False, timeout=30)
        try:
            migrate(self._db, data_dir)
        except BaseException:
            self._db.close()
            raise

    def put_provider(self, ident, kind, base_url, api_key, models, enabled, allow_outbound=None):
        with self._lock, self._db:
            old = self._db.execute('select secret,allow_outbound from ai_provider where id=?', (ident,)).fetchone()
            secret = encrypt_setting(self._cipher, api_key) if api_key is not None else (old[0] if old else encrypt_setting(self._cipher, ''))
            limit = allow_outbound if allow_outbound is not None else (old[1] if old else None)
            self._db.execute('insert or replace into ai_provider(id,kind,base_url,secret,models,enabled,allow_outbound) values (?,?,?,?,?,?,?)',
                             (ident, kind, base_url.rstrip('/'), secret, json.dumps(models), int(enabled), limit))

    def provider(self, ident):
        with self._lock:
            row = self._db.execute('select id,kind,base_url,secret,models,enabled,allow_outbound from ai_provider where id=?', (ident,)).fetchone()
        if row is None:
            return None
        return dict(id=row[0], kind=row[1], base_url=row[2], api_key=decrypt_setting(self._cipher, row[3]), models=json.loads(row[4]), enabled=bool(row[5]), allow_outbound=row[6] or 'internal')

    def providers(self):
        with self._lock:
            rows = self._db.execute('select id,kind,base_url,models,enabled,length(secret),allow_outbound from ai_provider order by id').fetchall()
        return [dict(id=r[0], kind=r[1], base_url=r[2], models=json.loads(r[3]), enabled=bool(r[4]), api_key='********', allow_outbound=r[6] or 'internal') for r in rows]

    def delete_provider(self, ident):
        """删除服务商，密文列随行一起消失；引用检查在管理接口做。"""
        with self._lock, self._db:
            self._db.execute('delete from ai_provider where id=?', (ident,))

    def put_route(self, capability, provider, model, fallback_provider=None, fallback_model=None):
        with self._lock, self._db:
            self._db.execute('insert or replace into ai_route values (?,?,?,?,?)', (capability, provider, model, fallback_provider, fallback_model))

    def routes(self):
        with self._lock:
            rows = self._db.execute('select capability,provider,model,fallback_provider,fallback_model from ai_route order by capability').fetchall()
        return [dict(zip(('capability','provider','model','fallback_provider','fallback_model'), r)) for r in rows]

    def route(self, capability):
        return next((r for r in self.routes() if r['capability'] == capability), None)

    def delete_route(self, capability):
        with self._lock, self._db:
            self._db.execute('delete from ai_route where capability=?', (capability,))

    def put_quota(self, app_id, max_calls):
        with self._lock, self._db:
            self._db.execute('insert or replace into ai_quota values (?,?)', (app_id, max_calls))

    def quotas(self):
        with self._lock:
            return [dict(app_id=r[0], max_calls=r[1]) for r in self._db.execute('select app_id,max_calls from ai_quota order by app_id')]

    def reserve(self, app_id, capability, provider, length, digest):
        with self._lock:
            self._db.execute('begin immediate')
            try:
                quota = self._db.execute('select max_calls from ai_quota where app_id=?', (app_id,)).fetchone()
                count = self._db.execute('select count(*) from ai_usage where app_id=?', (app_id,)).fetchone()[0]
                if quota and count >= quota[0]:
                    self._db.rollback()
                    return None
                cur = self._db.execute('insert into ai_usage(ts,app_id,capability,provider,status,input_length,input_hash) values (?,?,?,?,?,?,?)', (time.time(), app_id, capability, provider, 'pending', length, digest))
                self._db.commit()
                return cur.lastrowid
            except BaseException:
                self._db.rollback()
                raise

    def finish(self, ident, status, provider):
        with self._lock, self._db:
            self._db.execute('update ai_usage set status=?,provider=? where id=?', (status, provider, ident))

    def usage(self):
        with self._lock:
            rows = self._db.execute('select app_id,capability,provider,status,count(*) from ai_usage group by app_id,capability,provider,status order by app_id,capability').fetchall()
        return [dict(app_id=r[0], capability=r[1], provider=r[2], status=r[3], calls=r[4]) for r in rows]

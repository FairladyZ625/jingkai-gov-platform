"""AI 配置与持久用量，使用平台数据库的独立表。"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .aihub.config import ENVIRONMENT_PROVIDER, ModelEnvironment, managed_api_key
from .migrations import migrate


PROVIDER_FIELDS = 'id,kind,base_url,models,enabled,allow_outbound'


class AISettings:
    def __init__(self, data_dir: Path, environment: ModelEnvironment | None = None):
        self.environment = environment or ModelEnvironment.read()
        data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(data_dir / 'platform.db', check_same_thread=False, timeout=30)
        try:
            migrate(self._db, data_dir)
        except BaseException:
            self._db.close()
            raise

    def put_provider(self, ident, kind, base_url, models, enabled, allow_outbound=None):
        with self._lock, self._db:
            old = self._db.execute('select allow_outbound from ai_provider where id=?', (ident,)).fetchone()
            limit = allow_outbound if allow_outbound is not None else (old[0] if old else None)
            self._db.execute(f'insert or replace into ai_provider({PROVIDER_FIELDS}) values (?,?,?,?,?,?)',
                             (ident, kind, base_url.rstrip('/'), json.dumps(models), int(enabled), limit))

    @staticmethod
    def _provider(row):
        ident, kind, base_url, models, enabled, limit = row
        return dict(id=ident, kind=kind, base_url=base_url, models=json.loads(models),
                    enabled=bool(enabled), allow_outbound=limit or 'internal',
                    api_key=managed_api_key(ident, base_url) if kind not in ('mock', 'builtin') else '')

    def provider(self, ident):
        if ident == ENVIRONMENT_PROVIDER:
            return self.environment.provider()
        with self._lock:
            row = self._db.execute(f'select {PROVIDER_FIELDS} from ai_provider where id=?', (ident,)).fetchone()
        return self._provider(row) if row is not None else None

    def providers(self):
        with self._lock:
            rows = self._db.execute(f'select {PROVIDER_FIELDS} from ai_provider where id<>? order by id',
                                    (ENVIRONMENT_PROVIDER,)).fetchall()
        items = [self._provider(row) for row in rows]
        environment = self.environment.provider()
        if environment:
            items.insert(0, environment)
        for item in items:
            item['has_key'] = bool(item['api_key'])
            item['api_key'] = '********' if item['has_key'] else ''
        return items

    def delete_provider(self, ident):
        with self._lock, self._db:
            self._db.execute('delete from ai_provider where id=?', (ident,))

    def put_route(self, capability, provider, model, fallback_provider=None, fallback_model=None):
        with self._lock, self._db:
            self._db.execute('insert or replace into ai_route values (?,?,?,?,?)', (capability, provider, model, fallback_provider, fallback_model))

    def stored_routes(self):
        with self._lock:
            rows = self._db.execute('select capability,provider,model,fallback_provider,fallback_model from ai_route order by capability').fetchall()
        return [dict(zip(('capability','provider','model','fallback_provider','fallback_model'), r)) for r in rows]

    def routes(self):
        routes = self.stored_routes()
        if self.environment.explicit:
            routes = [route for route in routes if route['capability'] != 'chat']
        environment = self.environment
        if environment.mode == 'mock':
            environment_chat, model = environment.explicit, environment.model or 'mock'
        else:
            environment_chat, model = environment.explicit or environment.ready(), environment.model
        if environment_chat and not any(route['capability'] == 'chat' for route in routes):
            routes.append(dict(capability='chat', provider=ENVIRONMENT_PROVIDER, model=model,
                               fallback_provider=None, fallback_model=None))
        return sorted(routes, key=lambda route: route['capability'])

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

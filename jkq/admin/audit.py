"""管理审计的筛选、分页和 CSV 导出。"""

import csv
import io
import json
import time
from datetime import datetime
from hashlib import sha256
from typing import Annotated

from fastapi import Depends, Header, Query, Request
from fastapi.responses import Response

from jkq.auth import BEIJING, AuthError

from .common import VIA, record_change, write

_COLUMNS = ('id', 'at', 'userId', 'user', 'role', 'app', 'action', 'target', 'model', 'via', 'detail')
_SOURCE = " from audit a left join users u on u.id=a.user_id"
_ROWS = "select a.id, a.ts, a.user_id, u.name, a.app_id, a.action, a.detail" + _SOURCE
_ORDER = " order by a.ts desc, a.id desc"
_EXPORT_CACHE = '~jkq.audit-export'
_REPLAY_SECONDS = 24 * 60 * 60


def _time(value, field):
    if value is None:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=BEIJING)
        return stamp.timestamp()
    except (ValueError, OverflowError):
        raise AuthError(400, 'INVALID_REQUEST', f'{field} 必须是 ISO 8601 时间', field=field) from None


def _filters(user: str = '', app: str = '', action: str = '',
             start: str | None = Query(None, alias='from'),
             end: str | None = Query(None, alias='to')):
    start, end = _time(start, 'from'), _time(end, 'to')
    if start is not None and end is not None and start > end:
        raise AuthError(400, 'INVALID_REQUEST', '开始时间不能晚于结束时间')
    clauses, params = [], []
    if user:
        clauses.append("(a.user_id=? or u.username=? or u.name=? "
                       "or json_extract(case when json_valid(a.detail) then a.detail end, '$.user')=?)")
        params.extend((user, user, user, user))
    for column, value in (('a.app_id=?', app), ('a.action=?', action), ('a.ts>=?', start), ('a.ts<=?', end)):
        if value is not None and value != '':
            clauses.append(column)
            params.append(value)
    return (' where ' + ' and '.join(clauses) if clauses else ''), tuple(params)


def _item(row):
    ident, ts, uid, name, app, action, raw = row
    try:
        detail = json.loads(raw)
    except ValueError:
        detail = {}
    if not isinstance(detail, dict):
        detail = {}
    via = detail.get('via')
    return dict(
        id=ident, at=datetime.fromtimestamp(ts, BEIJING).isoformat(), userId=uid,
        user=detail.get('user') or name or uid, role=detail.get('role'), app=app, action=action,
        target=detail.get('target') or detail.get('appId'), model=detail.get('model'),
        via=via if isinstance(via, str) and via in VIA else 'api', detail=detail,
    )


def _csv_cell(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and (
        value.startswith(('\t', '\r', '\n')) or value.lstrip(' \t\r\n\ufeff').startswith(
            ('=', '+', '-', '@', '＝', '＋', '－', '＠')
        )
    ):
        return "'" + value
    return value


def _csv_response(content):
    return Response(content, media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="audit.csv"',
                             'Cache-Control': 'no-store'})


def register(router, platform, admin):
    store = platform.store

    @router.get('/api/v1/audit')
    def audit(user=Depends(admin), filters=Depends(_filters), limit: int = Query(50, ge=1, le=1000),
              offset: int = Query(0, ge=0, le=2**63 - 1)):
        where, params = filters
        with store._lock, store._db as db:
            # 让总数与当页共享读取快照，即使另一个进程同时写入。
            db.execute('BEGIN')
            total = db.execute('select count(*)' + _SOURCE + where, params).fetchone()[0]
            rows = db.execute(_ROWS + where + _ORDER + ' limit ? offset ?', (*params, limit, offset)).fetchall()
        return dict(items=[_item(row) for row in rows], total=total)

    @router.get('/api/v1/audit/export')
    def export(request: Request, user=Depends(admin), filters=Depends(_filters),
               key: Annotated[str | None, Header(alias='Idempotency-Key', min_length=1, max_length=200)] = None):
        where, params = filters
        with write(platform, user) as db:
            if key is not None:
                now = time.time()
                cache_key = sha256(json.dumps([user.id, key]).encode()).hexdigest()
                signature = json.dumps([where, params], ensure_ascii=False)
                db.execute('delete from kv where app_id=? and updated<=?', (_EXPORT_CACHE, now - _REPLAY_SECONDS))
                cached = db.execute('select value from kv where app_id=? and key=?',
                                    (_EXPORT_CACHE, cache_key)).fetchone()
                if cached:
                    old_signature, content = json.loads(cached[0])
                    if old_signature != signature:
                        raise AuthError(409, 'CONFLICT', '该幂等键已用于不同的筛选条件')
                    return _csv_response(content)
            output = io.StringIO(newline='')
            writer = csv.writer(output)
            writer.writerow(_COLUMNS)
            count = 0
            for row in db.execute(_ROWS + where + _ORDER, params):
                item = _item(row)
                writer.writerow(_csv_cell(item[key]) for key in _COLUMNS)
                count += 1
            record_change(platform, db, user, request, action='audit.export', target='audit',
                          before=None, after={'count': count})
            content = output.getvalue()
            if key is not None:
                db.execute('insert into kv values (?,?,?,?)',
                           (_EXPORT_CACHE, cache_key, json.dumps([signature, content], ensure_ascii=False), now))
        return _csv_response(content)

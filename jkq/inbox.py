"""收件箱按当前用户聚合。实例入口通过 jkq.routers.ROUTERS 注册 router。"""
from contextlib import asynccontextmanager
import json
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StrictBool

from haiknow_core.main import current_user
from haiknow_core.stability import AppUnavailable
from haiknow_sdk import DataError

from . import feed
from .admin import usage
from .reviews_api import list_pending, STATUSES


class TodoPatch(BaseModel):
    done: StrictBool


def error(status, code, message):
    return JSONResponse({'error': {'code': code, 'message': message, 'details': {}}}, status_code=status)


def todo_view(row):
    ident, app, title, sender, at, ref, done = row
    return {'id': ident, 'kind': 'todo', 'app': app, 'title': title, 'from': sender,
            'at': feed.local_time(at), 'ref': json.loads(ref), 'done': bool(done),
            'status': 'done' if done else 'pending'}


TODO_FIELDS = 'id, app, title, sender, at, ref, done'


def todos_for(db, owner):
    rows = db.execute(f'select {TODO_FIELDS} from jkq_todos where owner=? order by at desc, id', (owner,))
    return [todo_view(row) for row in rows]


def review_item(review):
    return {'id': review['id'], 'kind': 'review', 'app': review['appId'],
            'title': review.get('title') or review['recordId'], 'from': review['submitter'],
            'at': feed.local_time(review['createdAt']), 'ref': {'recordId': review['recordId']},
            'status': STATUSES.get(review['status'], review['status'])}


def completed_reviews(service, user):
    db = service.store._db
    rows = db.execute("""select r.document, d.document from v1_decisions d
        join v1_reviews r on r.id=d.review_id
        where json_extract(d.document, '$.actor')=?
        and json_extract(d.document, '$.decision') in ('confirm','return')""", (user.id,))
    for raw, decision in rows:
        review = json.loads(raw)
        try:
            service._record(db, user, review['appId'], review['recordId'], review['version'])
        except AppUnavailable:
            continue
        except DataError as exc:
            if exc.code != 'not_found':
                raise
            continue
        yield {**review_item(review), 'at': feed.local_time(json.loads(decision)['createdAt'])}


def inbox_page(service, user, box):
    boxes = {'review': [], 'todo': [], 'done': []}
    with service.store._lock:
        for item in todos_for(service.store._db, user.id):
            boxes['done' if item['done'] else 'todo'].append(item)
        boxes['review'].extend(review_item(r) for r in list_pending(service, user)['items'])
        boxes['done'].extend(completed_reviews(service, user))
        for note in service.list_notifications(user)['items'] + service.list_messages(user)['items']:
            done = note['acknowledged'] if note.get('requiresAcknowledgement') else note['read']
            boxes['done' if done else 'todo'].append({
                'id': note['id'], 'kind': 'notice', 'app': note['appId'],
                'title': note.get('title') or note.get('message', ''), 'from': note.get('senderId', ''),
                'at': feed.local_time(note['createdAt']), 'ref': note['source'],
                'status': 'done' if done else 'pending',
            })
    items = sorted(boxes[box], key=lambda i: (i['at'], i['id']), reverse=True)
    counts = {name: len(rows) for name, rows in boxes.items()}
    counts['pending'] = counts['review'] + counts['todo']
    return {'items': items, 'total': len(items), 'counts': counts}


@asynccontextmanager
async def init_tables(app):
    store = app.state.platform.store
    with store._lock, store._db:
        store._db.execute("""create table if not exists jkq_todos (
            id text primary key, owner text not null, app text not null, title text not null,
            sender text not null, at real not null, ref text not null default '{}',
            done integer not null default 0 check(done in (0,1)))""")
        store._db.execute('create index if not exists jkq_todos_owner on jkq_todos(owner, at)')

        store._db.execute("""create table if not exists jkq_feed (
            id text primary key, project text not null, title text not null, at real not null)""")
    yield


router = APIRouter(lifespan=init_tables)


@router.get('/api/v1/todos')
def todos(request: Request, user=Depends(current_user)):
    store = request.app.state.platform.store
    with store._lock:
        items = todos_for(store._db, user.id)
    return {'items': items, 'total': len(items)}


@router.patch('/api/v1/todos/{id}')
def patch_todo(id: str, body: TodoPatch, request: Request, user=Depends(current_user)):
    store = request.app.state.platform.store
    with store._lock, store._db as db:
        store.begin_write()
        row = db.execute(f'select {TODO_FIELDS} from jkq_todos where id=? and owner=?',
                         (id, user.id)).fetchone()
        if row is None:
            return error(404, 'NOT_FOUND', '待办不存在')
        item = todo_view(row)
        if item['done'] != body.done:
            db.execute('update jkq_todos set done=? where id=? and owner=?', (body.done, id, user.id))
            store.audit(item['app'], user.id, 'todo.patch', {'id': id, 'done': body.done}, connection=db)
            item.update(done=body.done, status='done' if body.done else 'pending')
    return {'item': item}


@router.get('/api/v1/inbox')
def inbox(request: Request, box: str = 'review', user=Depends(current_user)):
    if box not in ('review', 'todo', 'done'):
        return error(400, 'INVALID_BOX', '收件箱分类须为 review、todo 或 done')
    return inbox_page(request.app.state.platform.data, user, box)


@router.get('/api/v1/feed')
def team_feed(request: Request, limit: int = Query(50, ge=1), offset: int = Query(0, ge=0),
              user=Depends(current_user)):
    store = request.app.state.platform.store
    with store._lock:
        return feed.feed_page(store._db, user.projects, limit, offset)


@router.get('/api/v1/admin/usage')
def admin_usage(request: Request, groupBy: Literal['app', 'model', 'user'] = 'app', user=Depends(current_user)):
    platform = request.app.state.platform
    if 'admin' not in platform.rbac.actions(user, '*'):
        return error(403, 'FORBIDDEN', '需要管理员权限')
    with platform.store._lock:
        return usage.usage_page(platform.store._db, groupBy)

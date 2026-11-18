"""经开区审签 HTTP 语义，版本、写入和审计由卫华 DataService 管理。"""

import json
from typing import Literal

from fastapi import Depends
from pydantic import BaseModel, Field

from haiknow_core.data import one, parse
from haiknow_core.stability import AppUnavailable
from haiknow_sdk import DataError

from .jobs_api import api_error, replace_core_route


DECISIONS = {'approve': 'confirm', 'reject': 'return'}
STATUSES = {'confirmed': 'done', 'needs_info': 'rejected'}


class DecisionBody(BaseModel):
    decision: Literal['approve', 'reject']
    version: int = Field(strict=True, gt=0)
    reason: str = ''


def review_view(review):
    return {
        **review, 'app': review['appId'], 'ref': review['recordId'],
        'status': STATUSES.get(review['status'], review['status']),
    }


def list_pending(service, user, app_id):
    with service.store._lock:
        db = service.store._db
        rows = db.execute("select document from v1_reviews order by rowid desc").fetchall()
        items = []
        for (raw,) in rows:
            review = json.loads(raw)
            app = review['appId']
            if review['status'] != 'pending' or (app_id is not None and app != app_id):
                continue
            if review['assignee'] != user.id and 'approve' not in service.rbac.actions(user, app):
                continue
            try:
                record = service._record(db, user, app, review['recordId'], review['version'])
            except AppUnavailable:
                continue
            except DataError as error:
                if error.code != 'not_found':
                    raise
                continue
            items.append({**review_view(review), 'project': record['project']})
        return {'items': items}


def require_approve(service, db, user, review):
    if 'approve' in service.rbac.actions(user, review['appId']):
        return
    # 项目外资源仍按不存在处理，应用无查看权限的同项目用户也收到 403。
    versions = db.execute(
        'select v.document from v1_versions v join v1_records r on r.id=v.record_id '
        'where r.id=? and v.version in (r.latest, ?)',
        (review['recordId'], review['version']),
    )
    for (raw,) in versions:
        service.projects.require(user, json.loads(raw)['project'])
    raise DataError('forbidden', '没有该应用的审签权限')


def decide(service, user, review_id, body):
    payload = parse(DecisionBody, body)
    store = service.store
    with store._lock, store._db:
        store.begin_write()
        row = one(store._db, 'select document from v1_reviews where id=?', (review_id,))
        if row is None:
            raise DataError('not_found', '确认待办不存在')
        review = json.loads(row[0])
        require_approve(service, store._db, user, review)
        try:
            result = service.decide_review(user, review_id, {
                'version': payload['version'], 'decision': DECISIONS[payload['decision']],
                'comment': payload['reason'],
            }, generic_http=True)
        except DataError as error:
            if (error.code == 'invalid_state' and review['status'] in STATUSES
                    and service.apps[review['appId']].manifest.get('review') != 'app'):
                return api_error(DataError('invalid_state', '此待办已处理'), code='ALREADY_DECIDED')
            raise
    item = review_view(result)
    item['decision'] = {**result['decision'], 'decision': payload['decision']}
    return {'item': item}


def install(app, current_user):
    service = app.state.platform.data

    def reviews(app: str | None = None, user=Depends(current_user)):
        try:
            return list_pending(service, user, app)
        except DataError as error:
            return api_error(error)

    def decide_review(rid: str, body: dict, user=Depends(current_user)):
        try:
            return decide(service, user, rid, body)
        except DataError as error:
            return api_error(error, status=409 if error.code == 'self_review' else None)

    replace_core_route(app.router, '/api/v1/reviews', 'GET', reviews)
    replace_core_route(app.router, '/api/v1/reviews/{rid}/decisions', 'POST', decide_review)

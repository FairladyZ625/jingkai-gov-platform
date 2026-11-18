"""§4.3 会议纪要、待办派发、企业诉求关联。"""

from datetime import datetime, timedelta, timezone
import re

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from haiknow_sdk import DataError, PermissionDenied, app_context, require
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from .enterprise_link import create_issue
from .minutes import (
    Input, MeetingPatch, ShortText, edit_minutes, minutes_for,
    public_todos, require_transcript, todos_for,
)
from .todos import commit_todos, my_todos

BEIJING = timezone(timedelta(hours=8))
DOCUMENT_TEMPLATES = (
    (re.compile('征集'), 'T04', 'title'),
    (re.compile('口径|答复|告知'), 'T10', 'issue'),
    (re.compile('方案|指南'), 'T02', 'title'),
)


class CommitRequest(Input):
    ids: list[ShortText] = Field(max_length=500)


class LinkRequest(Input):
    entId: ShortText
    title: ShortText | None = None


class MeetingRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request):
            try:
                return await handler(request)
            except DataError as exc:
                details = {k: v for k, v in exc.error.items() if k not in ('code', 'message', 'retryable')}
                code, message, status = exc.code.upper(), str(exc), exc.status
            except PermissionDenied as exc:
                code, message, status, details = 'FORBIDDEN', '没有执行此操作的权限', 403, {'need': exc.action}
            except RequestValidationError as exc:
                code, message, status = 'INVALID_REQUEST', '请求字段缺失或类型不正确', 422
                details = {'fields': [list(error['loc']) for error in exc.errors()]}
            except HTTPException as exc:
                status, message, details = exc.status_code, str(exc.detail), {}
                code = {401: 'UNAUTHENTICATED', 403: 'FORBIDDEN', 404: 'NOT_FOUND',
                        409: 'INVALID_STATE', 503: 'APP_UNAVAILABLE'}.get(status, 'INVALID_REQUEST')
            return JSONResponse({'error': {'code': code, 'message': message, 'details': details}}, status)

        return handle


router = APIRouter(route_class=MeetingRoute)


def meeting_record(ctx, meeting_id):
    record = ctx.records.get(meeting_id)
    if record['type'] != 'meeting' or not isinstance(record['data'], dict):
        raise DataError('not_found', '会议不存在')
    return record


def meeting_view(ctx, record):
    data = record['data']
    status = 'done' if data.get('transcript') else 'new'
    if data.get('jobId'):
        try:
            job = ctx.preview.jobs.get(data['jobId'])
        except DataError as exc:
            if exc.code != 'not_found':
                raise
        else:
            if job['status'] in ('queued', 'running', 'cancelling'):
                status = 'running'
    item = {key: value for key, value in data.items() if key != 'minutesEdit'}
    item.update(id=record['id'], status=status, todos=public_todos(data))
    if data.get('transcriptMode') == 'demo':
        item['transcriptAudio'] = '/api/apps/meeting/transcription/demo'
    return {'item': item, 'minutes': minutes_for(data)}


@router.get('/meetings/{meeting_id}')
def get_meeting(meeting_id: str, ctx=Depends(app_context)):
    return meeting_view(ctx, meeting_record(ctx, meeting_id))


@router.patch('/meetings/{meeting_id}')
def patch_meeting(meeting_id: str, patch: MeetingPatch, ctx=Depends(require('operate'))):
    record = meeting_record(ctx, meeting_id)
    edit_minutes(record['data'], patch)
    saved = ctx.records.save(id=meeting_id, baseVersion=record['version'], data=record['data'])
    return meeting_view(ctx, saved)


@router.post('/meetings/{meeting_id}/todos/commit')
def dispatch_todos(meeting_id: str, body: CommitRequest, ctx=Depends(require('operate'))):
    # 对并发写入重读版本，让重复派发得到与重试相同的结果。
    for attempt in range(3):
        record = meeting_record(ctx, meeting_id)
        require_transcript(record['data'])
        try:
            return commit_todos(ctx, record, body.ids)
        except DataError as exc:
            if exc.code != 'version_conflict' or attempt == 2:
                raise


@router.get('/my-todos')
def personal_todos(ctx=Depends(app_context)):
    return my_todos(ctx, now=datetime.now(BEIJING))


@router.post('/meetings/{meeting_id}/link')
async def link_meeting(meeting_id: str, body: LinkRequest, request: Request, ctx=Depends(require('operate'))):
    record = await run_in_threadpool(meeting_record, ctx, meeting_id)
    data = record['data']
    require_transcript(data)
    issue = await create_issue(request, {
        'entId': body.entId, 'title': body.title or f"{data['title']}中提出的诉求",
        'from': '会议', 'next': '按会议纪要跟进',
    })
    await run_in_threadpool(ctx.audit, 'meeting.link', {'recordId': meeting_id, 'issueId': issue['id']})
    return {'issue': issue}


@router.get('/meetings/{meeting_id}/todos/{todo_id}/document-link')
def document_link(meeting_id: str, todo_id: str, ctx=Depends(app_context)):
    data = meeting_record(ctx, meeting_id)['data']
    todo = next((item for item in todos_for(data) if item['id'] == todo_id), None)
    if todo is None:
        raise DataError('not_found', '会议待办不存在')
    task = todo['task']
    text = task + (todo.get('deliverable') or '')
    template, input_key = next(((template, key) for pattern, template, key in DOCUMENT_TEMPLATES
                                if pattern.search(text)), ('T02', 'title'))
    return {'app': 'document', 'route': 'new', 'params': {
        'templateId': template, 'autogen': True, 'fromMeeting': meeting_id,
        'inputs': {input_key: re.sub(r'^起草\s*', '', task)},
        'from': {'app': 'meeting', 'id': meeting_id, 'title': data['title']},
    }}

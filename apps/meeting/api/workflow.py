"""§4.3 会议纪要、待办派发、企业诉求关联。"""

from datetime import datetime
import re

from fastapi import APIRouter, Depends, Request
from haiknow_sdk import DataError, app_context, require
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from .enterprise_link import create_issue
from .meetings import BEIJING, MeetingRoute, meeting_detail
from .minutes import Input, MeetingPatch, ShortText, edit_minutes, require_transcript, todos_for
from .todos import commit_todos, my_todos
from .transcription import meeting_record, require_owner

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


router = APIRouter(route_class=MeetingRoute)


@router.patch('/meetings/{meeting_id}')
def patch_meeting(meeting_id: str, patch: MeetingPatch, ctx=Depends(require('operate'))):
    record = meeting_record(ctx, meeting_id)
    require_owner(ctx, record)
    if record['data'].get('ownerId'):
        from .workbench import owner
        owner(ctx, record)
        raise DataError('invalid_state', '请在会议纪要工作台保存带版本的修订，已定稿版本保持不变')
    edit_minutes(record['data'], patch)
    saved = ctx.records.save(id=meeting_id, baseVersion=record['version'], data=record['data'])
    return meeting_detail(ctx, saved)


@router.post('/meetings/{meeting_id}/todos/commit')
def dispatch_todos(meeting_id: str, body: CommitRequest, ctx=Depends(require('operate'))):
    record = meeting_record(ctx, meeting_id)
    require_owner(ctx, record)
    if record['data'].get('ownerId'):
        raise DataError('invalid_state', '工作台会议请核对定稿、成员和明确期限后派发')
    # 对并发写入重读版本，让重复派发得到与重试相同的结果。
    for attempt in range(3):
        record = meeting_record(ctx, meeting_id)
        require_owner(ctx, record)
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
    require_owner(ctx, record)
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

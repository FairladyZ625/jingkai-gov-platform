"""§4.3 会议录音与转写路由，由 #29 的会议应用挂载。"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from haiknow_sdk import DataError, PermissionDenied, app_context, require
from starlette.exceptions import HTTPException

from .transcription import (
    DEMO_AUDIO, MEETING_LOCK, MEETING_TYPES, OPERATION, RECORD_TYPE, Options,
    __haiknow_jobs__, attach_job, meeting_record,
)


PROJECT = 'jkq'
MAX_AUDIO_BYTES = 64 * 1024 * 1024
BEIJING = timezone(timedelta(hours=8))
DEMO_URL = '/api/apps/meeting/transcription/demo'
WEB_PAGE = Path(__file__).resolve().parents[1] / 'web' / 'transcription.html'
SIMPLE_AUDIO_SIGNATURES = {
    'amr': (b'#!AMR\n', b'#!AMR-WB\n'),
    'flac': (b'fLaC',),
    'ogg': (b'OggS',),
    'webm': (b'\x1a\x45\xdf\xa3',),
}


def error_response(code, message, status, details=None):
    return JSONResponse({'error': {'code': code, 'message': message, 'details': details or {}}},
                        status_code=status)


class MeetingRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request):
            try:
                return await handler(request)
            except DataError as exc:
                details = {k: v for k, v in exc.error.items() if k not in ('code', 'message', 'retryable')}
                return error_response(exc.code.upper(), str(exc), exc.status, details)
            except PermissionDenied as exc:
                return error_response('FORBIDDEN', '没有执行此操作的权限', 403, {'need': exc.action})
            except RequestValidationError as exc:
                fields = [list(error['loc']) for error in exc.errors()]
                return error_response('INVALID_REQUEST', '请求字段缺失或类型不正确', 422, {'fields': fields})
            except HTTPException as exc:
                code = {401: 'UNAUTHENTICATED', 403: 'FORBIDDEN', 404: 'NOT_FOUND'}.get(
                    exc.status_code, 'INVALID_REQUEST'
                )
                return error_response(code, str(exc.detail), exc.status_code)

        return handle


router = APIRouter(route_class=MeetingRoute)


def job_view(job):
    """提交回执按 §3.5 展示，与 #18 的公开轮询快照对齐。"""
    names = [step['name'] for step in job['steps']]
    completed = sum(step['status'] == 'done' for step in job['steps'])
    status = {'queued': 'running', 'cancelling': 'running', 'cancelled': 'failed'}.get(
        job['status'], job['status']
    )
    return {
        'id': job['id'], 'kind': OPERATION, 'ref': job['input'].get('ref'), 'status': status,
        'progress': 100 if status == 'done' else 100 * completed // (completed + 1),
        'step': max(0, len(names) - 1), 'steps': names, 'stepName': names[-1] if names else None,
    }


def meeting_view(ctx, record):
    item = {**record['data'], 'id': record['id']}
    item['status'] = 'done' if item.get('transcript') else 'new'
    if item.get('jobId'):
        try:
            job = ctx.preview.jobs.get(item['jobId'])
        except DataError as exc:
            if exc.code != 'not_found':
                raise
            item.pop('jobId')
        else:
            if job_view(job)['status'] == 'running':
                item['status'] = 'running'
    if item.get('transcriptMode') == 'demo':
        item['transcriptAudio'] = DEMO_URL
    return item


def parse_participants(value):
    try:
        people = json.loads(value)
    except ValueError as exc:
        raise DataError('invalid_request', '参会人员须为 JSON 字符串数组') from exc
    if not isinstance(people, list) or len(people) > 100 or any(
        not isinstance(name, str) or not name.strip() or len(name) > 160 for name in people
    ):
        raise DataError('invalid_request', '参会人员须为不超过 100 项的非空字符串数组')
    return [name.strip() for name in people]


def audio_upload(file):
    name = Path((file.filename or '').replace('\\', '/')).name
    extension = Path(name).suffix.lower().lstrip('.')
    if (
        len(name) > 255 or not (
            (file.content_type or '').startswith(('audio/', 'video/'))
            or file.content_type == 'application/octet-stream'
        )
    ):
        raise DataError('invalid_request', '请选择受支持的录音文件')
    if file.size is not None and file.size > MAX_AUDIO_BYTES:
        raise HTTPException(413, '单份录音不得超过 64 MiB')
    data = file.file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, '单份录音不得超过 64 MiB')
    if not data:
        raise DataError('invalid_request', '录音文件为空')
    if extension == 'wav':
        valid = data.startswith(b'RIFF') and data[8:12] == b'WAVE'
    elif extension in {'m4a', 'mp4'}:
        valid = data[4:8] == b'ftyp'
    elif extension in {'mp3', 'aac'}:
        valid = data.startswith(b'ID3') or (len(data) >= 2 and data[0] == 0xff and data[1] & 0xe0 == 0xe0)
    else:
        valid = extension in SIMPLE_AUDIO_SIGNATURES and data.startswith(SIMPLE_AUDIO_SIGNATURES[extension])
    if not valid:
        raise DataError('invalid_request', '文件内容与受支持的录音格式不符')
    return name, data


@router.get('/meetings')
def list_meetings(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                  ctx=Depends(app_context)):
    records = ctx.records.list(project=PROJECT, type=RECORD_TYPE)['items']
    items = []
    for record in records[offset:offset + limit]:
        item = meeting_view(ctx, record)
        item['todoCount'] = len(item.pop('todos', []))
        item.pop('transcript', None)
        item.pop('topics', None)
        items.append(item)
    templates = [{'id': f'meeting-{index}', 'name': name, 'sections': ['逐字稿']}
                 for index, name in enumerate(MEETING_TYPES, 1)]
    return {'items': items, 'total': len(records), 'templates': templates, 'hotwords': ['北京经开区']}


@router.post('/meetings', status_code=201)
def create_meeting(title: str = Form(min_length=1, max_length=160),
                   type: str = Form(default=MEETING_TYPES[0]),
                   participants: str = Form(default='[]'), file: UploadFile | None = None,
                   source: str = Form(default='upload'), ctx=Depends(require('operate'))):
    title = title.strip()
    if not title or type not in MEETING_TYPES or source not in {'upload', 'live', 'nas', 'demo'}:
        raise DataError('invalid_request', '请填写会议名称、有效类型和录音来源')
    people = parse_participants(participants)
    if file is not None and source != 'demo':
        name, audio = audio_upload(file)
    elif file is None and source == 'demo':
        name, audio = DEMO_AUDIO.name, DEMO_AUDIO.read_bytes()
    else:
        raise DataError('invalid_request', '请上传录音，或选择演示录音')
    saved = ctx.data_files.save(name, audio, project=PROJECT, purpose='meeting_audio')
    data = {
        'title': title, 'type': type, 'participants': people, 'source': source,
        'date': datetime.now(BEIJING).isoformat(timespec='seconds'), 'place': '', 'host': '',
        'duration': '00:11' if source == 'demo' else None,
        'file': saved['name'], 'fileId': saved['fileId'], 'size': saved['size'],
        'transcript': [], 'topics': [], 'todos': [],
    }
    record = ctx.records.save(project=PROJECT, type=RECORD_TYPE, data=data, files=[saved['fileId']])
    return {'item': meeting_view(ctx, record)}


@router.get('/meetings/{meeting_id}')
def get_meeting(meeting_id: str, ctx=Depends(app_context)):
    return {'item': meeting_view(ctx, meeting_record(ctx, meeting_id)), 'minutes': None}


@router.post('/meetings/{meeting_id}/transcribe', status_code=202)
def start_transcription(meeting_id: str, options: Options | None = None,
                        key: str | None = Header(default=None, alias='Idempotency-Key'),
                        ctx=Depends(require('operate'))):
    options = options or Options()
    if key is not None and (not key.strip() or len(key) > 200):
        raise DataError('invalid_request', 'Idempotency-Key 须为 1 到 200 个字符')

    inputs = {'ref': meeting_id, **options.model_dump(exclude_none=True)}
    with MEETING_LOCK:
        record = meeting_record(ctx, meeting_id)
        current_id = record['data'].get('jobId')
        job_key = key if key is not None else f'meeting:{meeting_id}'
        if current_id:
            try:
                current = ctx.preview.jobs.get(current_id)
            except DataError as exc:
                if exc.code != 'not_found':
                    raise
                raise DataError('invalid_state', '该会议已有转写任务') from exc
            if current['submitter'] != ctx.user.id or (
                key is not None and key != current['idempotencyKey']
            ):
                raise DataError('invalid_state', '该会议已有转写任务，请在原任务中查看或重试')
            job_key = current['idempotencyKey']
        job = ctx.preview.jobs.submit(OPERATION, project=record['project'], input=inputs, idempotency_key=job_key)
        attach_job(ctx, record, job['id'])
    return {'job': job_view(job)}


@router.get('/transcription', include_in_schema=False)
def transcription_page(_ctx=Depends(app_context)):
    return FileResponse(WEB_PAGE, media_type='text/html; charset=utf-8')


@router.get('/transcription/demo', include_in_schema=False)
def demo_audio(_ctx=Depends(app_context)):
    return FileResponse(DEMO_AUDIO, media_type='audio/webm')

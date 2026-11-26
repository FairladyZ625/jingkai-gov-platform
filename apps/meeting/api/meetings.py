"""§4.3 会议录音与转写路由，由 #29 的会议应用挂载。"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from haiknow_sdk import DataError, PermissionDenied, app_context, require
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartParser

from .minutes import minutes_for, public_todos
from .transcription import (
    DEMO_AUDIO, MEETING_LOCK, MEETING_TYPES, OPERATION, RECORD_TYPE, Options,
    __haiknow_jobs__, attach_job, demo_parts, meeting_record, meeting_owner, transcribe_part,
)


PROJECT = 'jkq'
MAX_AUDIO_BYTES = 64 * 1024 * 1024
BEIJING = timezone(timedelta(hours=8))
DEMO_URL = '/api/apps/meeting/transcription/demo'
DEMO_SAMPLE_ID = 'park-service-v1'
DEMO_SAMPLE_TITLE = '【合成演示】园区服务清单核对'
DEMO_SAMPLE_TYPE = '专题推进会'
LEGACY_DEMO_TITLE = '【示例】文化企业座谈会录音_1117'
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
                code = {
                    401: 'UNAUTHENTICATED',
                    403: 'FORBIDDEN',
                    404: 'NOT_FOUND',
                    409: 'INVALID_STATE',
                    413: 'PAYLOAD_TOO_LARGE',
                    503: 'APP_UNAVAILABLE',
                }.get(exc.status_code, 'INVALID_REQUEST')
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
        'cancelled': job['status'] in {'cancelled', 'cancelling'},
        'progress': 100 if status == 'done' else 100 * completed // (completed + 1),
        'step': max(0, len(names) - 1), 'steps': names, 'stepName': names[-1] if names else None,
    }


def is_demo_sample(data):
    if data.get('source') != 'demo' or data.get('file') != DEMO_AUDIO.name:
        return False
    if data.get('sampleId') == DEMO_SAMPLE_ID:
        return True
    # 只整理系统自动生成的无编辑副本。不同纪要、待办、参会人仍是独立会议。
    if (data.get('title') != LEGACY_DEMO_TITLE or data.get('minutesEdit') or data.get('todos')
            or data.get('participants') or data.get('place') or data.get('host')):
        return False
    transcript = data.get('transcript')
    return not transcript or (DEMO_AUDIO.is_file() and transcript == [
        line for part in demo_parts() for line in transcribe_part(part, hotwords=[], step_key='legacy')])


def preferred_sample(records):
    return max(
        (record for record in records if is_demo_sample(record['data'])),
        key=lambda record: (bool(record['data'].get('transcript')), bool(record['data'].get('jobId')),
                            record['data'].get('sampleId') == DEMO_SAMPLE_ID),
        default=None,
    )


def meeting_view(ctx, record):
    data = record['data']
    # 共享合成样本可只读预览，不能因复用档案而让另一成员启动或写入原会议。
    # 既核对样本身份，也逐字节核对实际音频；普通同名录音与自定义记录不适用。
    preview = False
    if is_demo_sample(data) and meeting_owner(ctx, record) != ctx.user.id:
        if data.get('fileId') and ctx.data_files.read(data['fileId']) == DEMO_AUDIO.read_bytes():
            data = {**data, 'readOnlySample': True}
            if not data.get('transcript'):
                data.update(transcript=[line for part in demo_parts()
                            for line in transcribe_part(part, hotwords=[], step_key='readonly-public-sample')],
                            transcriptMode='demo')
            preview = True
    item = {key: value for key, value in data.items() if key != 'minutesEdit'}
    if is_demo_sample(data):
        item.update(sampleId=DEMO_SAMPLE_ID, title=DEMO_SAMPLE_TITLE, type=DEMO_SAMPLE_TYPE)
    item.update(id=record['id'], todos=public_todos(data))
    item['status'] = 'done' if item.get('transcript') else 'new'
    if item.get('jobId') and not preview:
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


async def read_meeting_form(request):
    """先完成鉴权，再在上限内解析 multipart，避免未授权或超限请求先落临时文件。"""
    limit = MAX_AUDIO_BYTES + 256 * 1024
    length = request.headers.get('content-length')
    if length is not None:
        try:
            size = int(length)
        except ValueError as exc:
            raise HTTPException(413, '单份录音不得超过 64 MiB') from exc
        if size > limit:
            raise HTTPException(413, '单份录音不得超过 64 MiB')
    content_type = request.headers.get('content-type') or ''
    if 'application/x-www-form-urlencoded' in content_type:
        return await request.form(), None
    if 'multipart/form-data' not in content_type:
        raise DataError('invalid_request', '请使用 multipart 上传录音')

    chunks = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            raise HTTPException(413, '单份录音不得超过 64 MiB')
        chunks.append(chunk)
    body = b''.join(chunks)

    async def body_stream():
        yield body

    try:
        form = await MultiPartParser(
            request.headers,
            body_stream(),
            max_files=2,
            max_fields=20,
            max_part_size=limit,
        ).parse()
    except HTTPException:
        raise
    except Exception as exc:
        name = type(exc).__name__
        if 'MultiPart' in name or 'ClientDisconnect' in name:
            raise HTTPException(413, '单份录音不得超过 64 MiB') from exc
        raise
    files = [value for _, value in form.multi_items() if isinstance(value, UploadFile)]
    if len(files) > 1:
        for item in files:
            await item.close()
        raise HTTPException(413, '一次只能上传一份录音')
    return form, files[0] if files else None


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
    sample = preferred_sample(records)
    if sample:
        records = [row for row in records if row['id'] == sample['id'] or not is_demo_sample(row['data'])]
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
async def create_meeting(request: Request, ctx=Depends(require('operate'))):
    form, file = await read_meeting_form(request)
    sample_id = str(form.get('sampleId') or '')
    if sample_id:
        if sample_id != DEMO_SAMPLE_ID or form.get('source') != 'demo' or file is not None:
            raise DataError('invalid_request', '合成示例不接受自定义录音')
        with MEETING_LOCK:
            records = ctx.records.list(project=PROJECT, type=RECORD_TYPE)['items']
            current = preferred_sample(records)
            if current:
                return JSONResponse({'item': meeting_view(ctx, current)}, status_code=200)
            return save_meeting(ctx, DEMO_SAMPLE_TITLE, DEMO_SAMPLE_TYPE, [], 'demo',
                                DEMO_AUDIO.name, DEMO_AUDIO.read_bytes(), sample_id=DEMO_SAMPLE_ID)
    title = str(form.get('title') or '').strip()
    type = str(form.get('type') or MEETING_TYPES[0])
    participants = form.get('participants')
    participants = '[]' if participants is None else str(participants)
    source = str(form.get('source') or 'upload')
    if not title or len(title) > 160 or type not in MEETING_TYPES or source not in {'upload', 'live', 'nas', 'demo'}:
        raise DataError('invalid_request', '请填写会议名称、有效类型和录音来源')
    people = parse_participants(participants)
    if file is not None and source != 'demo':
        name, audio = audio_upload(file)
    elif file is None and source == 'demo':
        name, audio = DEMO_AUDIO.name, DEMO_AUDIO.read_bytes()
    else:
        raise DataError('invalid_request', '请上传录音，或选择演示录音')
    return save_meeting(ctx, title, type, people, source, name, audio)


def save_meeting(ctx, title, type, people, source, name, audio, *, sample_id=None):
    saved = ctx.data_files.save(name, audio, project=PROJECT, purpose='meeting_audio')
    data = {
        'title': title, 'type': type, 'participants': people, 'source': source,
        'date': datetime.now(BEIJING).isoformat(timespec='seconds'), 'place': '', 'host': '',
        'duration': '00:11' if source == 'demo' else None,
        'file': saved['name'], 'fileId': saved['fileId'], 'size': saved['size'],
        'transcript': [], 'topics': [], 'todos': [],
    }
    if sample_id:
        data['sampleId'] = sample_id
    record = ctx.records.save(project=PROJECT, type=RECORD_TYPE, data=data, files=[saved['fileId']])
    return {'item': meeting_view(ctx, record)}


def meeting_detail(ctx, record):
    item = meeting_view(ctx, record)
    projected = {**record['data'], **item}
    return {'item': item, 'minutes': minutes_for(projected)}


@router.get('/meetings/{meeting_id}')
def get_meeting(meeting_id: str, ctx=Depends(app_context)):
    return meeting_detail(ctx, meeting_record(ctx, meeting_id))


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
        if record['data'].get('ownerId') and record['data']['ownerId'] != ctx.user.id and not ctx.can('admin'):
            raise DataError('forbidden', '仅会议整理负责人可启动转写')
        from .transcription import require_owner
        require_owner(ctx, record)
        current_id = record['data'].get('jobId')
        job_key = key if key is not None else f'meeting:{meeting_id}'
        if current_id:
            try:
                current = ctx.preview.jobs.get(current_id)
            except DataError as exc:
                if exc.code != 'not_found':
                    raise
                raise DataError('invalid_state', '该会议已有转写任务') from exc
            cancelled = current['status'] in {'cancelled', 'cancelling'}
            if cancelled:
                if key is not None and key == current.get('idempotencyKey'):
                    return {'job': job_view(current)}
                job_key = key if key is not None else f'meeting:{meeting_id}:restart'
            elif current['submitter'] != ctx.user.id or (
                key is not None and key != current['idempotencyKey']
            ):
                raise DataError('invalid_state', '该会议已有转写任务，请在原任务中查看或重试')
            else:
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

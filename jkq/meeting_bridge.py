"""实例拥有转写适配、个人收件箱与 Word 依赖，会议应用只调用公开桥接能力。"""
from io import BytesIO
import re
import sys
import sqlite3
from types import SimpleNamespace

from docx import Document
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from haiknow_sdk import DataError

from .meeting_tasks import task_state, update_task, install_reassignment


async def recognize(audio):
    from .transcribe import transcriber_from_environment
    adapter = transcriber_from_environment()
    if adapter.provider is None:
        raise DataError('invalid_state', '未配置真实语音转写服务；录音已保留，可补录文字或配置服务后重试')
    return await adapter.transcribe(audio)


def export_word(result):
    item, minutes = result['item'], result['minutes']
    document = Document()
    clean = lambda value: re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value))
    document.add_heading(clean(minutes['title']), 0)
    document.add_paragraph(clean(f"{item['date']} · {item['minutesStatus']} · 版本 {item['version']}"))
    if item['minutesStatus'] != '已定稿':
        document.add_paragraph('草稿 · 尚未经办人核对定稿')
    else:
        document.add_paragraph(clean(f"定稿人：{item.get('finalizedBy', '')}　时间：{item.get('finalizedAt', '')}"))
    for section in minutes.get('body', []):
        document.add_heading(clean(section['h']), 2)
        document.add_paragraph(clean(section['p']))
        for source in section.get('sources', []):
            document.add_paragraph(clean(f"依据 {source['id']}（来源版本 {source['version']}）：{source['quote']}"))
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue(), re.sub(r'[\x00-\x1f/\\]', '_', item['title']) + '.docx'


def install(app):
    platform = app.state.platform
    from .inbox import ensure_tables
    with platform.store._lock, platform.store._db as db:
        ensure_tables(db)
        install_reassignment(db)

    def reassign(user, record, data):
        try:
            return platform.data.save_record(user, 'meeting', {'baseVersion': record['version'], 'data': data}, record['id'])
        except sqlite3.IntegrityError as exc:
            if str(exc) == 'meeting_assignment_closed':
                raise DataError('invalid_state', '事项已完成或已取消，请先说明原因重开') from exc
            if str(exc) == 'meeting_assignment_conflict':
                raise DataError('version_conflict', '原负责人或期限已变化，请重新加载') from exc
            raise

    def progress(user, meeting_id, todo_id, status, note):
        # 同事务重查最新接收人，防止跨进程改派与原负责人办理请求交错。
        with platform.store._lock, platform.store._db:
            platform.store.begin_write()
            record = platform.data.get_record(user, 'meeting', meeting_id)
            todo = next((t for t in record['data'].get('todos', []) if t['id'] == todo_id), None)
            if not todo or not todo.get('assignment'):
                raise DataError('not_found', '已派发事项不存在')
            assignment = todo['assignment']
            actions = platform.rbac.actions(user, 'meeting')
            manager = 'operate' in actions and (record['data'].get('ownerId', record['submitter']) == user.id or 'admin' in actions)
            if (status == '已取消' and not manager) or (status != '已取消' and assignment['recipientId'] != user.id and not (manager and status == '待处理')):
                raise DataError('forbidden', '负责人已变化或无权更新此事项，请重新加载')
            old = task_state(platform.store, assignment)
            if old['status'] in ('已完成', '已取消') and status not in (old['status'], '待处理'):
                raise DataError('invalid_state', '请先填写原因并重开为待处理')
            update_task(platform.store, assignment, status, note, user.id)
            return record

    guard = APIRouter(prefix='/api/v1/apps/meeting')

    @guard.post('/records', include_in_schema=False)
    @guard.put('/records/{identity}', include_in_schema=False)
    def use_meeting_routes():
        return JSONResponse({'error': {'code': 'METHOD_NOT_ALLOWED', 'message': '请使用会议记录或工作台接口写入，保留负责人、版本和派发校验'}}, status_code=405)

    routes = app.router.routes
    count = len(routes)
    app.include_router(guard)
    routes[:] = routes[count:] + routes[:count]
    app.state.meeting_services = SimpleNamespace(
        task_state=lambda assignment: task_state(platform.store, assignment),
        progress=progress,
        target=lambda user, module, ident: platform.data.get_record(user, module, ident),
        export_word=export_word, reassign=reassign,
    )
    module = sys.modules.get('haiknow_apps.meeting.transcription')
    if module is not None:
        module.configure_transcriber(recognize)

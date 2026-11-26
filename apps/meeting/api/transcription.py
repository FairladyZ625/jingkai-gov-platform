"""会议转写的持久步骤，调用卫华 jobs 检查点。"""
import asyncio
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal

from haiknow_sdk import DataError
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from haiknow_sdk.preview.jobs import operation


RECORD_TYPE = 'meeting'
OPERATION = 'transcribe'
DEMO_AUDIO = Path(__file__).resolve().parents[1] / 'samples' / 'demo.webm'
MeetingType = Literal['企业座谈会', '局务会', '专题推进会']
MEETING_TYPES = ('企业座谈会', '局务会', '专题推进会')
MEETING_LOCK = Lock()
TRANSCRIBE_AUDIO = None


def configure_transcriber(provider):
    """实例安装真实转写能力；未接入时拒绝用示例内容代替。"""
    global TRANSCRIBE_AUDIO
    TRANSCRIBE_AUDIO = provider
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class Options(BaseModel):
    title: ShortText | None = None
    type: MeetingType | None = None
    hotwords: list[ShortText] = Field(default_factory=list, max_length=100)


class TranscriptionInput(Options):
    ref: str = Field(min_length=1)


def meeting_record(ctx, meeting_id):
    record = ctx.records.get(meeting_id)
    if record['type'] != RECORD_TYPE or not isinstance(record['data'], dict):
        raise DataError('not_found', '会议不存在')
    return record


def meeting_owner(ctx, record):
    if record['data'].get('ownerId'):
        return record['data']['ownerId']
    # 老记录没有负责人字段时回看创建者，不能把最近写入者变成负责人。
    return record['submitter'] if record['version'] == 1 else ctx.records.get(record['id'], 1)['submitter']


def require_owner(ctx, record):
    if not ctx.can('operate') or (meeting_owner(ctx, record) != ctx.user.id and not ctx.can('admin')):
        raise DataError('forbidden', '只有会议整理负责人可修改或定稿')


def attach_job(ctx, record, job_id):
    """调用方持有 MEETING_LOCK。队列先落盘，重启后准备步骤可补写关联。"""
    require_owner(ctx, record)
    data = record['data']
    active_id = data.get('jobId')
    if active_id == job_id:
        return
    if active_id:
        try:
            current = ctx.preview.jobs.get(active_id)
        except DataError as exc:
            if exc.code != 'not_found':
                raise
            current = None
        if current is not None and current['status'] not in {'cancelled', 'cancelling'}:
            raise DataError('invalid_state', '该会议已有转写任务，请在原任务中查看或重试')
    ctx.records.save(id=record['id'], baseVersion=record['version'], data={**data, 'jobId': job_id})


def demo_parts():
    # #35 接入后由音频分片接口返回持久片段引用和原录音偏移。
    if not DEMO_AUDIO.is_file():
        raise DataError('internal_error', '找不到演示录音')
    return [
        {'number': 1, 'offset': '00:00'},
        {'number': 2, 'offset': '00:05.716'},
    ]


def transcribe_part(part, *, hotwords, step_key):
    """#35 转写接口桩，每段结果对应同一份公开合成录音。"""
    sentences = {
        1: ('发言人 1', '我们先核对园区服务清单。请把本周收集的问题按主题归类。'),
        2: ('发言人 2', '好的。我会整理一份问题清单，周五前发给大家核对。'),
    }
    speaker, words = sentences[part['number']]
    return [[part['offset'], speaker, words]]


def publish_transcript(ctx, job_id, inputs, transcript, mode="demo"):
    with MEETING_LOCK:
        record = meeting_record(ctx, inputs.ref)
        require_owner(ctx, record)
        data = record['data']
        if data.get('jobId') != job_id:
            raise DataError('invalid_state', '转写任务与会议当前记录不一致')
        if not data.get('transcript'):
            data = {
                **data, 'title': inputs.title or data['title'], 'type': inputs.type or data['type'],
                'transcript': transcript, 'transcriptMode': mode,
            }
            ctx.records.save(id=inputs.ref, baseVersion=record['version'], data=data)
    return {'ref': inputs.ref, 'transcriptMode': mode}


@operation(OPERATION, version='1')
def transcribe(job, body):
    try:
        inputs = TranscriptionInput.model_validate(body)
    except ValidationError as exc:
        raise DataError('invalid_request', '转写参数无效') from exc
    ctx = job.context

    def prepare(_step_key):
        with MEETING_LOCK:
            record = meeting_record(ctx, inputs.ref)
            if record['project'] != job.project:
                raise DataError('not_found', '会议不存在')
            attach_job(ctx, record, job.id)
        audio = ctx.data_files.read(record['data']['fileId'])
        # 只有明确示例，或内容逐字节相同的公开合成录音，才使用示例逐字稿。
        if record['data'].get('source') == 'demo' or audio == DEMO_AUDIO.read_bytes():
            return demo_parts()
        return [{'number': 1, 'fileId': record['data']['fileId'], 'real': True}]

    parts = job.step('分片', prepare)
    transcript = []
    real = bool(parts and parts[0].get('real'))

    def recognize(part):
        if TRANSCRIBE_AUDIO is None:
            raise DataError('invalid_state', '未接入真实转写服务；录音已保留，可补录文字继续')
        result = asyncio.run(TRANSCRIBE_AUDIO(ctx.data_files.read(part['fileId'])))
        return [[f"{line['startMs']//60000:02d}:{line['startMs']//1000%60:02d}.{line['startMs']%1000:03d}",
                 line.get('speaker') or '待核对发言人', line['text']] for line in result['sentences']]

    for part in parts:
        lines = job.step(
            f"转写第 {part['number']} 片",
            lambda key: recognize(part) if real else transcribe_part(part, hotwords=inputs.hotwords, step_key=key),
        )
        transcript.extend(lines)
    return job.step('合并逐字稿', lambda _: publish_transcript(ctx, job.id, inputs, transcript, "provider" if real else "demo"))

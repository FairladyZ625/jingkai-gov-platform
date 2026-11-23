"""会议纪要与逐字稿引用。"""

from collections import defaultdict
from hashlib import sha256
import re
from typing import Annotated

from haiknow_sdk import DataError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ShortText = Annotated[Text, StringConstraints(max_length=160)]
UNCONFIRMED = '待确认'
DECISION = re.compile(r'^(?:结论|会议议定|会议决定|议定|决定)[：:]\s*(.+)|^(?:会议一致同意|会议决定|会议议定)(.+)')
ACTION = re.compile(r'^(?:待办[：:]\s*|(?:我会|我们会|请)(?=\S))(.+)')


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SpeakerEdit(Input):
    source: ShortText = Field(alias='from')
    to: ShortText


class LineEdit(Input):
    index: int = Field(strict=True, ge=0)
    text: Text


class TodoEdit(Input):
    id: ShortText
    owner: Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)] | None = None
    due: Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)] | None = None

    @model_validator(mode='after')
    def has_change(self):
        if not self.model_fields_set.intersection({'owner', 'due'}):
            raise ValueError('请填写负责人或期限')
        return self


class SectionEdit(BaseModel):
    h: ShortText
    p: Text
    refs: list[ShortText] = Field(min_length=1)


class MinutesEdit(BaseModel):
    # 接受把 GET 返回的纪要整体传回来，引用原话和待办由服务端重新计算。
    title: Annotated[Text, StringConstraints(max_length=320)]
    meta: str = ''
    attendees: str = ''
    template: str = ''
    body: list[SectionEdit] = Field(min_length=1)


class MeetingPatch(Input):
    renameSpeaker: SpeakerEdit | None = None
    todo: TodoEdit | None = None
    line: LineEdit | None = None
    minutes: MinutesEdit | None = None

    @model_validator(mode='after')
    def one_change(self):
        if sum(value is not None for value in (self.renameSpeaker, self.todo, self.line, self.minutes)) != 1:
            raise ValueError('每次只修改一类会议内容')
        return self


def require_transcript(data):
    lines = data.get('transcript') or []
    if not lines:
        raise DataError('invalid_state', '请先完成转写')
    return lines


def transcript_sources(lines):
    sources = defaultdict(list)
    for index, (ts, speaker, words) in enumerate(lines):
        sources[ts].append({'ts': ts, 'index': index, 'speaker': speaker, 'quote': words})
    return sources


def citations(sources, refs):
    """时间戳和原句均取自当前版本的逐字稿。"""
    if any(ref not in sources for ref in refs):
        raise DataError('invalid_request', '纪要引用的时间戳不在当前逐字稿中')
    return [source for ref in dict.fromkeys(refs) for source in sources[ref]]


def minutes_for(data):
    lines = data.get('transcript') or []
    if not lines:
        return None
    edited = data.get('minutesEdit')
    if edited:
        view = edited
    else:
        body = []
        for ts, speaker, words in lines:
            for sentence in re.split(r'(?<=[。！？；])', words):
                match = DECISION.search(sentence.strip())
                if match:
                    body.append({'h': '会议议定', 'p': f'{speaker}：{match[1] or match[2]}', 'refs': [ts]})
        if not body:
            body = [
                {'h': f'发言片段 {index} · {speaker}', 'p': words, 'refs': [ts]}
                for index, (ts, speaker, words) in enumerate(lines, start=1)
            ]
        view = {
            'title': f"{data['title']}纪要",
            'meta': f"时间：{data.get('date') or '—'}　地点：{data.get('place') or '—'}　主持：{data.get('host') or '—'}",
            'attendees': '、'.join(data.get('participants') or []),
            'template': data.get('type', ''),
            'body': body,
        }
    sources = transcript_sources(lines)
    return {
        **view,
        'body': [{**section, 'sources': citations(sources, section['refs'])} for section in view['body']],
        'todos': public_todos(data),
    }


def todos_for(data):
    # #36 初始记录的 todos 是空数组。首次整理时仅从明确的待办语句提取，
    # 保持候选 id 稳定，负责人和期限由经办人确认。
    if data.get('todos'):
        return data['todos']
    todos = []
    for index, (ts, _, words) in enumerate(data.get('transcript') or []):
        for part, sentence in enumerate(re.split(r'(?<=[。！？；])', words)):
            match = ACTION.match(sentence.strip())
            task = match[1].rstrip('。！？；').strip() if match else ''
            if task:
                signature = sha256(task.encode()).hexdigest()[:10]
                todos.append({
                    'id': f'TD-{index + 1}-{part + 1}-{signature}', 'task': task,
                    'owner': UNCONFIRMED, 'due': UNCONFIRMED, 'deliverable': '',
                    'ref': ts, 'status': '待认领', 'certain': False,
                })
    return todos


def public_todos(data):
    return [{key: value for key, value in todo.items() if key != 'assignment'} for todo in todos_for(data)]


def edit_minutes(data, patch):
    lines = require_transcript(data)
    if patch.renameSpeaker:
        source, target = patch.renameSpeaker.source, patch.renameSpeaker.to
        if not any(speaker == source for _, speaker, _ in lines):
            raise DataError('not_found', '逐字稿中没有该发言人')
        data['transcript'] = [[ts, target if speaker == source else speaker, words] for ts, speaker, words in lines]
        data['participants'] = list(dict.fromkeys(
            target if person == source else person for person in data.get('participants', [])
        ))
        if data.get('host') == source:
            data['host'] = target
        edited = data.get('minutesEdit')
        if edited:
            people = {speaker for _, speaker, _ in lines} | {source}
            names = re.compile('|'.join(re.escape(person) for person in sorted(filter(None, people), key=len, reverse=True)))

            def rename_mentions(text):
                return names.sub(lambda match: target if match[0] == source else match[0], text)

            for field in ('title', 'meta', 'attendees'):
                edited[field] = rename_mentions(edited[field])
            for section in edited['body']:
                for field in ('h', 'p'):
                    section[field] = rename_mentions(section[field])
    elif patch.line:
        index = patch.line.index
        if index >= len(lines):
            raise DataError('not_found', '逐字稿行不存在')
        ts, speaker, old_text = lines[index]
        lines[index] = [ts, speaker, patch.line.text]
        if data.get('minutesEdit') and old_text != patch.line.text:
            for section in data['minutesEdit']['body']:
                if ts in section['refs']:
                    section['needsReview'] = True
    elif patch.minutes:
        sources = transcript_sources(lines)
        for section in patch.minutes.body:
            citations(sources, section.refs)
        data['minutesEdit'] = patch.minutes.model_dump()
    else:
        edit = patch.todo
        todos = todos_for(data)
        todo = next((item for item in todos if item['id'] == edit.id), None)
        if todo is None:
            raise DataError('not_found', '会议待办不存在')
        if todo['status'] == '已派发':
            raise DataError('invalid_state', '待办已派发，无法修改')
        for key, value in edit.model_dump(exclude_unset=True, exclude={'id'}).items():
            todo[key] = value or UNCONFIRMED
        todo['certain'] = bool(todo['owner'] not in ('', UNCONFIRMED) and todo['due'] not in ('', UNCONFIRMED))
        data['todos'] = todos

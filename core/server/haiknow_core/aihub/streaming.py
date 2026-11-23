"""平台内部 OpenAI 工具流：不向编排进程传凭据或服务商错误正文。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from threading import Event
from typing import Callable, Generic, TypeVar

import httpx
from anyio import create_task_group, sleep

from .config import auth_headers
from .errors import AIError, TRANSPORT_ERRORS, transport_error


Chunk = TypeVar('Chunk')
MOCK_CONTENT = '[模拟模型] 已收到输入。'
SUCCESSFUL_FINISH_REASONS = ('stop', 'length', 'content_filter', 'tool_calls', 'function_call')


@dataclass
class Channel(Generic[Chunk]):
    emit: Callable[[Chunk], None]
    cancelled: Event
    started: bool = False

    def send(self, data: Chunk) -> None:
        self.started = True
        self.emit(data)


class ChatRequest(dict):
    """结构化消息调用。流式通道和工具校验只在网关内部使用。"""

    def __init__(self, payload, events=None, *, validate_tool_call=None):
        super().__init__(payload)
        self.events = events
        self.validate_tool_call = validate_tool_call

    def validate_message(self, message):
        if self.validate_tool_call is not None:
            for call in message['tool_calls']:
                try:
                    self.validate_tool_call(call)
                except AIError as error:
                    error.retryable = False
                    raise
        return message


def chat_message(message):
    if not isinstance(message, dict):
        raise ValueError('无效对话消息')
    content = message.get('content')
    calls = message.get('tool_calls')
    if calls is None:
        calls = []
    if (content is not None and not isinstance(content, str)) or not isinstance(calls, list):
        raise ValueError('无效对话消息')
    tool_calls = []
    for call in calls:
        function = call['function']
        name, arguments = function['name'], json.loads(function['arguments'])
        if not isinstance(name, str) or not name or not isinstance(arguments, dict):
            raise ValueError('无效工具调用')
        # json.loads 也接受 NaN 和 Infinity，但它们不是有效的 SSE JSON。
        json.dumps(arguments, allow_nan=False)
        tool_calls.append({'name': name, 'arguments': arguments})
    if content is None and not tool_calls:
        raise ValueError('对话消息没有内容或工具调用')
    return {'content': content, 'tool_calls': tool_calls}


def chat_usage(usage):
    usage = usage if isinstance(usage, dict) else {}
    return {key: value if type(value) is int and value >= 0 else None
            for key, value in (('input', usage.get('prompt_tokens')), ('output', usage.get('completion_tokens')))}


def mock_message(provider):
    return provider.get('chat_script', {'content': MOCK_CONTENT})


def _sse(delta, finish=None):
    return 'data: ' + json.dumps({'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]},
                                 ensure_ascii=False) + '\n\n'


async def request(provider, model, payload, timeout, channel: Channel[str], *,
                  transport=None, trust_env=None, on_start=None):
    if channel.cancelled.is_set():
        raise AIError('timeout', '本轮已中断。')

    def start():
        if not channel.started:
            channel.started = True
            if on_start is not None:
                on_start()

    if provider['kind'] == 'mock':
        message = mock_message(provider)
        start()
        channel.send(_sse({'content': message.get('content')}))
        calls = message.get('tool_calls') or []
        if calls:
            channel.send(_sse({'tool_calls': [{**call, 'index': i} for i, call in enumerate(calls)]}))
        channel.send(_sse({}, 'tool_calls' if calls else 'stop'))
        channel.send('data: [DONE]\n\n')
        return None
    if provider['kind'] not in ('ark', 'openai', 'deepseek', 'local'):
        raise AIError('provider_error', '当前服务商不支持原生工具流。')

    if trust_env is None:
        trust_env = provider['kind'] != 'local'

    async def read():
        complete = False
        # classification 只用于平台出站策略，不传上游；路由模型始终由能力中心决定。
        body = {k: v for k, v in payload.items() if k not in ('classification', 'model', 'stream')}
        request_options = body.pop('stream_options', None)
        stream_options = request_options.copy() if isinstance(request_options, dict) else {}
        stream_options.pop('include_usage', None)
        if provider.get('stream_usage', provider['kind'] in ('openai', 'deepseek', 'local')):
            stream_options['include_usage'] = True
        if stream_options:
            body['stream_options'] = stream_options
        options = {'transport': transport} if transport is not None else {}
        async with httpx.AsyncClient(timeout=timeout, trust_env=trust_env, **options) as client:
            async with client.stream('POST', provider['base_url'] + '/chat/completions',
                                     headers=auth_headers(provider),
                                     json={**body, 'model': model, 'stream': True}) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    data = line[5:].strip()
                    if data == '[DONE]':
                        break
                    try:
                        value = json.loads(data)
                        if not isinstance(value, dict):
                            raise ValueError('无效流')
                    except ValueError:
                        raise AIError('provider_error', '模型服务商流式响应格式无效。') from None
                    if 'error' in value:
                        start()
                        raise AIError('provider_error', '模型服务商中断了流式生成。')
                    choices = value.get('choices')
                    if not isinstance(choices, list) or any(
                        not isinstance(choice, dict)
                        or (not isinstance(choice.get('delta'), dict) and choice.get('finish_reason') is None)
                        for choice in choices
                    ):
                        raise AIError('provider_error', '模型服务商流式响应格式无效。')
                    if choices:
                        start()
                        reasons = [choice.get('finish_reason') for choice in choices]
                        if any(reason is not None and reason not in SUCCESSFUL_FINISH_REASONS for reason in reasons):
                            raise AIError('provider_error', '模型服务商中断了流式生成。')
                        complete |= any(reason in SUCCESSFUL_FINISH_REASONS for reason in reasons)
                    # 空 choices 的用量块不能确定上游已经开始生成。
                    if channel.started:
                        channel.send('data: ' + data + '\n\n')
        if not complete:
            raise AIError('provider_error', '模型流在完成前中断，已收到的进展已保留。')
        channel.send('data: [DONE]\n\n')

    async def monitor(group):
        while not channel.cancelled.is_set():
            await sleep(0.1)
        group.cancel_scope.cancel()

    error = None
    try:
        async with create_task_group() as group:
            group.start_soon(monitor, group)
            try:
                await read()
            except Exception as exc:
                error = exc
            finally:
                group.cancel_scope.cancel()
        if channel.cancelled.is_set():
            raise AIError('timeout', '本轮已中断。')
        if error is not None:
            raise error
    except httpx.TimeoutException:
        raise AIError('timeout', '模型调用超时。') from None
    except (httpx.TransportError, *TRANSPORT_ERRORS):
        raise transport_error('模型服务连接中断，请稍后继续。') from None
    except httpx.HTTPStatusError as exc:
        error = AIError('provider_error', '模型服务商调用失败，请检查配置或稍后重试。')
        error.status_code = exc.response.status_code
        error.retryable = error.status_code >= 500
        raise error from None


async def chat_events(provider, model, payload, timeout, events, *, route_note='', **options):
    """文本即时交付，工具参数按索引拼接，收到完成帧后才交付完整调用。"""
    text = []
    fragments = {}
    usage = chat_usage(None)
    meta = {'model': model, 'routeNote': route_note}

    def start():
        if not events.started:
            events.send(('meta', meta))

    def receive(frame):
        nonlocal usage
        if frame == 'data: [DONE]\n\n':
            return
        chunk = json.loads(frame[5:])
        if chunk.get('usage') is not None:
            usage = chat_usage(chunk['usage'])
        for choice in chunk['choices']:
            if choice.get('index', 0) != 0:
                continue
            delta = choice.get('delta') or {}
            content = delta.get('content')
            if content:
                if not isinstance(content, str):
                    raise ValueError('无效文本增量')
                text.append(content)
                events.send(('delta', {'text': content}))
            for call in delta.get('tool_calls') or []:
                index = call['index']
                if type(index) is not int or index < 0:
                    raise ValueError('无效工具索引')
                function = fragments.setdefault(index, {'name': '', 'arguments': ''})
                for key, value in (call.get('function') or {}).items():
                    if key in function and value is not None:
                        function[key] += value

    try:
        await request(provider, model, payload, timeout, Channel(receive, events.cancelled),
                      on_start=start, **options)
        message = chat_message({
            'content': ''.join(text) if text or not fragments else None,
            'tool_calls': [{'function': function} for _, function in sorted(fragments.items())],
        })
    except (ValueError, KeyError, TypeError, AttributeError):
        raise AIError('provider_error', '模型服务商流式响应格式无效。') from None
    payload.validate_message(message)
    for call in message['tool_calls']:
        events.send(('tool', call))
    if provider['kind'] == 'mock':
        usage = {'input': 0, 'output': 0}
    return {**message, 'usage': usage, 'mock': provider['kind'] == 'mock'}

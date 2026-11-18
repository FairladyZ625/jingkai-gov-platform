"""平台内部 OpenAI 工具流：不向编排进程传凭据或服务商错误正文。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from threading import Event
from typing import Callable

import httpx
from anyio import create_task_group, sleep

from .errors import AIError, TRANSPORT_ERRORS, transport_error


@dataclass
class Channel:
    emit: Callable[[str], None]
    cancelled: Event
    started: bool = False

    def send(self, data: str) -> None:
        self.started = True
        self.emit(data)


def _sse(delta, finish=None):
    return 'data: ' + json.dumps({'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]},
                                 ensure_ascii=False) + '\n\n'


async def request(provider, model, payload, timeout, channel: Channel):
    if channel.cancelled.is_set():
        raise AIError('timeout', '本轮已中断。')
    if provider['kind'] == 'mock':
        channel.send(_sse({'content': '[模拟模型] 已收到输入。'}))
        channel.send(_sse({}, 'stop'))
        channel.send('data: [DONE]\n\n')
        return None
    if provider['kind'] not in ('ark', 'openai', 'deepseek'):
        raise AIError('provider_error', '当前服务商不支持原生工具流。')

    async def read():
        complete = False
        # classification 只用于平台出站策略，不传上游；路由模型始终由能力中心决定。
        body = {k: v for k, v in payload.items() if k not in ('classification', 'model', 'stream')}
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream('POST', provider['base_url'] + '/chat/completions',
                                     headers={'Authorization': 'Bearer ' + provider['api_key']},
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
                        if not isinstance(value, dict) or 'error' in value or not isinstance(value.get('choices'), list):
                            raise ValueError('无效流')
                        complete |= any(c.get('finish_reason') is not None for c in value['choices'])
                    except (ValueError, TypeError, AttributeError):
                        raise AIError('provider_error', '模型服务商流式响应格式无效。') from None
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
        raise error from None

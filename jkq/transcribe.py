"""经开区转写入口，供 §3.2 路由和 #36 会议长任务复用。"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from haiknow_core.aihub.api import TranscribeBody
from haiknow_core.aihub.transcribe import (
    DEFAULT_TIMEOUT, FunASRProvider, Sentence, TranscribeProvider, merge_transcripts, transcribe_chunk,
)
from haiknow_core.aihub.transcribe_audio import SAMPLE_RATE, TranscribeError, split_audio
from haiknow_core.main import current_user

DEFAULT_HOTWORDS = (
    '北京经济技术开发区管理委员会',
    '北京经济技术开发区行政审批局',
    '北京经济技术开发区营商合作局',
    '北京经济技术开发区促进高精尖产业发展政策',
)

# 公开演示用节选。预置结果使用自己的时间轴，与上传的音频无关。
_PRESET = (
    Sentence('今天开始北京经济技术开发区共享智能体工作站的公开演示。', 0, 6800, 'S1'),
    Sentence('北京经济技术开发区行政审批局的演示条目已经准备好。', 38000, 44000, 'S2'),
    Sentence('北京经济技术开发区营商合作局是本段热词。', 73000, 79000, 'S1'),
    Sentence('第一轮查看逐字稿，重点核对机构名、政策名以及发言归属。', 106000, 113000, 'S2'),
    Sentence('北京经济技术开发区促进高精尖产业发展政策是演示词表中的一项。', 139000, 147000, 'S1'),
    Sentence('本次演示录音到此结束。', 189000, 193000, 'S2'),
)
_PRESET_DURATION_MS = 203625

CloudProviderFactory = Callable[[str, str, str], TranscribeProvider]


@dataclass(frozen=True)
class Transcriber:
    source: str
    provider: TranscribeProvider | None = None
    hotwords: tuple[str, ...] = DEFAULT_HOTWORDS
    timeout: float = DEFAULT_TIMEOUT

    def preset_result(self, chunks):
        return self._result(chunks, _PRESET, duration_ms=_PRESET_DURATION_MS)

    async def transcribe_chunk(self, chunk):
        """供 #36 将单片重试置于独立的长任务检查点。"""
        if self.provider is None:
            raise ValueError('预置模式请使用 preset_result。')
        return await transcribe_chunk(self.provider, chunk, self.hotwords, timeout=self.timeout)

    def merge(self, parts):
        return self._result([chunk for chunk, _ in parts], merge_transcripts(parts))

    def _result(self, chunks, sentences, *, duration_ms=None):
        if duration_ms is None:
            frames = max(chunk.offset_frames + chunk.frames for chunk in chunks)
            duration_ms = (frames * 1000 + SAMPLE_RATE - 1) // SAMPLE_RATE
        return {
            'source': self.source,
            'mock': self.provider is None,
            'durationMs': duration_ms,
            'chunkCount': len(chunks),
            'sentences': [
                {'text': s.text, 'startMs': s.start_ms, 'endMs': s.end_ms, 'speaker': s.speaker}
                for s in sentences
            ],
        }

    async def transcribe(self, audio: bytes):
        chunks = await run_in_threadpool(split_audio, audio)
        if self.provider is None:
            return self.preset_result(chunks)
        parts = [(chunk, await self.transcribe_chunk(chunk)) for chunk in chunks]
        return self.merge(parts)


def _not_configured(message):
    return TranscribeError(503, 'TRANSCRIBE_NOT_CONFIGURED', message)


def transcriber_from_environment(
    *,
    classification='internal',
    cloud_providers: Mapping[str, CloudProviderFactory] | None = None,
    transport=None,
):
    mode = os.getenv('JKQ_TRANSCRIBE_MODE', 'local').strip()
    if mode == 'mock':
        return Transcriber('preset')
    if mode not in ('local', 'cloud'):
        raise _not_configured('转写模式配置无效，请联系管理员。')

    prefix = 'JKQ_TRANSCRIBE_' + mode.upper()
    api_key = os.getenv(f'{prefix}_API_KEY', '').strip()
    if not api_key:
        return Transcriber('preset')
    if not all(33 <= ord(char) <= 126 for char in api_key):
        raise _not_configured('转写服务密钥格式无效，请联系管理员。')

    if mode == 'cloud':
        if classification == 'confidential':
            raise TranscribeError(403, 'OUTBOUND_DENIED', '机密录音只能使用内网转写服务。')
        kind = os.getenv(f'{prefix}_PROVIDER', '').strip()
        factory = (cloud_providers or {}).get(kind)
        if factory is None:
            raise _not_configured('云端转写服务暂未接入，请使用内网转写。')

    url = os.getenv(f'{prefix}_URL', '').strip()
    model = os.getenv(f'{prefix}_MODEL', '').strip()
    try:
        endpoint = httpx.URL(url)
    except (httpx.InvalidURL, ValueError):
        raise _not_configured('转写服务地址无效，请联系管理员。') from None
    schemes = {'https'} if mode == 'cloud' else {'http', 'https'}
    if endpoint.scheme not in schemes or not endpoint.host or endpoint.userinfo or endpoint.query or endpoint.fragment:
        raise _not_configured('转写服务地址无效，请联系管理员。')
    if not model:
        raise _not_configured('尚未配置转写模型，请联系管理员。')
    try:
        timeout = float(os.getenv('JKQ_TRANSCRIBE_TIMEOUT_SECONDS', str(DEFAULT_TIMEOUT)))
    except ValueError:
        raise _not_configured('转写超时配置无效，请联系管理员。') from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise _not_configured('转写超时配置无效，请联系管理员。')

    extra_hotwords = os.getenv('JKQ_TRANSCRIBE_HOTWORDS', '').splitlines()
    hotwords = tuple(dict.fromkeys([*DEFAULT_HOTWORDS, *(word.strip() for word in extra_hotwords if word.strip())]))
    provider = FunASRProvider(str(endpoint), model, api_key, transport=transport) if mode == 'local' else factory(
        str(endpoint), model, api_key,
    )
    return Transcriber(mode, provider, hotwords, timeout)


router = APIRouter()


@router.post('/api/v1/ai/transcribe')
async def transcribe_file(body: TranscribeBody, request: Request, user=Depends(current_user)):
    platform = request.app.state.platform
    await run_in_threadpool(platform.data.app, user, body.appId, 'operate')
    audio = await run_in_threadpool(platform.data.read_file, user, body.fileId)
    audit = {'fileId': body.fileId, 'status': 'failed'}
    try:
        transcriber = transcriber_from_environment(
            classification=body.classification,
            cloud_providers=getattr(request.app.state, 'transcribe_cloud_providers', None),
        )
        audit['source'] = transcriber.source
        result = await transcriber.transcribe(audio)
        audit['status'] = 'success'
        return result
    except TranscribeError as error:
        audit['status'] = error.code
        raise
    finally:
        await run_in_threadpool(platform.store.audit, body.appId, user.id, 'ai.transcribe', audit)

"""厂商无关的分片转写契约与内网 FunASR HTTP 适配器。"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Protocol

import httpx
from anyio import fail_after

from .errors import AIError, TRANSPORT_ERRORS
from .transcribe_audio import AudioChunk, TranscribeError

RETRIES = 3
DEFAULT_TIMEOUT = 300.0


@dataclass(frozen=True)
class Sentence:
    text: str
    start_ms: int
    end_ms: int
    speaker: str


class TranscribeProvider(Protocol):
    async def transcribe(self, audio: bytes, hotwords: tuple[str, ...]) -> list[Sentence]:
        """转写一段 WAV，返回片内毫秒与片内说话人标识；失败时抛出 AIError。"""
        ...


def _parse_sentences(body):
    if type(body['code']) is not int or body['code'] != 0 or not isinstance(body['sentences'], list):
        raise ValueError('转写服务响应无效。')
    sentences = []
    for item in body['sentences']:
        text, start, end, speaker = item['text'], item['start'], item['end'], item['spk']
        if (
            not isinstance(text, str) or not text.strip()
            or type(start) is not int or type(end) is not int or not 0 <= start < end
            or type(speaker) not in (str, int) or not str(speaker).strip()
        ):
            raise ValueError('转写分句无效。')
        sentences.append(Sentence(text.strip(), start, end, str(speaker)))
    return sentences


class FunASRProvider:
    def __init__(self, url, model, api_key, *, transport=None):
        self.url = url
        self.model = model
        self._api_key = api_key
        self._transport = transport

    async def transcribe(self, audio, hotwords):
        try:
            async with httpx.AsyncClient(
                transport=self._transport, trust_env=False, follow_redirects=False, timeout=None,
            ) as client:
                response = await client.post(
                    self.url,
                    headers={'Authorization': 'Bearer ' + self._api_key},
                    data={'model': self.model, 'hotword': ' '.join(hotwords)},
                    files={'audio': ('audio.wav', audio, 'audio/wav')},
                )
            response.raise_for_status()
            return _parse_sentences(response.json())
        except httpx.TimeoutException:
            raise AIError('timeout', '内网转写服务超时。') from None
        except (httpx.HTTPError, *TRANSPORT_ERRORS):
            raise AIError('provider_error', '内网转写服务调用失败。') from None
        except (ValueError, KeyError, TypeError):
            raise AIError('provider_error', '内网转写服务返回了无效分句。') from None


async def transcribe_chunk(provider: TranscribeProvider, chunk: AudioChunk, hotwords=(), *, timeout=DEFAULT_TIMEOUT):
    """首调失败后重试三次，只重跑当前片。"""
    for attempt in range(RETRIES + 1):
        try:
            with fail_after(timeout):
                sentences = await provider.transcribe(chunk.data, tuple(hotwords))
            if any(sentence.end_ms > chunk.duration_ms for sentence in sentences):
                raise AIError('provider_error', '转写时间超出分片时长。')
            return sentences
        except TimeoutError:
            timed_out = True
        except AIError as error:
            if error.kind not in ('timeout', 'provider_error'):
                raise
            timed_out = error.kind == 'timeout'
        if attempt < RETRIES:
            continue
        if timed_out:
            raise TranscribeError(504, 'TRANSCRIBE_TIMEOUT', '语音转写服务超时，请稍后重试。', attempts=attempt + 1)
        raise TranscribeError(502, 'TRANSCRIBE_PROVIDER_ERROR', '语音转写服务暂时不可用，请稍后重试。', attempts=attempt + 1)


def _normalized(text):
    return ''.join(
        char for char in unicodedata.normalize('NFKC', text).casefold()
        if not char.isspace() and not unicodedata.category(char).startswith('P')
    )


def _overlap_duplicate(left, right):
    overlap = min(left.end_ms, right.end_ms) - max(left.start_ms, right.start_ms)
    shorter = min(left.end_ms - left.start_ms, right.end_ms - right.start_ms)
    left_text = _normalized(left.text)
    return overlap > 0 and 2 * overlap >= shorter and left_text and left_text == _normalized(right.text)


def merge_transcripts(parts: list[tuple[AudioChunk, list[Sentence]]]) -> list[Sentence]:
    """按采样偏移合并。只删除音频重叠区中相同的句子，借匹配句对齐局部说话人。"""
    merged = []
    boundary = []
    next_speaker = 1
    for chunk, sentences in sorted(parts, key=lambda part: part[0].offset_frames):
        absolute = [
            Sentence(s.text, s.start_ms + chunk.offset_ms, s.end_ms + chunk.offset_ms, s.speaker)
            for s in sorted(sentences, key=lambda s: (s.start_ms, s.end_ms))
        ]
        boundary = [s for s in boundary if s.end_ms > chunk.offset_ms]
        duplicates = set()
        speaker_candidates = {}
        for index, sentence in enumerate(absolute):
            for previous in boundary:
                if _overlap_duplicate(previous, sentence):
                    duplicates.add(index)
                    speaker_candidates.setdefault(sentence.speaker, set()).add(previous.speaker)
                    break
        speakers = {speaker: next(iter(matches)) for speaker, matches in speaker_candidates.items() if len(matches) == 1}
        for index, sentence in enumerate(absolute):
            if sentence.speaker not in speakers:
                speakers[sentence.speaker] = f'S{next_speaker}'
                next_speaker += 1
            if index in duplicates:
                continue
            resolved = Sentence(sentence.text, sentence.start_ms, sentence.end_ms, speakers[sentence.speaker])
            merged.append(resolved)
            boundary.append(resolved)
    return sorted(merged, key=lambda s: (s.start_ms, s.end_ms))

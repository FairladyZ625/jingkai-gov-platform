"""转写专用音频读取、标准化和分片。"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from haiknow_sdk.resources import DataError

from .gateway import TRANSCRIBE_MAX_BYTES, audio_mime

SAMPLE_RATE = 16000
SAMPLE_BYTES = 2
WAV_HEADER_BYTES = 44
OVERLAP_FRAMES = 2 * SAMPLE_RATE

_INPUT_FORMATS = {
    'audio/wav': 'wav',
    'audio/webm': 'matroska',
    'audio/mp4': 'mov',
    'audio/ogg': 'ogg',
    'audio/mpeg': 'mp3',
    'audio/flac': 'flac',
}


class TranscribeError(DataError):
    def __init__(self, status, code, message, **details):
        super().__init__(code, message)
        self.status = status
        self.error = {'code': code, 'message': message, 'details': details}


def _unsupported_audio():
    return TranscribeError(415, 'UNSUPPORTED_TYPE', '无法读取音频，请上传有效的 WAV、WebM、M4A、OGG、MP3 或 FLAC 文件。')


def _format(audio):
    mime = audio_mime(audio)
    if audio.startswith(b'fLaC'):
        mime = 'audio/flac'
    elif audio.startswith(b'ID3') or (
        len(audio) >= 2 and audio[0] == 0xff and audio[1] & 0xe0 == 0xe0 and audio[1] & 0x06
    ):
        mime = 'audio/mpeg'
    if mime not in _INPUT_FORMATS:
        raise _unsupported_audio()
    return _INPUT_FORMATS[mime]


def _normal_wav(audio):
    with wave.open(io.BytesIO(audio), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, SAMPLE_BYTES, SAMPLE_RATE):
            return None
        frames = wav.getnframes()
        data = wav.readframes(frames)
        if len(data) != frames * SAMPLE_BYTES:
            raise _unsupported_audio()
        return data


def _pcm(audio):
    demuxer = _format(audio)
    if demuxer == 'wav':
        try:
            pcm = _normal_wav(audio)
        except (EOFError, wave.Error):
            pcm = None
        if pcm is not None:
            return pcm
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg is None:
        raise TranscribeError(503, 'TRANSCRIBE_NOT_CONFIGURED', '转写服务缺少音频解码工具，请联系管理员。')
    try:
        # 可寻址的输入支持索引位于尾部的 M4A。显式选择解码器并禁止网络协议。
        with TemporaryDirectory(prefix='jkq-transcribe-') as tmp:
            source = Path(tmp) / 'input'
            source.write_bytes(audio)
            result = subprocess.run(
                [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-xerror',
                 '-protocol_whitelist', 'file', '-f', demuxer, '-i', str(source),
                 '-map', '0:a:0', '-ac', '1', '-ar', str(SAMPLE_RATE),
                 '-f', 's16le', '-acodec', 'pcm_s16le', 'pipe:1'],
                capture_output=True, check=True, timeout=120,
                env={name: os.environ[name] for name in ('PATH', 'LANG') if name in os.environ},
            )
    except subprocess.CalledProcessError:
        raise _unsupported_audio() from None
    except (OSError, subprocess.TimeoutExpired):
        raise TranscribeError(503, 'TRANSCRIBE_NOT_CONFIGURED', '音频解码服务暂时不可用，请联系管理员。') from None
    return result.stdout


def _wav(pcm):
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setparams((1, SAMPLE_BYTES, SAMPLE_RATE, 0, 'NONE', 'not compressed'))
        wav.writeframes(pcm)
    return output.getvalue()


@dataclass(frozen=True)
class AudioChunk:
    offset_frames: int
    frames: int
    data: bytes

    @property
    def offset_ms(self):
        return self.offset_frames * 1000 // SAMPLE_RATE

    @property
    def duration_ms(self):
        # 一帧不足 1 ms，向上取整以包住音频尾帧。
        return (self.frames * 1000 + SAMPLE_RATE - 1) // SAMPLE_RATE


def split_audio(audio: bytes, *, max_bytes: int = TRANSCRIBE_MAX_BYTES) -> tuple[AudioChunk, ...]:
    """返回有绝对采样帧偏移、可独立提交给模型的 PCM WAV 分片。"""
    if not WAV_HEADER_BYTES + SAMPLE_BYTES <= max_bytes <= TRANSCRIBE_MAX_BYTES:
        raise ValueError('转写分片上限无效。')
    pcm = _pcm(audio)
    frames = len(pcm) // SAMPLE_BYTES
    if not frames or len(pcm) % SAMPLE_BYTES:
        raise _unsupported_audio()

    capacity = (max_bytes - WAV_HEADER_BYTES) // SAMPLE_BYTES
    if frames <= capacity and len(audio) <= max_bytes:
        return (AudioChunk(0, frames, _wav(pcm)),)
    # 原始文件过大时，即使转为单声道后体积缩小，也保留至少两个有效分片。
    stride = min(capacity - min(OVERLAP_FRAMES, capacity // 4), max(1, (frames + 1) // 2))
    overlap = min(OVERLAP_FRAMES, stride // 4, capacity - stride)
    step = []
    for offset in range(0, frames, stride):
        end = min(offset + stride + overlap, frames)
        step.append(AudioChunk(offset, end - offset, _wav(pcm[offset * SAMPLE_BYTES:end * SAMPLE_BYTES])))
    return tuple(step)

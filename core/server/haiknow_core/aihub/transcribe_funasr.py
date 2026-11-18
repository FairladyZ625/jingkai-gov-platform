"""可选内网 FunASR 服务。平台与 CI 无需安装模型运行依赖。"""

from __future__ import annotations

import io
import os
import secrets
import wave
from threading import Lock

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

from .transcribe import _parse_sentences
from .transcribe_audio import SAMPLE_BYTES, SAMPLE_RATE, TRANSCRIBE_MAX_BYTES


def _required(suffix):
    name = f'JKQ_TRANSCRIBE_LOCAL_{suffix}'
    value = os.getenv(name, '').strip()
    if not value:
        raise RuntimeError(f'缺少内网转写配置 {name}。')
    return value


def _speech(engine, audio, hotword):
    # FastAPI 工作线程读取 WAV，本服务仅接受平台已标准化的单声道 PCM。
    import numpy as np

    with wave.open(io.BytesIO(audio), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, SAMPLE_BYTES, SAMPLE_RATE):
            raise ValueError('无效的内网音频格式。')
        frame_count = wav.getnframes()
        pcm = wav.readframes(frame_count)
    if not frame_count or len(pcm) != frame_count * SAMPLE_BYTES:
        raise ValueError('音频为空或不完整。')
    samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
    result = engine.generate(input=samples, hotword=hotword, disable_pbar=True)[0]
    # FunASR 静音结果可能没有 sentence_info。模型有文字时必须提供真实时间和说话人。
    sentences = result['sentence_info'] if result['text'].strip() else []
    return {'code': 0, 'sentences': [
        {'text': row['text'], 'start': row['start'], 'end': row['end'], 'spk': row['spk']}
        for row in sentences
    ]}


def create_app():
    model = _required('MODEL')
    api_key = _required('API_KEY')
    model_settings = {name.lower(): _required(name) for name in ('VAD_MODEL', 'PUNC_MODEL', 'SPK_MODEL')}

    from funasr import AutoModel

    engine = AutoModel(
        model=model, **model_settings, device=os.getenv('JKQ_TRANSCRIBE_LOCAL_DEVICE', 'cpu'),
        disable_update=True, trust_remote_code=False,
    )
    app = FastAPI(title='经开区内网转写')
    # FunASR AutoModel 在 generate 中更新实例配置，多进程部署时各进程独享模型。
    inference = Lock()
    expected_auth = ('Bearer ' + api_key).encode()

    @app.post('/recognition')
    def recognition(
        audio: UploadFile = File(...), model_name: str = Form(alias='model'),
        hotword: str = Form(default=''), authorization: str = Header(default=''),
    ):
        if not secrets.compare_digest(authorization.encode(), expected_auth):
            raise HTTPException(401, '内网转写鉴权失败。')
        if model_name != model:
            raise HTTPException(400, '内网服务未加载该转写模型。')
        content = audio.file.read(TRANSCRIBE_MAX_BYTES + 1)
        if len(content) > TRANSCRIBE_MAX_BYTES:
            raise HTTPException(413, '音频分片超出 20 MiB。')
        try:
            with inference:
                response = _speech(engine, content, hotword)
            _parse_sentences(response)
            return response
        except (ValueError, KeyError, TypeError, IndexError, wave.Error, EOFError):
            raise HTTPException(422, '音频或内网模型的分句结果无效。') from None

    return app

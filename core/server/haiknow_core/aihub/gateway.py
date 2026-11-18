"""统一能力调用、兜底和用量。"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import shutil
import struct
import time

import httpx
from anyio import fail_after
from anyio.from_thread import start_blocking_portal

from . import adapters, codex, streaming
from .config import ENVIRONMENT_PROVIDER, auth_headers, provider_available
from .errors import AIError, TRANSPORT_ERRORS, mentions_model, transport_error

CAPABILITIES = {'chat', 'image', 'transcribe', 'speech', 'embedding', 'parse', 'search', 'fetch', 'vision'}
# 服务商类型支持哪些能力。管理接口保存路由与网关调用前都读这张表：
# 新增服务商类型、新增能力时只改这里，规则不再散落在各适配器里。
CAPABILITY_SUPPORT = {
    'mock': CAPABILITIES,
    'ark': {'chat', 'image', 'transcribe', 'speech', 'embedding', 'vision'},
    'openai': {'chat', 'image', 'transcribe', 'speech', 'embedding', 'vision'},
    'local': {'chat', 'image', 'transcribe', 'speech', 'embedding', 'vision'},
    'codex-cli': {'chat'},
    'deepseek': {'chat', 'search', 'vision'},
    'mineru': {'parse'},
    'builtin': {'fetch'},
}
FILE_CAPABILITIES = {'parse', 'vision', 'transcribe'}
OUTBOUND_CAPABILITIES = {'chat', 'image', 'transcribe', 'speech', 'embedding', 'parse', 'search', 'fetch', 'vision'}
CLASSIFICATIONS = ('public', 'internal', 'confidential')
DEFAULT_CLASSIFICATION = 'internal'
TRANSCRIBE_MAX_BYTES = 20 * 1024 * 1024
REQUIRED = {
    'chat': 'messages', 'image': 'prompt', 'transcribe': 'audio_base64', 'speech': 'input',
    'embedding': 'input', 'parse': 'file_id', 'search': 'query', 'fetch': 'url', 'vision': 'file_id',
}

# 一键测试：每种能力用最小样例真实调用一次，超时压到 15 秒，避免管理员在后台干等。
TEST_TIMEOUT = 15
TEST_ORDER = ('chat', 'image', 'transcribe', 'speech', 'embedding', 'parse', 'search', 'fetch', 'vision')


def _sample_wav():
    """0.1 秒静音 WAV：足够让转写接口完成一次真实请求，又几乎不花额度。"""
    data = b'\x80' * 800
    header = (b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVEfmt '
              + struct.pack('<IHHIIHH', 16, 1, 1, 8000, 8000, 1, 8) + b'data' + struct.pack('<I', len(data)))
    return header + data


def _sample_pdf():
    """一页最小合法 PDF：文档解析测试用，不依赖平台文件或样例数据。"""
    content = b'BT /F1 12 Tf 20 100 Td (HAiKnow connectivity test) Tj ET'
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R '
        b'/Resources << /Font << /F1 5 0 R >> >> >>',
        b'<< /Length %d >>\nstream\n' % len(content) + content + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    out = bytearray(b'%PDF-1.4\n')
    offsets = []
    for index, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b'%d 0 obj\n' % index + body + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1)
    out += b''.join(b'%010d 00000 n \n' % offset for offset in offsets)
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref)
    return bytes(out)


TEST_SAMPLES = {
    'chat': {'messages': [{'role': 'user', 'content': '连通测试：请回复“收到”。'}]},
    'image': {'prompt': '一张用于平台连通测试的纯色小图'},
    'transcribe': {'audio_base64': base64.b64encode(_sample_wav()).decode()},
    'speech': {'input': '连通测试'},
    'embedding': {'input': '连通测试'},
    'parse': {'file_id': 'sample-document'},
    'search': {'query': '连通测试'},
    'fetch': {'url': 'https://example.com/'},
    'vision': {'file_id': 'sample-image', 'instruction': '用一句话描述图片内容。'},
}
TEST_ASSETS = {
    'parse': ('连通测试.pdf', _sample_pdf()),
    'vision': ('连通测试.png', base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')),
}

FETCH_FAILURE_MESSAGES = {
    'not_found': '目标网页不存在，请检查网址。',
    'blocked': '目标网站拒绝访问或需要人机验证，请稍后重试。',
    'no_content': '目标网页没有可读正文。',
    'http_error': '目标网站返回错误，请稍后重试。',
    'unsupported_content_type': '目标网页类型不支持读取。',
    'redirect_limit': '目标网页跳转次数过多。',
}


def _rank(classification):
    return CLASSIFICATIONS.index(classification)


def allowed_outbound(provider, classification):
    """服务商的出站上限（未配置按 internal）；超出即拒绝。"""
    limit = provider.get('allow_outbound') or DEFAULT_CLASSIFICATION
    return _rank(limit) >= _rank(classification)


def _test_summary(capability, result):
    """一次成功测试的中文结论：说清返回了什么，不暴露上游原始响应。"""
    if capability == 'image':
        count = len(result) if isinstance(result, list) else 0
        return f'生成图片成功，返回 {count} 张图。' if count else '生成图片成功，但服务商没有返回图片。'
    if capability == 'chat':
        return '对话调用成功，已收到回复。'
    if capability == 'transcribe':
        return f'语音转写成功，返回 {len(result)} 个字。' if isinstance(result, str) else '语音转写成功。'
    if capability == 'speech':
        return '语音合成成功，已返回音频数据。'
    if capability == 'embedding':
        return f'向量计算成功，返回 {len(result)} 个向量。' if isinstance(result, list) else '向量计算成功。'
    if capability == 'parse':
        pages = result.get('totalPages', 0) if isinstance(result, dict) else 0
        blocks = len(result.get('blocks') or []) if isinstance(result, dict) else 0
        return f'文档解析成功，共 {pages} 页、{blocks} 个区块。'
    if capability == 'search':
        count = len(result.get('results') or []) if isinstance(result, dict) else 0
        return f'网络搜索成功，返回 {count} 条结果。'
    if capability == 'fetch':
        length = len(result.get('text') or '') if isinstance(result, dict) else 0
        return f'网页读取成功，正文 {length} 字。'
    if capability == 'vision':
        count = len(result.get('candidates') or []) if isinstance(result, dict) else 0
        return f'读图识别成功，返回 {count} 个候选。'
    return '能力调用成功。'


def _test_preview(capability, result):
    """成功能预览的最小内容：生成图片给图片地址，对话给回复开头；其余不额外搬运正文。"""
    if capability == 'image' and isinstance(result, list):
        for item in result:
            if not isinstance(item, dict):
                continue
            url = item.get('url')
            if isinstance(url, str) and url.startswith(('https://', 'http://', 'data:image/')):
                return {'kind': 'image', 'url': url}
            encoded = item.get('b64_json')
            if isinstance(encoded, str) and encoded:
                return {'kind': 'image', 'url': 'data:image/png;base64,' + encoded}
    if capability == 'chat' and isinstance(result, str):
        return {'kind': 'text', 'text': result[:120]}
    return None


def _test_failure(error, timeout):
    """把网关错误分类成可区分的中文原因；界面只显示这里的中文，不显示任何原始码。"""
    if error.kind == 'timeout':
        return 'timeout', f'调用超时（{timeout:g} 秒），请检查接入地址或稍后重试。'
    if error.kind == 'not_configured':
        return 'not_configured', '该能力尚未配置可用路由，请先配置服务商与模型。'
    if error.kind == 'outbound_denied':
        return 'outbound_denied', '该服务商不允许外发这类测试样例，请调整出站上限。'
    if error.kind == 'not_found':
        return 'not_found', '服务商不存在。'
    if error.kind == 'bad_input':
        return 'bad_input', '测试样例无效，请联系平台维护者。'
    status = getattr(error, 'status_code', None)
    if status in (401, 403):
        return 'auth', '服务商拒绝访问，请检查密钥是否正确或已过期。'
    if getattr(error, 'model_hint', False):
        return 'model', '服务商不认识这个模型，请检查模型名称或开通状态。'
    if status == 404:
        return 'endpoint', '接入地址不正确，服务商没有这个接口，请检查接入地址。'
    if status == 429:
        return 'rate_limited', '服务商限流，请稍后重试。'
    if status is None:
        return 'network', '无法连接接入地址，请检查地址与网络。'
    if status >= 500:
        return 'provider', '服务商内部错误，请稍后重试。'
    return 'provider', '服务商拒绝了请求，请检查服务商配置。'


def audio_mime(data):
    """按原件字节识别可交给转写服务的音频格式。"""
    if data.startswith(b'RIFF') and data[8:12] == b'WAVE':
        return 'audio/wav'
    if data.startswith(b'\x1a\x45\xdf\xa3'):
        return 'audio/webm' if b'webm' in data[:64].lower() else None
    if len(data) >= 12 and data[4:8] == b'ftyp':
        return 'audio/mp4'
    if data.startswith(b'OggS'):
        return 'audio/ogg'
    return None


class Gateway:
    def __init__(self, settings, files=None, audit=None):
        self.settings = settings
        self.files = files
        self.audit = audit

    def stream_chat(self, app_id, payload, on_chunk, cancelled, timeout=50, *, principal=None):
        """仅平台内部使用的原生工具流；复用 call 的出站、配额和结算，不改 SDK 返回。"""
        return self.call(app_id, 'chat', payload, timeout, principal=principal,
                         _stream=streaming.Channel(on_chunk, cancelled))

    def call(self, app_id, capability, payload, timeout=50, *, override_model=None, legacy=False, principal=None,
             _stream=None):
        decoded_audio = self._validate(capability, payload, timeout)
        classification = None
        if capability in OUTBOUND_CAPABILITIES:
            classification = payload.get('classification') or DEFAULT_CLASSIFICATION
            if classification not in CLASSIFICATIONS:
                raise AIError('bad_input', 'classification 只能是 public、internal 或 confidential。')
        candidates = self._route_candidates(capability, override_model)
        if capability == 'transcribe' and decoded_audio is not None and audio_mime(decoded_audio) != 'audio/wav':
            raise AIError('bad_input', '稳定转写接口只接受 WAV 音频。')
        if classification is not None:
            # 每个会收到资料的候选都要单独过出站上限；上限不足的候选在尝试前剔除。
            candidates = [(p, m) for p, m in candidates if allowed_outbound(p, classification)]
            if not candidates:
                self._deny(app_id, principal, capability, classification)
                raise AIError('outbound_denied', '没有允许向外出站此分类资料的服务商。')
        file = self._file(payload, capability) if capability in FILE_CAPABILITIES and 'file_id' in payload else None
        if file is not None:
            self._load_file(file, principal)
        audit = {key: value for key, value in payload.items() if key not in ('file_id', 'classification')}
        if file is not None:
            audit['fileSha256'] = file['sha256']
        try:
            data = json.dumps(audit, ensure_ascii=False, sort_keys=True).encode()
        except (TypeError, ValueError):
            raise AIError('bad_input', '输入必须可序列化。') from None
        digest = hashlib.sha256(data).hexdigest()
        reservation = self.settings.reserve(app_id, capability, candidates[0][0]['id'], len(data), digest)
        if reservation is None:
            raise AIError('quota_exceeded', '应用调用次数已达到限额。')
        provider = candidates[0][0]['id']
        try:
            with start_blocking_portal() as portal:
                result, provider, model = portal.call(self._attempt, candidates, capability, payload, file,
                                                     min(timeout, 50), legacy, decoded_audio, _stream)
            self.settings.finish(reservation, 'success', provider)
            if capability == 'chat' and self.audit is not None:
                self.audit(app_id, getattr(principal, 'id', None) or 'system', 'ai.chat',
                           {'provider': provider, 'model': model})
            return {
                'result': result,
                'task_id': None,
                'capability': capability,
                'provider': provider,
                'model': model,
                'status': 'success',
                'created_at': time.time(),
                'input': self._input_ref(payload, file, digest, len(data)),
            }
        except BaseException:
            self.settings.finish(reservation, 'failure', provider)
            raise

    def _deny(self, app_id, principal, capability, classification):
        if self.audit is None:
            return
        self.audit(app_id, getattr(principal, 'id', None) or 'system', 'ai.outbound_denied',
                   {'capability': capability, 'classification': classification})

    def _route_candidates(self, capability, model=None):
        route = self.settings.route(capability)
        if not route:
            raise AIError('not_configured', '该能力尚未配置。')
        pairs = [(route['provider'], model or route['model'])]
        if route['fallback_provider']:
            pairs.append((route['fallback_provider'], model or route['fallback_model']))
        candidates = [(self.settings.provider(p), m) for p, m in pairs]
        if model and route['provider'] == ENVIRONMENT_PROVIDER and not self.settings.environment.explicit:
            # 兼容原 HAIKNOW_MODEL_* 调用方传入的模型覆盖值。
            provider, _ = candidates[0]
            candidates[0] = ({**provider, 'models': [model]}, model)
        candidates = [(p, m) for p, m in candidates if provider_available(p, m)]
        if not candidates:
            raise AIError('not_configured', '该能力没有可用的服务商。')
        return candidates

    def probe(self, ident):
        provider = self.settings.provider(ident)
        if provider is None:
            raise AIError('not_found', '服务商不存在。')
        if provider['kind'] == 'codex-cli':
            available = bool(shutil.which('codex'))
            return {'ok': available, 'detail': '已找到 Codex CLI。' if available else '本机未安装 Codex CLI。'}
        if not any(provider_available(provider, model) for model in provider['models']):
            return {'ok': False, 'detail': '服务商未启用，或缺少模型配置及环境变量凭据。'}
        with start_blocking_portal() as portal:
            return portal.call(adapters.probe, provider)

    def test(self, capability, *, provider_id=None, model=None, timeout=TEST_TIMEOUT):
        """用该能力最小样例真实调用一次；失败也返回中文结果，不向界面抛原始码。

        provider_id 为空时按已保存路由（含兜底）；否则固定测该服务商与模型。
        测试不预留应用配额、不写 ai_usage，留痕由管理接口写。
        """
        started = time.monotonic()
        provider = tested_model = None
        try:
            if capability not in TEST_SAMPLES:
                raise AIError('bad_input', '能力或输入参数无效。')
            if provider_id is None:
                candidates = self._route_candidates(capability)
            else:
                provider = self.settings.provider(provider_id)
                if provider is None:
                    raise AIError('not_found', '服务商不存在。')
                tested_model = model or (provider['models'][0] if provider['models'] else '')
                candidates = [(provider, tested_model)]
            provider, tested_model = candidates[0]
            if capability not in CAPABILITY_SUPPORT[provider['kind']]:
                return self._test_result(capability, provider, tested_model, started, reason='unsupported',
                                         message='该服务商类型不支持此能力，请更换支持它的服务商。')
            if not provider_available(provider, tested_model):
                raise AIError('not_configured', '服务商未启用，或缺少模型配置及环境变量凭据。')
            if capability in OUTBOUND_CAPABILITIES:
                candidates = [(p, m) for p, m in candidates
                              if allowed_outbound(p, 'public' if p['kind'] == 'codex-cli' else DEFAULT_CLASSIFICATION)]
                if not candidates:
                    return self._test_result(capability, provider, tested_model, started, reason='outbound_denied',
                                             message='该服务商不允许外发这类测试样例，请调整出站上限。')
            with start_blocking_portal() as portal:
                result, provider, tested_model = portal.call(
                    self._attempt, candidates, capability, dict(TEST_SAMPLES[capability]),
                    self._sample_file(capability), timeout, False)
            if capability == 'fetch' and isinstance(result, dict) and result.get('status') == 'failed':
                reason = result.get('reason') if result.get('reason') in FETCH_FAILURE_MESSAGES else 'provider'
                return self._test_result(capability, provider, tested_model, started, reason=reason,
                                         message=FETCH_FAILURE_MESSAGES[reason])
            outcome = self._test_result(capability, provider, tested_model, started,
                                        summary=_test_summary(capability, result))
            preview = _test_preview(capability, result)
            if preview:
                outcome['preview'] = preview
            return outcome
        except AIError as error:
            reason, message = _test_failure(error, timeout)
            return self._test_result(capability, provider, tested_model, started, reason=reason, message=message)

    @staticmethod
    def _test_result(capability, provider, model, started, **details):
        result = {
            'ok': not details.get('reason'),
            'capability': capability,
            'provider': provider['id'] if isinstance(provider, dict) else provider,
            'model': model or '',
            'elapsed_ms': int((time.monotonic() - started) * 1000),
        }
        result.update(details)
        return result

    @staticmethod
    def _sample_file(capability):
        asset = TEST_ASSETS.get(capability)
        if asset is None:
            return None
        name, data = asset
        return {'fileId': 'sample-' + capability, 'name': name,
                'sha256': hashlib.sha256(data).hexdigest(), 'data': data}

    def _validate(self, capability, payload, timeout):
        if capability not in CAPABILITIES or not isinstance(payload, dict) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise AIError('bad_input', '能力或输入参数无效。')
        value = payload.get(REQUIRED[capability])
        if capability == 'chat':
            if not isinstance(value, list) or not value or any(not isinstance(item, dict) for item in value):
                raise AIError('bad_input', '对话消息不能为空。')
        elif capability == 'transcribe':
            audio_base64 = payload.get('audio_base64')
            file_id = payload.get('file_id')
            has_audio = 'audio_base64' in payload
            has_file = 'file_id' in payload
            if has_audio == has_file:
                raise AIError('bad_input', '转写必须提供 WAV base64 或文件 ID，且只能提供一种。')
            if has_audio:
                if not isinstance(audio_base64, str) or not audio_base64:
                    raise AIError('bad_input', '音频必须是有效的 base64。')
                if len(audio_base64) > 4 * ((TRANSCRIBE_MAX_BYTES + 2) // 3):
                    raise AIError('bad_input', '音频文件不能超过 20 MB。')
                try:
                    decoded = base64.b64decode(audio_base64, validate=True)
                except (TypeError, ValueError):
                    raise AIError('bad_input', '音频必须是有效的 base64。') from None
                if len(decoded) > TRANSCRIBE_MAX_BYTES:
                    raise AIError('bad_input', '音频文件不能超过 20 MB。')
                return decoded
            elif not isinstance(file_id, str) or not file_id:
                raise AIError('bad_input', '文件 ID 不能为空。')
        elif capability in ('parse', 'vision'):
            if not isinstance(value, str) or not value:
                raise AIError('bad_input', '文件 ID 不能为空。')
            if capability == 'vision' and (not isinstance(payload.get('instruction'), str) or not payload['instruction'].strip()):
                raise AIError('bad_input', '读图任务说明不能为空。')
        elif capability in ('search', 'fetch'):
            if not isinstance(value, str) or not value.strip():
                raise AIError('bad_input', '能力输入不能为空。')
        elif not isinstance(value, str) or not value:
            raise AIError('bad_input', '能力输入不能为空。')

    @staticmethod
    def _file(payload, capability):
        return {'fileId': payload['file_id'], 'name': '', 'sha256': '', 'data': b'',
                'kind': capability}

    def _load_file(self, file, principal):
        if self.files is None or principal is None:
            raise AIError('bad_input', '文件类能力需要登录用户与文件服务。')
        document = self.files.get_file(principal, file['fileId'])
        declared_size = document.get('size')
        if (file.get('kind') == 'transcribe' and isinstance(declared_size, int)
                and not isinstance(declared_size, bool) and declared_size > TRANSCRIBE_MAX_BYTES):
            raise AIError('bad_input', '音频文件不能超过 20 MB。')
        data = self.files.read_file(principal, file['fileId'])
        if file.get('kind') == 'transcribe' and len(data) > TRANSCRIBE_MAX_BYTES:
            raise AIError('bad_input', '音频文件不能超过 20 MB。')
        file.update(name=document['name'], sha256=document['sha256'], size=document.get('size', len(data)), data=data)
        if file.get('kind') == 'transcribe':
            file['mime_type'] = audio_mime(data)
            if file['mime_type'] is None:
                raise AIError('bad_input', '转写文件格式不支持，仅支持 WAV、WebM、MP4 或 Ogg。')

    @staticmethod
    def _input_ref(payload, file, digest, length):
        if file is not None:
            return {'kind': 'file', 'fileId': file['fileId'], 'name': file['name'], 'sha256': file['sha256']}
        return {'kind': 'text', 'sha256': digest, 'length': length}

    async def _attempt(self, candidates, capability, payload, file, timeout, legacy, decoded_audio=None, stream=None):
        deadline = time.monotonic() + timeout
        try:
            with fail_after(timeout):
                for index, (provider, model) in enumerate(candidates):
                    for attempt in range(2 if legacy else 1):
                        try:
                            try:
                                with fail_after(min(timeout, 25) if legacy else timeout):
                                    return await self._invoke(provider, model, capability, payload, file, timeout,
                                                              deadline, decoded_audio, stream), provider['id'], model
                            except TimeoutError:
                                raise AIError('timeout', '模型调用超时。') from None
                            except TRANSPORT_ERRORS:
                                raise transport_error('模型服务连接中断，请稍后重试。') from None
                        except AIError as error:
                            # 首个流块发出后不能切到另一个服务商，把两份回答拼在一起。
                            if stream is not None and (stream.started or stream.cancelled.is_set()):
                                raise
                            if legacy and attempt == 0 and (error.kind == 'timeout' or getattr(error, 'legacy_retryable', False)):
                                continue
                            if index + 1 == len(candidates) or error.kind not in ('timeout', 'provider_error'):
                                raise
                            break
        except TimeoutError:
            raise AIError('timeout', '能力调用超时。') from None

    async def _invoke(self, provider, model, capability, payload, file, timeout, deadline, decoded_audio=None, stream=None):
        if capability not in CAPABILITY_SUPPORT[provider['kind']]:
            raise AIError('provider_error', f'服务商 {provider["id"]} 不支持能力 {capability}。')
        if stream is not None:
            return await streaming.request(provider, model, payload, timeout, stream)
        if provider['kind'] == 'mock':
            return self._mock(provider, capability, payload, file, model)
        if provider['kind'] == 'codex-cli':
            return await codex.chat(model, payload)
        if capability == 'parse':
            return await adapters.mineru_parse(provider, model, file, timeout, deadline)
        if capability == 'search':
            return await adapters.deepseek_search(provider, model, payload, timeout)
        if capability == 'fetch':
            return await adapters.builtin_fetch(provider, model, payload, timeout)
        if capability == 'vision':
            return await adapters.vision_candidates(provider, model, file, payload, timeout)
        paths = {'chat': '/chat/completions', 'image': '/images/generations', 'transcribe': '/audio/transcriptions', 'speech': '/audio/speech', 'embedding': '/embeddings'}
        headers = auth_headers(provider)
        try:
            async with httpx.AsyncClient(timeout=50, trust_env=provider['kind'] != 'local') as client:
                if capability == 'transcribe':
                    if file is not None:
                        audio, filename, mime_type = file['data'], file['name'], file['mime_type']
                    else:
                        audio = decoded_audio
                        if audio is None:
                            try:
                                audio = base64.b64decode(payload['audio_base64'], validate=True)
                            except (KeyError, ValueError, TypeError):
                                raise AIError('bad_input', '音频必须是有效的 base64。') from None
                        filename, mime_type = 'audio.wav', 'audio/wav'
                    options = {k: str(v) for k, v in payload.items()
                               if k not in ('audio_base64', 'file_id', 'classification')}
                    response = await client.post(provider['base_url'] + paths[capability], headers=headers,
                                                 data={**options, 'model': model},
                                                 files={'file': (filename, audio, mime_type)})
                else:
                    provider_payload = {key: value for key, value in payload.items() if key != 'classification'}
                    response = await client.post(provider['base_url'] + paths[capability], headers=headers,
                                                 json={**provider_payload, 'model': model})
                response.raise_for_status()
                if capability == 'speech':
                    return {'audio_base64': base64.b64encode(response.content).decode()}
                result = response.json()
                if capability == 'chat':
                    content = result['choices'][0]['message']['content']
                    if not isinstance(content, str):
                        raise TypeError('响应格式错误')
                    return content
                if capability == 'transcribe':
                    return result['text']
                return result.get('data', result)
        except httpx.TimeoutException:
            message = '模型调用超时。' if capability == 'chat' else '能力调用超时。'
            raise AIError('timeout', message) from None
        except httpx.TransportError:
            raise transport_error('模型服务连接中断，请稍后重试。') from None
        except httpx.HTTPError as exc:
            error = AIError('provider_error', '模型服务商调用失败。')
            error.legacy_kind = 'http'
            error.status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            error.legacy_retryable = error.status_code is not None and 500 <= error.status_code < 600
            error.model_hint = mentions_model(exc)
            raise error from None
        except (ValueError, KeyError, IndexError, TypeError):
            error = AIError('provider_error', '模型服务商响应格式无效。')
            error.legacy_kind = 'bad_response'
            raise error from None

    def _mock(self, provider, capability, payload, file, model):
        if capability == 'chat':
            return '[模拟模型] 已收到输入。'
        if capability == 'image':
            return [{'url': 'mock://' + provider['id']}]
        if capability == 'transcribe':
            return '[模拟转写]'
        if capability == 'speech':
            return {'audio_base64': base64.b64encode(provider['id'].encode()).decode()}
        if capability == 'embedding':
            return [{'embedding': [0.0]}]
        if capability == 'parse':
            return {
                'blocks': [{'id': 'b0', 'type': 'text', 'order': 0, 'page': 1,
                            'text': '[模拟解析] 平台未配置真实解析服务，此结果仅用于联调。'}],
                'processedPages': [1], 'uncoveredPages': [], 'totalPages': 1,
                'parser': {'name': 'mock', 'version': model},
                'source': {'fileId': file['fileId'], 'name': file['name'], 'sha256': file['sha256']},
                'mock': True,
            }
        if capability == 'search':
            return {
                'query': payload['query'], 'queriedAt': time.time(),
                'service': {'provider': provider['id'], 'model': model},
                'results': [{'url': 'mock://search/1', 'title': '[模拟搜索] 未调用真实搜索服务',
                             'snippet': '[模拟搜索] 仅用于联调，不是业务事实。', 'rank': 1,
                             'domain': 'mock.invalid', 'publishedAt': None}],
                'mock': True,
            }
        if capability == 'fetch':
            return {
                'finalUrl': payload['url'], 'title': '[模拟读取] 未请求真实网页',
                'sha256': hashlib.sha256(b'mock-page').hexdigest(), 'fetchedAt': time.time(),
                'status': 'complete', 'reason': None, 'reader': {'name': 'mock', 'version': model},
                'blocks': [{'index': 0, 'offset': 0, 'text': '[模拟读取] 仅用于联调。'}],
                'text': '[模拟读取] 仅用于联调。', 'truncated': False, 'httpStatus': 200, 'mock': True,
            }
        return {
            'candidates': [{'label': '[模拟识别]', 'value': '仅用于联调', 'confidence': 0.0}],
            'rawText': '[模拟识别] 平台未配置真实视觉服务，此结果仅用于联调。',
            'source': {'fileId': file['fileId'], 'name': file['name'], 'sha256': file['sha256']},
            'mock': True,
        }

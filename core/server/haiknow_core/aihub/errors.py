"""与 SDK 共享的能力调用错误。"""
import ssl

from haiknow_sdk.ai import AIError

# 上游 TLS/连接层的原生异常：httpx 不保证把它们包装成 HTTPError，漏出会落到全局 500。
TRANSPORT_ERRORS = (ssl.SSLError, OSError)


def transport_error(message):
    """传输中断统一映射为可重试的 provider_error；不带异常文本、接入地址或密钥。"""
    error = AIError('provider_error', message)
    error.legacy_kind = 'http'
    error.legacy_retryable = True
    return error


def mentions_model(exc):
    """上游拒绝时是否点名了模型：只看状态码与响应里有无 model 字样，不回显响应正文。"""
    response = getattr(exc, 'response', None)
    status = getattr(response, 'status_code', None)
    if status not in (400, 404, 422):
        return False
    text = getattr(response, 'text', '')
    return isinstance(text, str) and 'model' in text[:2000].lower()

"""公开出口只规范平台保留码，应用自定义码按原拼写传输。"""

from haiknow_sdk.resources import ERROR_STATUS

_PLATFORM_CODES = ERROR_STATUS.keys() | {
    'already_decided', 'app_unavailable', 'submitter_unavailable',
    # 已持久化的 jobs 也可能记录 AIError 或旧 ModelError 的 kind。
    'bad_input', 'bad_response', 'http', 'not_configured', 'outbound_denied',
    'provider_error', 'quota_exceeded', 'timeout',
}


def public_error_code(code: str) -> str:
    return code.upper() if code.lower() in _PLATFORM_CODES else code

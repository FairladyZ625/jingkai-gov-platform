"""公开出口只规范平台保留码，应用自定义码按原拼写传输。"""

import json
from pathlib import Path

from haiknow_sdk.resources import ERROR_STATUS

# 旧 ModelError 的这两种 kind 未列入公开平台码表，应用允许精确登记。
_LEGACY_MODEL_CODES = {'bad_response', 'http'}
_PLATFORM_CODES = ERROR_STATUS.keys() | {
    'already_decided', 'app_unavailable', 'submitter_unavailable',
    'bad_input', 'not_configured', 'outbound_denied',
    'provider_error', 'quota_exceeded', 'timeout',
} | _LEGACY_MODEL_CODES


def public_error_code(code: str, *, app_dir: Path | None = None) -> str:
    if code in _LEGACY_MODEL_CODES and app_dir is not None:
        try:
            registry = json.loads((app_dir / 'web' / 'errors.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        else:
            if isinstance(registry, dict) and isinstance(registry.get(code), str):
                return code
    return code.upper() if code.lower() in _PLATFORM_CODES else code

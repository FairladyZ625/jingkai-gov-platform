"""进程拥有的模型配置，与管理员保存的服务商元数据分开。"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

ENVIRONMENT_PROVIDER = '@environment'
KEYLESS_PROVIDERS = {'mock', 'builtin', 'local', 'codex-cli'}


def valid_base_url(value, schemes=('https', 'http')):
    try:
        url = urlsplit(value)
        url.port  # 校验端口
    except ValueError:
        return False
    return bool(url.scheme in schemes and url.hostname and url.username is None and
                url.password is None and '?' not in value and '#' not in value and
                '\\' not in value and not any(char.isspace() or ord(char) < 32 for char in value))


def _env_key(name):
    value = os.environ.get(name, '')
    return value if all('!' <= char <= '~' for char in value) else ''


def managed_api_key(ident, base_url):
    # '-' 对应 '_'，小写字母与数字保持唯一映射。端点由进程固定，管理员改址不会带走凭据。
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', ident):
        return ''
    prefix = 'HAIKNOW_PROVIDER_' + ident.upper().replace('-', '_')
    pinned_url = os.environ.get(prefix + '_BASE_URL', '').strip().rstrip('/')
    if base_url and pinned_url == base_url:
        return _env_key(prefix + '_API_KEY')
    return ''


@dataclass(frozen=True)
class ModelEnvironment:
    mode: str
    base_url: str
    model: str
    api_key: str = field(repr=False)
    explicit: bool = False

    @classmethod
    def read(cls):
        mode = os.environ.get('HAIKNOW_MODEL_PROVIDER', '').strip()
        base_url = os.environ.get('HAIKNOW_MODEL_BASE_URL', '').strip().rstrip('/')
        model = os.environ.get('HAIKNOW_MODEL_NAME', '').strip()
        api_key = _env_key('HAIKNOW_MODEL_API_KEY')
        implicit = 'legacy' if any((base_url, model, api_key)) else 'mock'
        return cls(mode or implicit, base_url, model, api_key, explicit=bool(mode))

    def ready(self, model=None):
        if not (model or self.model):
            return False
        if self.mode == 'codex-cli':
            return True
        if self.mode == 'local':
            return valid_base_url(self.base_url)
        if self.mode == 'cloud':
            return valid_base_url(self.base_url, ('https',)) and bool(self.api_key)
        if self.mode == 'legacy' and not self.explicit:
            return valid_base_url(self.base_url) and bool(self.api_key)
        return False

    def provider(self):
        if self.mode == 'mock':
            if not self.explicit:
                return None
            # 显式 mock：本机模拟，不出站，可承接任何分类。
            return dict(id=ENVIRONMENT_PROVIDER, kind='mock', enabled=True, base_url='',
                        models=[self.model or 'mock'], api_key='', allow_outbound='confidential')
        kind = {'local': 'local', 'codex-cli': 'codex-cli'}.get(self.mode, 'openai')
        return dict(id=ENVIRONMENT_PROVIDER, kind=kind, enabled=self.ready(),
                    base_url=self.base_url if kind != 'codex-cli' else '',
                    models=[self.model] if self.model else [],
                    api_key=self.api_key if kind != 'codex-cli' else '',
                    allow_outbound='public' if kind == 'codex-cli' else 'internal')


def provider_available(provider, model):
    return bool(provider and provider['enabled'] and model in provider['models'] and
                (provider['kind'] in KEYLESS_PROVIDERS or provider['api_key']))


def auth_headers(provider):
    key = provider['api_key']
    return {'Authorization': 'Bearer ' + key} if key else {}

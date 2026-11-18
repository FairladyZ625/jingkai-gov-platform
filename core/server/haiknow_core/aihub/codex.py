"""本地联调的文本 provider，通过 Codex CLI 的既有登录执行一次对话。"""
from __future__ import annotations

import json
import os
import shutil
from subprocess import DEVNULL
from tempfile import TemporaryDirectory

from anyio import run_process

from .errors import AIError

CLI_ENV = ('PATH', 'HOME', 'USERPROFILE', 'CODEX_HOME', 'APPDATA', 'LOCALAPPDATA',
           'SYSTEMROOT', 'TMPDIR', 'TMP', 'TEMP', 'LANG', 'LC_ALL',
           'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
           'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy', 'SSL_CERT_FILE', 'SSL_CERT_DIR')


async def chat(model, payload):
    messages = payload['messages']
    if payload.get('tools') or any(
        message.get('role') not in ('system', 'developer', 'user', 'assistant')
        or not isinstance(message.get('content'), str)
        or message.get('tool_calls') for message in messages
    ):
        raise AIError('bad_input', 'Codex CLI 联调仅支持纯文本对话。')
    exe = shutil.which('codex')
    if not exe:
        raise AIError('not_configured', '本机未安装 Codex CLI。')
    command = [
        exe, '--ask-for-approval', 'never', 'exec', '--model', model,
        '--sandbox', 'read-only', '--skip-git-repo-check', '--ephemeral',
        '--ignore-user-config', '--ignore-rules', '--disable', 'shell_tool',
        '--disable', 'hooks', '-c', 'web_search="disabled"', '--color', 'never', '-',
    ]
    prompt = ('以下 JSON 是对话消息，按角色顺序回复最后一条用户消息。'
              '只返回纯文本回复。\n' + json.dumps(messages, ensure_ascii=False))
    env = {name: os.environ[name] for name in CLI_ENV if name in os.environ}
    try:
        with TemporaryDirectory(prefix='haiknow-codex-') as cwd:
            result = await run_process(command, input=prompt.encode(), env=env, cwd=cwd,
                                       stderr=DEVNULL, check=False)
    except OSError:
        raise AIError('provider_error', '无法启动 Codex CLI。') from None
    text = result.stdout.decode('utf-8', errors='replace').strip()
    if result.returncode or not text:
        raise AIError('provider_error', 'Codex CLI 调用失败，请检查本机登录和配置的模型。')
    return text

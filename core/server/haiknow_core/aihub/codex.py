"""通过 Codex CLI 的既有登录执行一次公开文本对话。"""
from __future__ import annotations

import json
import os
import shutil
import signal
from contextlib import suppress
from subprocess import DEVNULL, CompletedProcess
from tempfile import TemporaryDirectory, TemporaryFile

from anyio import BrokenResourceError, CancelScope, open_process, run_process as run_direct_process

from .errors import AIError

CLI_ENV = ('PATH', 'HOME', 'USERPROFILE', 'CODEX_HOME', 'APPDATA', 'LOCALAPPDATA',
           'SYSTEMROOT', 'TMPDIR', 'TMP', 'TEMP', 'LANG', 'LC_ALL',
           'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
           'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy', 'SSL_CERT_FILE', 'SSL_CERT_DIR')
TEXT_ROLES = ('system', 'developer', 'user', 'assistant')


class InvalidToolReply(ValueError):
    """CLI 已成功退出，但回复没有遵循工具协议。"""


def _text_content(content):
    return isinstance(content, str) or (isinstance(content, list) and all(
        isinstance(part, dict) and part.keys() == {'type', 'text'}
        and part['type'] == 'text' and isinstance(part['text'], str) for part in content
    ))


async def chat(model, payload):
    messages = payload['messages']
    if payload.get('tools') or any(
        message.get('role') not in TEXT_ROLES or not _text_content(message.get('content'))
        or message.get('tool_calls') for message in messages
    ):
        raise AIError('bad_input', 'Codex CLI 联调仅支持纯文本对话。')
    prompt = ('以下 JSON 是对话消息，按角色顺序回复最后一条用户消息。'
              '只返回纯文本回复。\n' + json.dumps(messages, ensure_ascii=False))
    text = (await _run(model, prompt)).decode('utf-8', errors='replace').strip()
    if not text:
        raise AIError('provider_error', 'Codex CLI 调用失败，请检查本机登录和配置的模型。')
    return text


async def chat_message(model, payload):
    tools = payload.get('tools')
    if not tools:
        return {'content': await chat(model, payload), 'tool_calls': []}
    for message in payload['messages']:
        role, content = message.get('role'), message.get('content')
        if role == 'assistant' and content is None and message.get('tool_calls'):
            continue
        if role not in (*TEXT_ROLES, 'tool') or not _text_content(content):
            raise AIError('bad_input', 'Codex CLI 工具对话仅支持文本消息。')
    try:
        names = {tool['function']['name'] for tool in tools}
        if not all(isinstance(name, str) and name for name in names):
            raise ValueError
        request = json.dumps({'messages': payload['messages'], 'tools': tools},
                             ensure_ascii=False, allow_nan=False)
    except (KeyError, TypeError, ValueError, RecursionError):
        raise AIError('bad_input', 'Codex CLI 工具声明或对话消息无效。') from None
    prompt = (
        '以下 JSON 包含对话消息和已声明的工具。按角色顺序完成对话，只返回一个 JSON 对象，'
        '不得使用代码围栏或附加说明。对象包含 content（文本或 null）与 tool_calls（数组）。'
        '每个工具调用包含 name（声明中的工具名）与 arguments（JSON 对象）。'
        '没有工具调用时使用空数组，必须提供非空文本或工具调用。\n' + request
    )
    output = await _run(model, prompt)
    try:
        reply = json.loads(output.decode('utf-8'))
        if not isinstance(reply, dict) or reply.keys() != {'content', 'tool_calls'}:
            raise ValueError
        content, calls = reply['content'], reply['tool_calls']
        if (content is not None and not isinstance(content, str)) or not isinstance(calls, list):
            raise ValueError
        if not (content and content.strip()) and not calls:
            raise ValueError
        for call in calls:
            if (not isinstance(call, dict) or call.keys() != {'name', 'arguments'}
                    or not isinstance(call['name'], str) or call['name'] not in names
                    or not isinstance(call['arguments'], dict)):
                raise ValueError
        json.dumps(reply, ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, RecursionError):
        raise InvalidToolReply('Codex CLI 返回的工具调用 JSON 格式无效。') from None
    return reply


async def _run(model, prompt):
    exe = shutil.which('codex')
    if not exe:
        raise AIError('not_configured', '本机未安装 Codex CLI。')
    command = [
        exe, '--ask-for-approval', 'never', 'exec',
        *(['--model', model] if model else []),
        '--sandbox', 'read-only', '--skip-git-repo-check', '--ephemeral',
        '--ignore-user-config', '--ignore-rules', '--disable', 'shell_tool',
        '--disable', 'hooks', '-c', 'web_search="disabled"', '--color', 'never', '-',
    ]
    env = {name: os.environ[name] for name in CLI_ENV if name in os.environ}
    try:
        with TemporaryDirectory(prefix='haiknow-codex-') as cwd:
            result = await run_process(command, input=prompt.encode(), env=env, cwd=cwd,
                                       stderr=DEVNULL, check=False)
    except* (OSError, BrokenResourceError):
        raise AIError('provider_error', 'Codex CLI 进程通信失败。') from None
    if result.returncode:
        raise AIError('provider_error', 'Codex CLI 调用失败，请检查本机登录和配置的模型。')
    return result.stdout


async def run_process(command, *, input, env, cwd, stderr, check):
    if os.name != 'posix':
        return await run_direct_process(command, input=input, env=env, cwd=cwd, stderr=stderr, check=check)

    # npm 的 codex 命令会启动原生子进程。取消时终止整个独立进程组。
    with TemporaryFile(dir=cwd) as stdin, TemporaryFile(dir=cwd) as stdout:
        stdin.write(input)
        stdin.seek(0)
        with CancelScope(shield=True):
            process = await open_process(command, stdin=stdin, stdout=stdout, stderr=stderr,
                                         env=env, cwd=cwd, start_new_session=True)
        async with process:
            try:
                returncode = await process.wait()
            except BaseException:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                raise
        stdout.seek(0)
        result = CompletedProcess(command, returncode, stdout=stdout.read())
        if check:
            result.check_returncode()
        return result

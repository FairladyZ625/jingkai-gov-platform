"""四类新能力的真实适配器：MinerU 文档解析、DeepSeek 网络搜索、读图识别与连通性探测。

fetch 的平台内置读取器见 reader.py；这里只做路由分发与能力校验。
"""
from __future__ import annotations

import base64
import io
import json
import re
import time
import zipfile
from urllib.parse import urlsplit

import anyio
import httpx

from . import reader
from .errors import AIError, TRANSPORT_ERRORS, mentions_model

POLL_INTERVAL = 1.0
MINERU_STATES = {'waiting-file', 'uploading', 'pending', 'running', 'converting', 'done', 'failed'}


def _headers(provider):
    return {'Authorization': 'Bearer ' + provider['api_key'], 'Content-Type': 'application/json'}


def _status_error(exc, message):
    error = AIError('provider_error', message)
    response = getattr(exc, 'response', None)
    error.status_code = getattr(response, 'status_code', None)
    error.model_hint = mentions_model(exc)
    return error


def _json(response, message):
    try:
        return response.json()
    except ValueError:
        raise AIError('provider_error', message) from None


# ---------------------------------------------------------------- 文档解析
def _timeout(task_id):
    error = AIError('timeout', '文档解析超时，可稍后重试。')
    error.task_id = task_id
    return error


def _mineru_data(response):
    payload = _json(response, '解析服务响应格式无效。')
    if not isinstance(payload, dict) or payload.get('code') != 0:
        error = AIError('provider_error', '解析服务返回错误。')
        if isinstance(payload, dict) and payload.get('code') in ('A0202', 'A0211'):
            error.status_code = 401
        raise error
    data = payload.get('data')
    if not isinstance(data, dict):
        raise AIError('provider_error', '解析服务响应格式无效。')
    return data


def parse_blocks(archive_bytes):
    """从 MinerU 结果 ZIP 的 content_list.json 生成区块与页码覆盖。"""
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            names = archive.namelist()
            name = next((n for n in names if n.endswith('_content_list.json')), None)
            name = name or next((n for n in names if n.endswith('content_list.json')), None)
            if name is None:
                raise KeyError('content_list')
            items = json.loads(archive.read(name))
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise AIError('provider_error', '解析结果缺少内容列表。') from None
    if not isinstance(items, list):
        raise AIError('provider_error', '解析结果缺少内容列表。')
    blocks = []
    for item in items:
        if not isinstance(item, dict):
            continue
        order = len(blocks)
        page = item.get('page_idx')
        block = {
            'id': f'b{order}',
            'type': str(item.get('type') or 'text'),
            'order': order,
            'page': page + 1 if isinstance(page, int) and page >= 0 else None,
        }
        text = item.get('text')
        if isinstance(text, str) and text.strip():
            block['text'] = text
        table = item.get('table_body') or item.get('table')
        if isinstance(table, str) and table.strip():
            block['table'] = table
        bbox = item.get('bbox')
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox):
            block['bbox'] = list(bbox)
        blocks.append(block)
    processed = sorted({block['page'] for block in blocks if block['page'] is not None})
    return blocks, processed


async def _mineru_poll(client, base, headers, batch_id, deadline):
    # 比外层预算早 50ms 收口，保证超时能带回任务 ID 而不是只被取消。
    while True:
        if time.monotonic() >= deadline - 0.05:
            raise _timeout(batch_id)
        response = await client.get(f'{base}/extract-results/batch/{batch_id}', headers=headers)
        response.raise_for_status()
        data = _mineru_data(response)
        items = data.get('extract_result') or []
        if isinstance(items, dict):
            items = [items]
        entry = items[0] if isinstance(items, list) and items else {}
        state = entry.get('state')
        if state == 'done':
            return entry
        if state == 'failed':
            raise AIError('provider_error', '解析服务返回失败。')
        if state not in MINERU_STATES:
            raise AIError('provider_error', '解析服务响应状态无效。')
        await anyio.sleep(min(POLL_INTERVAL, max(0.0, deadline - time.monotonic())))


async def mineru_parse(provider, model, file, timeout, deadline):
    base = provider['base_url']
    headers = _headers(provider)
    batch_id = None
    try:
        async with httpx.AsyncClient(timeout=min(timeout, 30)) as client:
            created = await client.post(base + '/file-urls/batch', headers=headers, json={
                'files': [{'name': file['name'], 'data_id': file['fileId'][:128]}],
                'model_version': model,
            })
            created.raise_for_status()
            data = _mineru_data(created)
            batch_id = data.get('batch_id')
            urls = data.get('file_urls') or []
            if not isinstance(batch_id, str) or not batch_id or not isinstance(urls, list) or not urls:
                raise AIError('provider_error', '解析服务未返回上传地址。')
            uploaded = await client.put(urls[0], content=file['data'])
            uploaded.raise_for_status()
            entry = await _mineru_poll(client, base, headers, batch_id, deadline)
            zip_url = entry.get('full_zip_url')
            if not isinstance(zip_url, str) or not zip_url:
                raise AIError('provider_error', '解析服务未返回结果文件。')
            archive = await client.get(zip_url)
            archive.raise_for_status()
            blocks, processed = parse_blocks(archive.content)
    except httpx.TimeoutException:
        raise _timeout(batch_id) from None
    except httpx.HTTPError as exc:
        raise _status_error(exc, '解析服务调用失败。') from None
    progress = entry.get('extract_progress') if isinstance(entry.get('extract_progress'), dict) else {}
    total = progress.get('total_pages')
    total = total if isinstance(total, int) and total >= 0 else (max(processed) if processed else 0)
    covered = set(processed)
    return {
        'blocks': blocks,
        'processedPages': processed,
        'uncoveredPages': [page for page in range(1, total + 1) if page not in covered],
        'totalPages': total,
        'parser': {'name': 'mineru', 'version': model},
        'source': {'fileId': file['fileId'], 'name': file['name'], 'sha256': file['sha256']},
        'mock': False,
    }


# ---------------------------------------------------------------- 网络搜索
def _domain(url):
    try:
        return (urlsplit(url).hostname or '').lower()
    except ValueError:
        return ''


async def deepseek_search(provider, model, payload, timeout):
    body = {'query': payload['query']}
    count = payload.get('count')
    if count is not None:
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 50:
            raise AIError('bad_input', '搜索条数必须是 1 到 50 的整数。')
        body['count'] = count
    for key in ('ori_question', 'localization'):
        if isinstance(payload.get(key), str) and payload[key]:
            body[key] = payload[key]
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(provider['base_url'] + '/tools/search', headers=_headers(provider), json=body)
            response.raise_for_status()
            data = _json(response, '搜索服务响应格式无效。')
    except httpx.TimeoutException:
        raise AIError('timeout', '网络搜索超时，请稍后重试。') from None
    except httpx.HTTPError as exc:
        raise _status_error(exc, '搜索服务调用失败。') from None
    items = data.get('results') if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise AIError('provider_error', '搜索服务响应格式无效。')
    results = []
    for rank, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        url = item.get('url') if isinstance(item.get('url'), str) else ''
        results.append({
            'url': url,
            'title': item.get('title') if isinstance(item.get('title'), str) else '',
            'snippet': item.get('snippet') if isinstance(item.get('snippet'), str) else '',
            'rank': rank,
            'domain': _domain(url),
            'publishedAt': item.get('date') if isinstance(item.get('date'), str) and item.get('date') else None,
        })
    return {
        'query': payload['query'],
        'queriedAt': time.time(),
        'service': {'provider': provider['id'], 'model': model},
        'results': results,
        'mock': False,
    }


# ---------------------------------------------------------------- 读图识别
def image_data_url(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        mime = 'image/png'
    elif data.startswith(b'\xff\xd8\xff'):
        mime = 'image/jpeg'
    elif data.startswith((b'GIF87a', b'GIF89a')):
        mime = 'image/gif'
    elif data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        mime = 'image/webp'
    else:
        raise AIError('bad_input', '读图只支持 PNG、JPEG、GIF 或 WebP 图片。')
    return f'data:{mime};base64,{base64.b64encode(data).decode("ascii")}'


def parse_candidates(raw):
    """模型输出 JSON 候选；不是合法 JSON 时保留原文、候选为空，不伪造识别结果。"""
    if not isinstance(raw, str):
        return []
    text = raw.strip()
    fenced = re.search(r'```(?:json)?\s*(.*?)```', text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        start, end = text.find('['), text.rfind(']')
    if start < 0 or end <= start:
        return []
    try:
        payload = json.loads(text[start:end + 1])
    except ValueError:
        return []
    items = payload.get('candidates') if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    candidates = []
    for item in items[:50]:
        if not isinstance(item, dict):
            continue
        label = item.get('label')
        if not isinstance(label, str) or not label.strip():
            continue
        candidate = {'label': label.strip()}
        value = item.get('value')
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            candidate['value'] = value
        bbox = item.get('bbox')
        if isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox):
            candidate['bbox'] = bbox
        confidence = item.get('confidence')
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and 0 <= confidence <= 1:
            candidate['confidence'] = float(confidence)
        candidates.append(candidate)
    return candidates


async def vision_candidates(provider, model, file, payload, timeout):
    image = image_data_url(file['data'])
    body = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你是读图识别助手。只输出 JSON：{"candidates":[{"label":"","value":"","bbox":[0,0,0,0],"confidence":0.0}]}。'
                                          '无法确认的对象给低置信度，不要编造；看不到的对象不要输出。'},
            {'role': 'user', 'content': [
                {'type': 'text', 'text': payload['instruction']},
                {'type': 'image_url', 'image_url': {'url': image}},
            ]},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(provider['base_url'] + '/chat/completions', headers=_headers(provider), json=body)
            response.raise_for_status()
            data = _json(response, '读图服务响应格式无效。')
    except httpx.TimeoutException:
        raise AIError('timeout', '读图识别超时，请稍后重试。') from None
    except httpx.HTTPError as exc:
        raise _status_error(exc, '读图服务调用失败。') from None
    try:
        content = data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        raise AIError('provider_error', '读图服务响应格式无效。') from None
    if isinstance(content, list):
        raw = ''.join(part.get('text', '') for part in content if isinstance(part, dict) and isinstance(part.get('text'), str))
    elif isinstance(content, str):
        raw = content
    else:
        raise AIError('provider_error', '读图服务响应格式无效。')
    return {
        'candidates': parse_candidates(raw),
        'rawText': raw,
        'source': {'fileId': file['fileId'], 'name': file['name'], 'sha256': file['sha256']},
        'mock': False,
    }


# ---------------------------------------------------------------- 内置读取与连通性
async def builtin_fetch(provider, model, payload, timeout):
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            return await reader.fetch_page(client, payload['url'], model, allowed_hosts=payload.get('allowed_hosts'))
    except httpx.TimeoutException:
        raise AIError('timeout', '网页读取超时，请稍后重试。') from None
    except httpx.HTTPError:
        raise AIError('provider_error', '网页读取失败。') from None


async def probe(provider, timeout=10):
    if provider['kind'] in ('mock', 'builtin'):
        return {'ok': True, 'detail': '该服务商不需要外部连通。'}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            if provider['kind'] == 'mineru':
                response = await client.get(provider['base_url'] + '/extract-results/batch/connectivity-probe', headers=_headers(provider))
                payload = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                code = payload.get('code') if isinstance(payload, dict) else None
                if response.status_code in (401, 403) or code in ('A0202', 'A0211'):
                    return {'ok': False, 'detail': '解析服务密钥无效或已过期。'}
                if response.status_code >= 400:
                    return {'ok': False, 'detail': f'解析服务返回 HTTP {response.status_code}。'}
                # 未知批次号返回“找不到任务”说明鉴权已通过；0 说明连通正常。
                if code in (0, -60012) or code is None:
                    return {'ok': True, 'detail': '已连通 MinerU 解析服务。'}
                return {'ok': False, 'detail': '解析服务返回错误码。'}
            response = await client.get(provider['base_url'] + '/models', headers=_headers(provider))
            if response.status_code == 200:
                return {'ok': True, 'detail': '已连通模型服务。'}
            if response.status_code in (401, 403):
                return {'ok': False, 'detail': '密钥无效或无权限。'}
            return {'ok': False, 'detail': f'服务返回 HTTP {response.status_code}。'}
    except httpx.TimeoutException:
        return {'ok': False, 'detail': '连接服务超时。'}
    except (httpx.HTTPError, *TRANSPORT_ERRORS):
        return {'ok': False, 'detail': '无法连接服务，请检查接入地址。'}

"""政策岗位只发布实际查询到的依据，不把模型或演示画像当作事实。"""
import re
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from .cards import render_card
from .ports import ToolCall
from .service import Reply, _failure, _tool_directory

FOLLOWUP = re.compile(r'^(?:那|这个|这项|该|它|上述|刚才|还有)')
NO_PROMISE = '这些信息不代表符合申请条件或获批，仍需核对企业实际情况和当期申报指南。'
NO_BASIS = '当前政策目录没有找到能支持此问题的原文，无法判断适用或获批。请提供政策名称、事项编号或具体支持方向。'


def _followup_query(text, history):
    if not FOLLOWUP.search(text.strip()):
        return None
    previous = next((message for message in reversed(history)
                     if message['role'] == 'assistant' and not message.get('incomplete')), {})
    if not previous.get('citations'):
        return None
    for call in reversed(previous.get('toolCalls', [])):
        query = call.get('args', {}).get('q')
        if call.get('tool') == 'policy.search' and call.get('status') == 'ok' and isinstance(query, str):
            return query[:max(0, 3999 - len(text))] + '\n' + text
    return None


def _valid_items(result):
    if result.get('queryState') not in ('searched', 'clarify') or not isinstance(result.get('items'), list):
        raise ValueError('政策结果缺少检索状态')
    selected = result['items'][:3]
    for item in selected:
        if not all(isinstance(item.get(key), str) and item[key].strip()
                   for key in ('id', 'title', 'doc', 'docTitle', 'original')):
            raise ValueError('政策结果缺少原文')
        source = item.get('source')
        if not isinstance(source, dict) or not isinstance(source.get('url'), str):
            raise ValueError('政策结果缺少来源')
        parsed = urlsplit(source['url'])
        if parsed.scheme != 'https' or not parsed.hostname:
            raise ValueError('政策来源地址无效')
        if (not isinstance(item.get('conditions'), list) or not item['conditions']
                or not all(isinstance(condition, dict) and isinstance(condition.get('label'), str)
                           for condition in item['conditions'])
                or not isinstance(item.get('materials'), list)
                or not all(isinstance(material, str) for material in item['materials'])
                or not isinstance(item.get('times'), dict)):
            raise ValueError('政策结果格式无效')
    return selected


def _answer(result, selected):
    sections = []
    enterprise = result.get('enterprise')
    if enterprise:
        if enterprise.get('status') == 'available':
            item = enterprise['item']
            fields = '；'.join(str(item[key]) for key in ('name', 'industry', 'scale') if item.get(key))
            sections.append(f'当前企业资料：{fields}。资料仅用于明确服务对象，尚未完成申请资格核验。')
        else:
            sections.append('未能读取所选企业资料，以下仅为一般政策参考；请核对企业选择和当前账号权限。')
    else:
        sections.append('以下为一般政策参考。若需判断某家企业，请选择企业并补充实际需求。')
    if not selected:
        sections.append('请补充政策名称、事项编号或具体支持方向，我再查询条件、材料和期限。'
                        if result['queryState'] == 'clarify' else NO_BASIS)
        return '\n\n'.join(sections)
    sections.append(f'从当前政策目录找到 {len(result["items"])} 项相关参考，先列出 {len(selected)} 项。{NO_PROMISE}')
    for index, item in enumerate(selected, 1):
        conditions = '；'.join(condition['label'] for condition in item['conditions'])
        materials = '、'.join(item['materials']) or '目录未提供完整材料清单'
        times = item['times']
        window = times.get('deadlineText') or times.get('window') or '尚无可确认的申报时间'
        sections.append(
            f'{index}. {item["title"]}\n申请条件（待确认）：{conditions}\n'
            f'申报材料（目录参考）：{materials}；完整清单以当期申报指南为准。\n'
            f'申报期限：{window}\n原文依据[{index}]：{item["original"]}'
        )
    sections.append('下一步：请说明拟申请的支持事项，并逐项补充上述待确认条件及证明材料；'
                    '核对当期申报通知后，再由经办人确认后续办理。此处不会提交申请或替代审批。')
    return '\n\n'.join(sections)


async def respond_policy(request, user, *, text, enterprise_id, history, bridge, on_event):
    reply = Reply(intent='policy')
    args = {'q': text, 'queryMode': 'question'}
    if enterprise_id is not None:
        args['enterpriseId'] = enterprise_id
    call = ToolCall('policy.search', args)
    entry = {'tool': call.tool, 'args': args, 'status': 'ok'}
    reply.tool_calls.append(entry)
    try:
        items = (await run_in_threadpool(bridge.tools, user))['items'] if bridge else []
        directory = _tool_directory(items, 'policy', kb_action=False)
        if call.tool not in directory or directory[call.tool]['write']:
            raise ValueError('当前没有可用的只读政策查询工具')
        for attempt in range(2):
            response = await bridge.call_from_chat(request, 'policy', call.tool, args)
            result = response['result']
            selected = _valid_items(result)
            # 本轮先独立查。只有缺少主题的明确指代才允许延用上一轮有依据的查询。
            followup = _followup_query(text, history) if attempt == 0 and result['queryState'] == 'clarify' else None
            if followup is None:
                break
            if on_event is not None:
                await on_event('tool', entry)
            args = {**args, 'q': followup}
            call = ToolCall('policy.search', args)
            entry = {'tool': call.tool, 'args': args, 'status': 'ok'}
            reply.tool_calls.append(entry)
        # 先校验完全部依据与正文，再发布卡片和引用；失败时不留下部分可信外观。
        answer = _answer(result, selected)
        citations = [{
            'fileId': item['doc'], 'name': item['docTitle'], 'snippet': item['original'],
            'url': item['source']['url'], 'itemId': item['id'],
            'source': {'app': 'policy', 'itemId': item['id']},
        } for item in selected]
        if selected:
            reply.cards.append(render_card(call, {'items': selected}))
        reply.citations.extend(citations)
        reply.say(answer)
    except ClientDisconnect:
        raise
    except Exception as exc:
        entry['status'] = 'error'
        reply.say(f'政策查询未完成，{_failure(exc)}。当前没有可核实的依据，无法判断适用或获批，请稍后重试。')
    if on_event is not None:
        await on_event('tool', entry)
    return reply

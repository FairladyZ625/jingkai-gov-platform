"""在会议记录的同一版本内确认派发，个人视图按成员 ID 读取。"""

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from haiknow_sdk.preview.components import c04

from .minutes import UNCONFIRMED, todos_for


def commit_todos(ctx, record, ids):
    data = record['data']
    todos = todos_for(data)
    selected = {todo['id']: todo for todo in todos}
    members = None
    committed, skipped = [], []
    for todo_id in dict.fromkeys(ids):
        todo = selected.get(todo_id)
        if not todo:
            skipped.append({'id': todo_id, 'reason': '待办不存在'})
            continue
        if todo['status'] == '已派发':
            skipped.append({'id': todo_id, 'reason': '待办已派发'})
            continue

        owner, due, task = (str(todo.get(field) or '').strip() for field in ('owner', 'due', 'task'))
        missing = [label for value, label in ((task, '事项'), (owner, '负责人'), (due, '期限'))
                   if value in ('', UNCONFIRMED)]
        if missing:
            skipped.append({'id': todo_id, 'reason': '缺少' + '、'.join(missing)})
            continue

        if members is None:
            members = ctx.preview.members.list(record['project'], action='view')['items']
        owner_ids = {member['id'] for member in members if member['id'] == owner}
        if not owner_ids:
            owner_ids = {member['id'] for member in members if member['name'] == owner}
        if len(owner_ids) != 1:
            skipped.append({'id': todo_id, 'reason': '负责人须唯一匹配有权查看会议的在用成员'})
            continue

        todo.update(status='已派发', certain=True, assignment={
            'id': uuid5(NAMESPACE_URL, f"meeting:{record['id']}:{todo_id}").hex,
            'recipientId': owner_ids.pop(),
            'sender': ctx.user.name,
            'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        })
        committed.append(todo_id)
    if committed:
        data['todos'] = todos
        ctx.records.save(id=record['id'], baseVersion=record['version'], data=data)
    return {'committed': committed, 'skipped': skipped}


def assigned_todos(records, recipient_id):
    """从调用方已通过权限检查的会议版本投影原始派发回执。"""
    items = []
    for record in records:
        for todo in record['data'].get('todos', []):
            assignment = todo.get('assignment') or {}
            if assignment.get('recipientId') == recipient_id:
                items.append({
                    'id': assignment['id'], 'title': todo['task'], 'task': todo['task'],
                    'owner': todo['owner'], 'due': todo['due'], 'app': 'meeting', 'kind': 'todo',
                    'from': assignment['sender'], 'at': assignment['at'], 'status': 'pending', 'done': False,
                    'ref': {'meetingId': record['id'], 'tab': 'todos', 'todoId': todo['id']},
                })
    return items


def my_todos(ctx, *, now):
    items = assigned_todos(ctx.records.list(type='meeting')['items'], ctx.user.id)
    # 日期表达式仍可派发，能解析为 ISO 时间的期限才参与逾期计算。
    plan = c04.plan([
        c04.Node(item['id'], item['task'], ctx.user.id, item['due']) for item in items
    ], now=now)
    reminders = {reminder.node: reminder.to_dict() for reminder in plan.reminders}
    states = {state.id: state.status for state in plan.states if state.planned}
    for item in items:
        item['dueStatus'] = states.get(item['id'])
        if item['id'] in reminders:
            item['reminder'] = reminders[item['id']]
    items.sort(key=lambda item: (item['at'], item['id']), reverse=True)
    return {'items': items, 'total': len(items)}

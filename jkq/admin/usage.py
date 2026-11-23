"""按 #15 的 ai.chat 逐次审计汇总；失败尝试保留次数，缺失 token 贡献为零。"""

from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DIMENSIONS = {'app': 'app_id', 'model': "json_extract(detail, '$.model')", 'user': 'user_id'}
BEIJING = ZoneInfo('Asia/Shanghai')


def usage_page(db, group_by):
    dimension = DIMENSIONS[group_by]
    rows = db.execute(f"""select {dimension} as bucket, count(*),
        coalesce(sum(json_extract(detail, '$.usage.input')), 0),
        coalesce(sum(json_extract(detail, '$.usage.output')), 0)
        from audit where action='ai.chat' group by bucket order by bucket""")
    items = [{group_by: bucket, 'calls': calls, 'input': inputs, 'output': outputs}
             for bucket, calls, inputs, outputs in rows]
    return {'items': items, 'total': len(items)}


def usage_summary(db, *, now=None):
    """本周（北京时间周一开始）按同一审计快照计数，不把拒绝出站或任务状态计成调用。"""
    now = datetime.now(BEIJING) if now is None else now.astimezone(BEIJING)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=today.weekday())
    rows = db.execute("""
        select action, app_id, json_extract(meta, '$.model'), json_extract(meta, '$.providerKind'),
               count(*), sum(ts >= ?)
        from (select action, ts, app_id, case when json_valid(detail) then detail end as meta
              from audit where ts >= ? and ts <= ? and action in ('ai.chat', 'ai.outbound_denied'))
        where action = 'ai.chat' or json_extract(meta, '$.capability') = 'chat'
        group by 1, 2, 3, 4
    """, (today.timestamp(), week.timestamp(), now.timestamp()))
    apps, models, kinds = Counter(), Counter(), Counter()
    today_calls = blocked_today = blocked_week = 0
    for action, app, model, kind, count, today_count in rows:
        if action == 'ai.outbound_denied':
            blocked_today += today_count
            blocked_week += count
            continue
        apps[app if isinstance(app, str) and app else '未记录应用'] += count
        models[model if isinstance(model, str) and model else '未记录模型'] += count
        kinds[kind] += count
        today_calls += today_count
    week_calls = sum(apps.values())
    classified = kinds['local'] + kinds['cloud']
    local_share = (round(kinds['local'] * 100 / classified)
                   if classified and classified + kinds['mock'] == week_calls else None)

    def buckets(counter):
        return [{'name': name, 'calls': calls} for name, calls in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]

    return {'today': today_calls, 'week': week_calls, 'blockedToday': blocked_today, 'blockedWeek': blocked_week,
            'byApp': buckets(apps), 'byModel': buckets(models), 'localShare': local_share}

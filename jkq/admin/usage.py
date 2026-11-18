"""按 #15 的 ai.chat 逐次审计汇总；失败尝试保留次数，缺失 token 贡献为零。"""

DIMENSIONS = {'app': 'app_id', 'model': "json_extract(detail, '$.model')", 'user': 'user_id'}


def usage_page(db, group_by):
    dimension = DIMENSIONS[group_by]
    rows = db.execute(f"""select {dimension} as bucket, count(*),
        coalesce(sum(json_extract(detail, '$.usage.input')), 0),
        coalesce(sum(json_extract(detail, '$.usage.output')), 0)
        from audit where action='ai.chat' group by bucket order by bucket""")
    items = [{group_by: bucket, 'calls': calls, 'input': inputs, 'output': outputs}
             for bucket, calls, inputs, outputs in rows]
    return {'items': items, 'total': len(items)}

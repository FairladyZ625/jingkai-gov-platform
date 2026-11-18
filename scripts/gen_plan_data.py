#!/usr/bin/env python3
"""生成「开发计划」页的静态数据：prototype/v4/plan-data.json + plan-data.js

数据来源：
  1. 本仓库 docs/plan/issues.json（任务、里程碑、验收标准、依赖、卫华复用点）
  2. gh 拉取 GitHub 上 Issue / PR 的实时状态（公开仓库；拉不到则只用 issues.json，状态记为 unknown）

防泄密：只输出对外可见字段；卫华复用点只保留模块名（去掉本机绝对路径、内部 GitLab 地址）；
输出前对整份数据做敏感词扫描，命中即失败。
用法：scripts/gen-plan-data.sh [issues.json 路径]
"""
import json, os, re, subprocess, sys, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

REPO = os.environ.get('PLAN_GH_REPO', 'FairladyZ625/jingkai-gov-platform')
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / 'docs' / 'plan' / 'issues.json'
OUT_DIR = Path(os.environ.get('PLAN_OUT_DIR', ROOT / 'prototype' / 'v4'))
# 额外敏感词（如内部域名）可通过环境变量 PLAN_EXTRA_BANNED 以逗号分隔传入，不写进仓库
BANNED = [w for w in os.environ.get('PLAN_EXTRA_BANNED', '').split(',') if w] + ['00_内部资料', '勿外发', '人天', '报价', '毛利', '采购价', '硬件价', '/Users/', '/home/',
          'gitlab.', 'ssh://', 'ghp_', 'gho_', 'github_pat_', 'CLOUDFLARE_API_TOKEN']


def section(body, title):
    m = re.search(r'^### ' + re.escape(title) + r'\s*\n(.*?)(?=^### |\Z)', body, re.S | re.M)
    return m.group(1).strip() if m else ''


def clean(s):
    s = re.sub(r'(?:/Users|/home)/[^\s`|，,）)]*', '', s)
    s = re.sub(r'https?://gitlab\S*', '', s)
    return re.sub(r'\s{2,}', ' ', s).strip()


def gh_json(args):
    try:
        out = subprocess.run(['gh'] + args + ['-R', REPO], check=True, capture_output=True, text=True, timeout=60).stdout
        return json.loads(out)
    except Exception as e:  # noqa
        sys.stderr.write(f'提示：gh {" ".join(args[:2])} 失败，状态将标为 unknown（{e.__class__.__name__}）\n')
        return None


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    items = json.loads(src.read_text(encoding='utf-8'))
    id2num = {t['id']: t['issue_number'] for t in items}

    issues = gh_json(['issue', 'list', '--state', 'all', '--limit', '200', '--json', 'number,state,assignees,closedAt'])
    prs = gh_json(['pr', 'list', '--state', 'all', '--limit', '200', '--json', 'number,state,title,body,headRefName,url,isDraft,mergedAt'])
    st = {i['number']: i for i in (issues or [])}
    pr_map = {}
    for p in prs or []:
        refs = set(int(n) for n in re.findall(r'(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?)\s+#(\d+)', p.get('body') or '', re.I))
        m = re.match(r'[a-z]+/(\d+)-', p.get('headRefName') or '')
        if m:
            refs.add(int(m.group(1)))
        for n in refs:
            pr_map.setdefault(n, []).append({'number': p['number'], 'state': p['state'], 'url': p['url'],
                                             'title': clean(p['title']), 'draft': p.get('isDraft', False)})

    milestones, tasks = [], []
    for t in items:
        body = t.get('body', '')
        head = body.split('\n', 1)[0]
        prio = re.search(r'优先级：(P\d)', head)
        goal = section(body, '背景与目标')
        ms_goal = re.search(r'所属里程碑目标：(.*)', goal)
        goal_line = goal.split('\n')[0].strip()
        acc = [clean(x) for x in re.findall(r'^- \[[ x]\] (.*)$', section(body, '验收标准'), re.M)]
        ms = t['milestone']
        if ms not in [m['name'] for m in milestones]:
            milestones.append({'name': ms, 'key': ms.split(' ')[0], 'title': ms.split(' ', 1)[-1],
                               'goal': clean(ms_goal.group(1)) if ms_goal else ''})
        reuse = []
        for r in t.get('reuse', []):
            path = clean(r.get('path', ''))
            if path in ('', '—'):
                path = ''
            reuse.append({'module': path, 'mode': r.get('mode', ''), 'change': clean(r.get('change', ''))})
        n = t['issue_number']
        s = st.get(n)
        tasks.append({
            'id': t['id'], 'issue': n, 'title': clean(t['title']), 'milestone': ms.split(' ')[0],
            'labels': t.get('labels', []), 'priority': prio.group(1) if prio else '',
            'wave': t.get('wave'), 'branch': t.get('branch', ''),
            'depends_on': [{'id': d, 'issue': id2num.get(d)} for d in t.get('depends_on', [])],
            'goal': clean(goal_line), 'acceptance': acc, 'reuse': reuse,
            'state': (s['state'].lower() if s else 'unknown'),
            'assignees': [a.get('login') for a in (s or {}).get('assignees', [])],
            'prs': pr_map.get(n, []),
        })
    data = {
        'repo': REPO,
        'generated_at': datetime.datetime.now(ZoneInfo('Asia/Taipei')).strftime('%Y-%m-%d %H:%M（台北时间）'),
        'status_source': 'github' if issues is not None else 'none',
        'milestones': milestones, 'tasks': tasks,
    }
    text = json.dumps(data, ensure_ascii=False, indent=1)
    hits = [b for b in BANNED if b in text]
    if hits:
        raise SystemExit('错误：计划数据里出现不应对外的字样，已中止：' + ', '.join(hits))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 'plan-data.json').write_text(text + '\n', encoding='utf-8')
    (OUT_DIR / 'plan-data.js').write_text('window.JK_PLAN = ' + text + ';\n', encoding='utf-8')
    closed = sum(1 for x in tasks if x['state'] == 'closed')
    print(f'已生成 {OUT_DIR}/plan-data.json：{len(milestones)} 个里程碑、{len(tasks)} 个任务，已关闭 {closed}，状态来源 {data["status_source"]}')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""生成「开发计划」页的静态数据：web/plan-data.json + plan-data.js

数据来源：
  1. 本仓库 docs/plan/issues.json（任务、里程碑、验收标准、依赖、卫华复用点）
  2. gh 拉取 GitHub 上 Issue / PR 的实时状态与 CI 结果（公开仓库；拉不到则状态记为 unknown）
  3. 本机 HA（Harness Anything）：ha task list / show / dispatches、ha agenda、ha runtime status、ha squad status
     （在本仓库目录下运行；HA 不可用时跳过，页面只显示 GitHub 状态）

防泄密：只输出对外可见的摘要字段（执行者、阶段、时间、PR/CI 状态）；不输出本机路径、会话内容、
日志正文、提示词、令牌或用量；卫华复用点只保留模块名。输出前对整份数据做敏感词扫描，命中即失败。
用法：scripts/gen-plan-data.sh [issues.json 路径]
环境变量：PLAN_GH_REPO、PLAN_OUT_DIR、PLAN_HA_CWD、PLAN_WORKER_CAP（默认 8）、PLAN_STALL_MIN（默认 60）、PLAN_NO_HA=1
"""
import json, os, re, subprocess, sys, datetime
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
from pathlib import Path

REPO = os.environ.get('PLAN_GH_REPO', 'FairladyZ625/jingkai-gov-platform')
ROOT = Path(__file__).resolve().parent.parent
GOV = ROOT
DEFAULT_SRC = GOV / 'docs' / 'plan' / 'issues.json'
OUT_DIR = Path(os.environ.get('PLAN_OUT_DIR', ROOT / 'web'))
HA_CWD = Path(os.environ.get('PLAN_HA_CWD', GOV))
WORKER_CAP = int(os.environ.get('PLAN_WORKER_CAP', '8'))
STALL_MIN = int(os.environ.get('PLAN_STALL_MIN', '60'))
TZ = ZoneInfo('Asia/Taipei')
# 额外敏感词（如内部域名）可通过环境变量 PLAN_EXTRA_BANNED 以逗号分隔传入，不写进仓库
# 商务核算类关键词与 guard 共用一份清单（scripts/guard_rules.json），不在代码里重复书写
_GUARD_RULES = Path(__file__).resolve().with_name('guard_rules.json')
_GUARD_KEYWORDS = json.loads(_GUARD_RULES.read_text(encoding='utf-8')).get('keywords', []) if _GUARD_RULES.exists() else []
BANNED = [w for w in os.environ.get('PLAN_EXTRA_BANNED', '').split(',') if w] + _GUARD_KEYWORDS + ['00_内部资料', '勿外发', '硬件价', '/Users/', '/home/', '/tmp/',
          'gitlab.', 'ssh://', 'ghp_', 'gho_', 'github_pat_', 'CLOUDFLARE_API_TOKEN',
          '.harness', 'eventStreamRef', 'providerSessionId', 'runtimeSessionId', 'dispatch_', 'runtime_']
SECRET_RE = re.compile(r'sk-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----')


def section(body, title):
    m = re.search(r'^### ' + re.escape(title) + r'[^\n]*\n(.*?)(?=^### |\Z)', body, re.S | re.M)
    return m.group(1).strip() if m else ''


def clean(s):
    s = re.sub(r'(?:/Users|/home|/tmp)/[^\s`|，,）)]*', '', s or '')
    s = re.sub(r'https?://gitlab\S*', '', s)
    return re.sub(r'\s{2,}', ' ', s).strip()


def gh_json(args):
    try:
        out = subprocess.run(['gh'] + args + ['-R', REPO], check=True, capture_output=True, text=True, timeout=90).stdout
        return json.loads(out)
    except Exception as e:  # noqa
        sys.stderr.write(f'提示：gh {" ".join(args[:2])} 失败，相关状态将缺省（{e.__class__.__name__}）\n')
        return None


def ha_json(args, timeout=30):
    """运行 ha <args> --json，返回解析后的对象；evidence 若是 JSON 字符串则展开。"""
    try:
        out = subprocess.run(['ha'] + args + ['--json'], cwd=HA_CWD, check=True, capture_output=True, text=True, timeout=timeout).stdout
        d = json.loads(out)
    except Exception:
        return None
    ev = d.get('evidence')
    if isinstance(ev, str) and ev.lstrip().startswith('{'):
        try:
            d['evidence'] = json.loads(ev)
        except Exception:
            pass
    return d


def to_tpe(iso):
    if not iso:
        return ''
    try:
        dt = datetime.datetime.fromisoformat(iso.replace('Z', '+00:00'))
        return dt.astimezone(TZ).strftime('%m-%d %H:%M')
    except Exception:
        return ''


def minutes_since(iso, now):
    try:
        return int((now - datetime.datetime.fromisoformat(iso.replace('Z', '+00:00'))).total_seconds() // 60)
    except Exception:
        return None


def ci_state(rollup):
    if not rollup:
        return 'none'
    st = set()
    for c in rollup:
        v = (c.get('conclusion') or c.get('state') or c.get('status') or '').upper()
        if v in ('FAILURE', 'ERROR', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STARTUP_FAILURE'):
            st.add('failure')
        elif v in ('SUCCESS', 'NEUTRAL', 'SKIPPED'):
            st.add('success')
        else:
            st.add('pending')
    return 'failure' if 'failure' in st else 'pending' if 'pending' in st else 'success'


PHASE = {'planned': '待开始', 'active': '进行中', 'submitted': '审核中', 'in_review': '审核中',
         'blocked': '卡住', 'done': '完成', 'cancelled': '已取消'}


def collect_ha(id2num, issue_comments, now):
    """返回 (按 Issue 归并的 HA 状态 dict, 全局摘要 dict)；HA 不可用返回 ({}, None)。"""
    if os.environ.get('PLAN_NO_HA') == '1':
        return {}, None
    rows, cursor = [], None
    while True:
        d = ha_json(['task', 'list', '--limit', '200'] + (['--cursor', cursor] if cursor else []))
        if not d or not d.get('ok'):
            if not rows:
                sys.stderr.write('提示：HA 不可用（ha task list 失败），跳过 HA 状态\n')
                return {}, None
            break
        rows += d.get('rows', [])
        cursor = (d.get('page') or {}).get('nextCursor')
        if not cursor:
            break
    rows = [r for r in rows if r.get('status') != 'cancelled' or minutes_since(r.get('updatedAt'), now) < 1440]

    def detail(r):
        tid = r['taskId']
        show = ha_json(['task', 'show', tid]) or {}
        disp = ha_json(['task', 'dispatches', tid]) or {}
        return tid, (show.get('evidence') if isinstance(show.get('evidence'), dict) else {}), (disp.get('dispatches') or [])

    with ThreadPoolExecutor(max_workers=8) as ex:
        details = {tid: (ev, ds) for tid, ev, ds in ex.map(detail, rows)}

    agenda = ha_json(['agenda', '--limit', '200']) or {}
    def ids(key):
        return {x.get('taskId') for x in agenda.get(key, []) or [] if isinstance(x, dict)}
    stalled_ids = ids('stalled') | ids('awaitingRestart')
    rework_ids = ids('awaitingRework')

    # GitHub 评论里登记的 HA task → Issue
    comment_map = {}
    for n, bodies in issue_comments.items():
        for b in bodies:
            for t in re.findall(r'HA task (task_[0-9a-f]+)', b or ''):
                comment_map.setdefault(t, set()).add(n)

    def issues_of(tid, ev):
        nums = set(comment_map.get(tid, set()))
        md = ((ev.get('task') or {}).get('metadata') or {})
        slug = md.get('slug') or ''
        lead = []
        for tok in slug.split('-'):
            if tok.isdigit():
                lead.append(int(tok))
            else:
                break
        nums |= set(lead)
        for tnum in re.findall(r'T(\d{2})', md.get('idempotencyKey') or ''):
            n = id2num.get('T' + tnum)
            if n:
                nums.add(n)
        return nums

    task_issues = {r['taskId']: issues_of(r['taskId'], details[r['taskId']][0]) for r in rows}
    # 小组（squad）里的 worker 子任务：经 squadRunId 找到组长主任务，归并到同一 Issue
    squad_subject = {}
    for r in rows:
        for dsp in details[r['taskId']][1]:
            sr = dsp.get('squadRunId')
            if sr and sr not in squad_subject:
                st = ha_json(['squad', 'status', sr]) or {}
                squad_subject[sr] = {'subject': (st.get('subject') or {}).get('taskId'), 'phase': st.get('phase'), 'squad': st.get('squadId')}

    per_issue, running_sessions = {}, {}
    for r in rows:
        tid = r['taskId']
        ev, ds = details[tid]
        task = ev.get('task') or {}
        status = r.get('status') or task.get('status')
        execs = ev.get('executions') or []
        latest_exec = execs[-1] if execs else {}
        ds_sorted = sorted(ds, key=lambda x: x.get('lastObservedAt') or '')
        last = ds_sorted[-1] if ds_sorted else {}
        squad_run = next((x.get('squadRunId') for x in reversed(ds_sorted) if x.get('squadRunId')), None)
        role = 'task'
        nums = set(task_issues.get(tid, set()))
        if squad_run and squad_subject.get(squad_run, {}).get('subject') and squad_subject[squad_run]['subject'] != tid:
            nums |= task_issues.get(squad_subject[squad_run]['subject'], set())
            role = 'squad-worker'
        phase = PHASE.get(status, status or '')
        if status == 'active' and (tid in rework_ids or latest_exec.get('state') == 'changes_requested'):
            phase = '打回'
        running = [x for x in ds if ((x.get('lifecycle') or {}).get('displayStatus') == 'running'
                                    or ((x.get('lifecycle') or {}).get('policy') or {}).get('processAlive'))]
        for x in running:
            running_sessions[x.get('runtimeSessionId') or x.get('dispatchId')] = {
                'agent': x.get('agentName') or x.get('agentId') or '', 'model': (x.get('provider') or {}).get('model', ''),
                'task_title': clean(r.get('title', '')), 'issues': sorted(nums), 'squad': bool(x.get('squadRunId'))}
        def is_rev(x):
            return 'review' in (x.get('agentId') or '')
        impl = [x for x in ds_sorted if not is_rev(x)]
        revs = [x for x in running if is_rev(x)]
        reviewer = ({'name': revs[-1].get('agentName') or revs[-1].get('agentId') or '',
                     'model': (revs[-1].get('provider') or {}).get('model', '')} if revs else None)
        if impl:
            last_impl = impl[-1]
            who = {'kind': 'codex', 'name': last_impl.get('agentName') or last_impl.get('agentId') or 'Codex worker',
                   'agent_id': last_impl.get('agentId') or '', 'model': (last_impl.get('provider') or {}).get('model', '')}
        elif last:
            who = {'kind': 'codex', 'name': last.get('agentName') or last.get('agentId') or 'Codex worker',
                   'agent_id': last.get('agentId') or '', 'model': (last.get('provider') or {}).get('model', '')}
        elif status in ('active', 'submitted', 'in_review') or execs:
            who = {'kind': 'ceo', 'name': 'CEO（Grok Bot 亲自做）', 'agent_id': '', 'model': ''}
        else:
            who = None
        starts = [e.get('claimedAt') for e in execs if e.get('claimedAt')] + [x.get('lastObservedAt') for x in ds_sorted[:1] if x.get('lastObservedAt')]
        acts = [r.get('updatedAt')] + [x.get('lastObservedAt') for x in ds if x.get('lastObservedAt')]
        acts = [a for a in acts if a]
        last_act = max(acts) if acts else ''
        idle = None
        if running:
            idle = min((x.get('activityIdleMinutes') for x in running if isinstance(x.get('activityIdleMinutes'), int)), default=None)
        stuck_reason = ''
        squad_live = bool(squad_run and squad_subject.get(squad_run, {}).get('phase') and
                          re.search(r'running|leader|planning|merging', squad_subject[squad_run]['phase'] or ''))
        if tid in stalled_ids and not squad_live and not running:
            stuck_reason = 'HA 判定停滞'
        elif status == 'blocked':
            stuck_reason = 'HA 状态为 blocked'
        elif running and idle is not None and idle >= STALL_MIN:
            stuck_reason = f'worker 已 {idle} 分钟无活动'
        elif status == 'active' and not running and last and minutes_since(last_act, now) is not None and minutes_since(last_act, now) >= STALL_MIN and not stalled_ids:
            stuck_reason = f'无在跑 worker，{minutes_since(last_act, now)} 分钟无更新'
        entry = {
            'task_title': clean(r.get('title', '')), 'role': role, 'phase': phase, 'ha_status': status,
            'executor': who, 'reviewer': reviewer, 'running': len(running),
            'squad': ({'run_phase': squad_subject[squad_run]['phase'], 'squad': squad_subject[squad_run]['squad']} if squad_run else None),
            'started_at': to_tpe(min(starts)) if starts else '', 'last_activity': to_tpe(last_act),
            'last_activity_iso': last_act, 'stuck': bool(stuck_reason), 'stuck_reason': stuck_reason,
        }
        for n in nums or {None}:
            per_issue.setdefault(n, []).append(entry)

    unmapped = per_issue.pop(None, [])
    summary = {
        'running_workers': len(running_sessions), 'worker_cap': WORKER_CAP,
        'running': sorted(running_sessions.values(), key=lambda x: (x['issues'] or [999])[0]),
        'tasks_total': len(rows),
        'unmapped_active': [{'title': e['task_title'], 'phase': e['phase'], 'executor': (e['executor'] or {}).get('name', ''),
                             'last_activity': e['last_activity'], 'stuck': e['stuck']}
                            for e in unmapped if e['ha_status'] not in ('done', 'cancelled')],
    }
    return per_issue, summary


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    items = json.loads(src.read_text(encoding='utf-8'))
    id2num = {t['id']: t['issue_number'] for t in items}
    now = datetime.datetime.now(datetime.timezone.utc)

    issues = gh_json(['issue', 'list', '--state', 'all', '--limit', '200', '--json', 'number,state,assignees,closedAt,comments,body'])
    prs = gh_json(['pr', 'list', '--state', 'all', '--limit', '200', '--json',
                   'number,state,title,body,headRefName,url,isDraft,mergedAt,statusCheckRollup,reviewDecision,createdAt'])
    st = {i['number']: i for i in (issues or [])}
    comments = {i['number']: [c.get('body') or '' for c in i.get('comments', [])] for i in (issues or [])}
    human_claims = {}
    for i in issues or []:
        for c in i.get('comments', []):
            if re.match(r'\s*我来', c.get('body') or ''):
                human_claims.setdefault(i['number'], set()).add((c.get('author') or {}).get('login', ''))

    pr_map, open_prs = {}, []
    for p in prs or []:
        refs = set(int(n) for n in re.findall(r'(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?)\s+#(\d+)', p.get('body') or '', re.I))
        m = re.match(r'[a-z]+/(\d+)-', p.get('headRefName') or '')
        if m:
            refs.add(int(m.group(1)))
        state = 'MERGED' if p.get('mergedAt') else p['state']
        info = {'number': p['number'], 'state': state, 'url': p['url'], 'title': clean(p['title']),
                'draft': p.get('isDraft', False), 'ci': ci_state(p.get('statusCheckRollup')),
                'review': p.get('reviewDecision') or ''}
        for n in refs:
            pr_map.setdefault(n, []).append(info)
        if state == 'OPEN':
            open_prs.append(dict(info, issues=sorted(n for n in refs if n in st and n != p['number'])))

    ha_issue, ha_sum = collect_ha(id2num, comments, now)

    milestones, tasks = [], []
    for t in items:
        # 验收标准等正文以 GitHub 上的 Issue 为准（随时可能被修订），拿不到时用 issues.json
        body = (st.get(t['issue_number']) or {}).get('body') or t.get('body', '')
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
        ha = sorted(ha_issue.get(n, []), key=lambda e: (e['ha_status'] in ('done', 'cancelled'), e['role'] != 'task'))
        assignees = [a.get('login') for a in (s or {}).get('assignees', [])]
        humans = sorted((set(assignees) | human_claims.get(n, set())) - {''})
        executors = []
        for e in ha:
            if e['executor'] and e['ha_status'] not in ('done', 'cancelled'):
                x = dict(e['executor'])
                x['phase'] = e['phase']
                if x not in executors:
                    executors.append(x)
        if not executors:
            executors += [{'kind': 'human', 'name': h, 'agent_id': '', 'model': '', 'phase': '进行中'} for h in humans]
        main_e = next((e for e in ha if e['role'] == 'task'), ha[0] if ha else None)
        tasks.append({
            'id': t['id'], 'issue': n, 'title': clean(t['title']), 'milestone': ms.split(' ')[0],
            'labels': t.get('labels', []), 'priority': prio.group(1) if prio else '',
            'wave': t.get('wave'), 'branch': t.get('branch', ''),
            'depends_on': [{'id': d, 'issue': id2num.get(d)} for d in t.get('depends_on', [])],
            'goal': clean(goal_line), 'acceptance': acc, 'reuse': reuse,
            'squad_hint': clean(t.get('squad_hint') or re.sub(r'^- ', '', section(body, '建议拆分').split('\n')[0])),
            'state': (s['state'].lower() if s else 'unknown'),
            'assignees': assignees,
            'prs': pr_map.get(n, []),
            'live': ({
                'phase': main_e['phase'] if main_e else '',
                'executors': executors,
                'started_at': min((e['started_at'] for e in ha if e['started_at']), default=''),
                'last_activity': to_tpe(max((e['last_activity_iso'] for e in ha if e['last_activity_iso']), default='')),
                'stuck': any(e['stuck'] for e in ha if e['ha_status'] not in ('done', 'cancelled')),
                'stuck_reason': next((e['stuck_reason'] for e in ha if e['stuck'] and e['ha_status'] not in ('done', 'cancelled')), ''),
                'ha_tasks': [{'title': e['task_title'], 'phase': e['phase'], 'role': e['role']} for e in ha],
                'squad': next((e['squad'] for e in ha if e['squad']), None),
                'reviewer': next((e['reviewer'] for e in ha if e.get('reviewer')), None),
            } if (ha or humans) else None),
        })
    data = {
        'repo': REPO,
        'generated_at': datetime.datetime.now(TZ).strftime('%Y-%m-%d %H:%M（台北时间）'),
        'generated_ts': int(now.timestamp()),
        'status_source': 'github' if issues is not None else 'none',
        'ha': ({
            'source': 'ha', 'updated_at': datetime.datetime.now(TZ).strftime('%Y-%m-%d %H:%M（台北时间）'),
            'running_workers': ha_sum['running_workers'], 'worker_cap': ha_sum['worker_cap'],
            'running': ha_sum['running'], 'tasks_total': ha_sum['tasks_total'],
            'unmapped_active': ha_sum['unmapped_active'],
        } if ha_sum else {'source': 'none', 'updated_at': '', 'running_workers': 0, 'worker_cap': WORKER_CAP, 'running': []}),
        'open_prs': sorted(open_prs, key=lambda x: x['number']),
        'milestones': milestones, 'tasks': tasks,
    }
    text = json.dumps(data, ensure_ascii=False, indent=1)
    hits = [b for b in BANNED if b in text] + (['疑似密钥'] if SECRET_RE.search(text) else [])
    if hits:
        raise SystemExit('错误：计划数据里出现不应对外的字样，已中止：' + ', '.join(hits))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 'plan-data.json').write_text(text + '\n', encoding='utf-8')
    (OUT_DIR / 'plan-data.js').write_text('window.JK_PLAN = ' + text + ';\n', encoding='utf-8')
    closed = sum(1 for x in tasks if x['state'] == 'closed')
    live = sum(1 for x in tasks if x['live'])
    print(f'已生成 plan-data.json：{len(milestones)} 个里程碑、{len(tasks)} 个任务，已关闭 {closed}，'
          f'有执行者 {live}，在跑 worker {data["ha"]["running_workers"]}/{WORKER_CAP}，待合并 PR {len(open_prs)}，'
          f'状态来源 GitHub={data["status_source"]} HA={data["ha"]["source"]}')


if __name__ == '__main__':
    main()

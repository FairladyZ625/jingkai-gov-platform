/* =====================================================================
 * 管理后台（复用 haiknow core/web/admin 布局：左侧分类 + 右侧表格；接口对应 admin_identity / rbac / audit）
 * 账号 · 组织 · 角色与授权 · 模型 · 技能审核 · 审计日志 · 用量
 * ===================================================================== */
(function () {
  const { esc, icon, tag, toast, modal, confirm, appIcon } = JK; const API = window.JKApi;
  const TABS = [['users', '账号', 'users'], ['org', '组织', 'building'], ['grants', '角色与授权', 'shield'], ['models', '模型', 'cpu'], ['skills', '技能审核', 'skill'], ['audit', '审计日志', 'history'], ['usage', '用量', 'chart']];
  const AUDIT_PAGE = 50;
  const APP_LABELS = { platform: '平台', policy: '政策兑现', enterprise: '企业管理', meeting: '会议记录', document: '公文协作', kb: '知识库', skills: '技能中心', computer: '电脑操作', admin: '管理后台' };
  const ACTION_LABELS = {
    login: '登录', logout: '退出登录', 'auth.login': '登录', 'auth.logout': '退出登录', 'auth.login.failed': '登录失败',
    'job.failed': '任务失败', 'job.start': '启动任务', 'job.done': '任务完成', 'job.step.running': '步骤执行中', 'job.step.done': '步骤已完成',
    'ai.chat': '对话模型调用', 'ai.outbound_denied': '外发被拦截', 'ai.route.test': '测试模型路由', 'model.select': '选择模型', 'model.enable': '调整模型启用状态',
    'document.draft.mock': '生成模拟公文初稿', 'document.draft.policy-template': '生成政策模板初稿', 'document.check': '核查公文', 'audit.export': '导出审计日志',
  };
  const appLabel = (code) => Object.hasOwn(APP_LABELS, code) ? APP_LABELS[code] : (JK.registry[code]?.manifest?.name || code);
  const actionLabel = (code) => Object.hasOwn(ACTION_LABELS, code) ? ACTION_LABELS[code] : code;
  const auditClock = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  function auditTime(value) {
    const raw = String(value || '');
    const stamp = new Date(raw.replace(' ', 'T') + (/^\d{4}-\d\d-\d\d[T ]\d\d:\d\d(?::\d\d(?:\.\d+)?)?$/.test(raw) ? '+08:00' : ''));
    if (Number.isNaN(stamp.getTime())) return raw || '—';
    const { month, day, hour, minute } = Object.fromEntries(auditClock.formatToParts(stamp).map(({ type, value }) => [type, value]));
    return `${month}月${day}日 ${hour}:${minute}`;
  }
  function csvCell(value) {
    const text = String(value ?? '');
    const safe = /^[\t\r\n]|^[\s\uFEFF]*[=+\-@＝＋－＠]/.test(text) ? "'" + text : text;
    return `"${safe.replace(/"/g, '""')}"`;
  }
  let SH = null;
  async function render(el, tab, shell) {
    SH = shell; el.dataset.tab = tab;
    el.innerHTML = `<div class="app-head">${appIcon('admin', 'lg')}<div><h2>管理后台</h2><div class="sub">改动立即生效，并写入审计日志</div></div></div>
      <div class="tabs adm-nav" style="margin-bottom:20px">${TABS.map(([id, n]) => `<button class="tab ${id === tab ? 'on' : ''}" data-tab="${id}" data-op="admin.tab-${id}">${n}</button>`).join('')}</div><div class="adm-body" style="min-width:0"><div class="skel" style="width:40%"></div></div>`;
    el.querySelector('.adm-nav').onclick = (e) => { const b = e.target.closest('[data-tab]'); if (b) render(el, b.dataset.tab, shell); };
    const body = el.querySelector('.adm-body');
    try { await (V[tab] || V.users)(body, el); } catch (e) { body.innerHTML = JK.empty({ icon: 'alert', title: '加载失败', desc: e.message }); }
  }
  const re = (el) => render(el, el.dataset.tab, SH);
  const V = {
    async users(b, el) {
      const r = await API.admin.users(); const roles = r.roles, deps = r.departments; const q = el.dataset.q || '';
      const list = r.items.filter((u) => !q || (u.name + u.username + u.dept).includes(q));
      b.innerHTML = `<div class="row" style="margin-bottom:16px"><div class="search grow" style="max-width:280px">${icon('search')}<input class="input sm" placeholder="搜索姓名 / 账号 / 部门" value="${esc(q)}" data-q></div><span class="sp"></span><span class="t-3 t-sm">${r.items.filter((u) => u.status === 'active').length} 个启用账号</span><button class="btn primary" data-op="admin.add-user">${icon('plus')}新增账号</button></div>
        <div class="card flat" style="overflow:auto"><table class="tbl"><thead><tr><th>姓名</th><th>账号</th><th>部门</th><th>角色</th><th>状态</th><th class="r"></th></tr></thead><tbody>${list.map((u) => `<tr><td style="white-space:nowrap"><div class="row"><span class="avatar h-${JK.hue((roles.find((x) => x.id === u.role) || {}).name, 'role')}" style="width:24px;height:24px;font-size:11px">${esc(u.name[0])}</span>${esc(u.name)}</div></td><td class="mono t-2">${esc(u.username)}</td><td class="t-2"><div class="clip" style="max-width:130px" title="${esc(u.dept)}">${esc((u.dept || '').split(' · ').pop())}</div></td><td><select class="select input sm" style="width:108px" data-role="${u.id}">${roles.map((ro) => `<option value="${ro.id}" ${ro.id === u.role ? 'selected' : ''}>${esc(ro.name)}</option>`).join('')}</select></td><td>${tag(u.status === 'active' ? '在线' : '已停用', 'status')}</td><td class="r"><button class="btn icon sm ghost" data-more="${u.id}" data-st="${u.status}" title="更多操作">${icon('more')}</button></td></tr>`).join('')}</tbody></table></div>`;
      const qi = b.querySelector('[data-q]'); qi.oninput = () => { el.dataset.q = qi.value; clearTimeout(qi._t); qi._t = setTimeout(() => re(el).then(() => { const n = el.querySelector('[data-q]'); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }), 300); };
      b.querySelectorAll('[data-role]').forEach((s) => (s.onchange = async () => { try { await API.admin.patchUser(s.dataset.role, { role: s.value }); toast('角色已更新，立即生效'); } catch (e) { toast(e.message, { type: 'err' }); re(el); } }));
      b.querySelectorAll('[data-more]').forEach((x) => (x.onclick = () => { const on = x.dataset.st === 'active'; JK.menu(x, [{ v: 'reset', icon: 'key', label: '重置密码' }, { v: 'toggle', icon: on ? 'lock' : 'check', label: on ? '停用账号' : '启用账号' }], async (v) => {
        const id = x.dataset.more;
        if (v === 'reset') { if (!(await confirm('密码将重置为 jk123456。'))) return; await API.admin.patchUser(id, { resetPassword: true }); toast('已重置为 jk123456'); }
        if (v === 'toggle') { if (on && !(await confirm('停用后该账号无法登录，已有数据保留。', { okText: '停用', danger: true }))) return; try { await API.admin.patchUser(id, { status: on ? 'disabled' : 'active' }); toast(on ? '已停用' : '已启用'); re(el); } catch (e) { toast(e.message, { type: 'err' }); } }
      }); }));
      b.querySelector('[data-op="admin.add-user"]').onclick = () => modal({ title: '新增账号', width: 460, okText: '创建', body: `<div class="col gap3"><div class="grid g2"><div class="field"><label>姓名</label><input class="input" data-op="admin.u-name" placeholder="如 张晓"></div><div class="field"><label>账号</label><input class="input" data-op="admin.u-username" placeholder="登录名，如 zhangxiao"></div></div><div class="grid g2"><div class="field"><label>角色</label><select class="select" data-op="admin.u-role">${roles.map((ro) => `<option value="${ro.id}" ${ro.id === 'member' ? 'selected' : ''}>${esc(ro.name)}</option>`).join('')}</select></div><div class="field"><label>部门</label><select class="select" data-op="admin.u-dept">${deps.filter((d) => d.parent).map((d) => `<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></div></div><div class="hint t-3 t-xs">初始密码 jk123456，首次登录后可在个人设置修改。</div></div>`,
        foot: '', ok: async (d) => { const v = (s) => d.querySelector(`[data-op="admin.u-${s}"]`).value.trim(); try { await API.admin.createUser({ name: v('name'), username: v('username'), role: v('role'), deptId: v('dept') }); toast('账号已创建'); re(el); } catch (e) { toast(e.message, { type: 'err' }); return false; } },
        onMount: (d) => { const ok = d.querySelector('[data-ok]'); ok.dataset.op = 'admin.u-save'; } });
    },
    async org(b, el) {
      const r = await API.admin.users(); const deps = r.departments; const cnt = (id) => r.items.filter((u) => u.deptId === id).length;
      const tree = (pid, lv) => deps.filter((d) => d.parent === pid).map((d) => `<div class="li" style="padding-left:${12 + lv * 20}px">${icon(lv ? 'folder' : 'building')}<span class="grow">${esc(d.name)}</span><span class="t-3 t-xs">${cnt(d.id)} 人</span><button class="btn sm ghost" data-ren="${d.id}">重命名</button><button class="btn sm ghost danger" data-del="${d.id}">删除</button></div>${tree(d.id, lv + 1)}`).join('');
      b.innerHTML = `<div class="row" style="margin-bottom:16px"><span class="t-2 t-sm">部门有成员或子部门时不能删除</span><span class="sp"></span><button class="btn primary" data-add>${icon('plus')}新增部门</button></div><div class="card flat" style="padding:6px"><div class="list">${tree(null, 0)}</div></div>`;
      b.querySelector('[data-add]').onclick = () => modal({ title: '新增部门', okText: '创建', body: `<div class="col gap3"><div class="field"><label>名称</label><input class="input" id="dn"></div><div class="field"><label>上级</label><select class="select" id="dp">${deps.map((d) => `<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></div></div>`, ok: async (d) => { try { await API.admin.addDept({ name: d.querySelector('#dn').value.trim(), parent: d.querySelector('#dp').value }); toast('已新增'); re(el); } catch (e) { toast(e.message, { type: 'err' }); return false; } } });
      b.querySelectorAll('[data-ren]').forEach((x) => (x.onclick = async () => { const n = prompt('新名称', deps.find((d) => d.id === x.dataset.ren).name); if (!n) return; await API.admin.patchDept(x.dataset.ren, { name: n }); toast('已重命名'); re(el); }));
      b.querySelectorAll('[data-del]').forEach((x) => (x.onclick = async () => { if (!(await confirm('确认删除这个部门？', { danger: true, okText: '删除' }))) return; try { await API.admin.delDept(x.dataset.del); toast('已删除'); re(el); } catch (e) { toast(e.message, { type: 'err' }); } }));
    },
    async grants(b, el) {
      const r = await API.admin.grants(); const acts = r.actions; const apps = r.apps;
      b.innerHTML = `<div class="callout h-blue" style="margin-bottom:16px">${icon('info')}<span>勾选即生效：查看 / 操作 / 审签 / 管理。外部协作者开启“脱敏”后，电话、营收等字段自动打码。</span></div>
        <div class="card flat" style="overflow:auto"><table class="tbl mtx"><thead><tr><th>应用</th>${r.roles.map((ro) => `<th data-op="admin.grant-${ro.id}">${tag(ro.name, 'role')}</th>`).join('')}</tr></thead><tbody>${apps.map((a) => `<tr><td style="white-space:nowrap">${a.id === '*' ? '<b>全部应用</b>' : esc(a.name)}</td>${r.roles.map((ro) => { const g = (r.grants[ro.id] || {})[a.id] || []; return `<td><span class="cell">${acts.map(([k, n]) => `<button class="cb ${g.includes(k) ? 'on' : ''}" data-r="${ro.id}" data-a="${a.id}" data-k="${k}" title="${esc(ro.name)} · ${n}">${n[0]}</button>`).join('')}</span></td>`; }).join('')}</tr>`).join('')}
          <tr><td>敏感字段脱敏</td>${r.roles.map((ro) => `<td><span class="switch ${ro.mask ? 'on' : ''}" data-mask="${ro.id}" style="display:inline-block"></span></td>`).join('')}</tr></tbody></table></div>
        <div class="t-3 t-xs" style="margin-top:8px">查 = 查看　操 = 操作　审 = 审签　管 = 管理</div>`;
      b.querySelectorAll('.cb').forEach((x) => (x.onclick = async () => { const cur = ((r.grants[x.dataset.r] || {})[x.dataset.a] || []).slice(); const k = x.dataset.k; const next = cur.includes(k) ? cur.filter((y) => y !== k) : [...cur, k]; try { const out = await API.admin.setGrant(x.dataset.r, x.dataset.a, next); r.grants = out.grants; x.classList.toggle('on', next.includes(k)); toast('授权已更新'); } catch (e) { toast(e.message, { type: 'err' }); } }));
      b.querySelectorAll('[data-mask]').forEach((x) => (x.onclick = async () => { const on = !x.classList.contains('on'); await API.admin.patchRole(x.dataset.mask, { mask: on }); x.classList.toggle('on', on); toast(on ? '已开启脱敏' : '已关闭脱敏'); }));
    },
    async models(b, el) {
      const r = await API.models.list(); const groups = {}; r.items.forEach((m) => (groups[m.group] = groups[m.group] || []).push(m));
      b.innerHTML = `<div class="callout h-amber" style="margin-bottom:16px">${icon('shield')}<span>政务数据不出境：海外模型默认关闭。企业台账等敏感数据自动路由到本地模型。</span></div>` + Object.entries(groups).map(([g, list]) => `<div class="sect">${esc(g)}</div><div class="card flat"><div class="list lined">${list.map((m) => `<div class="li" style="cursor:default"><span class="sdot" style="--tf:var(--t-${m.kind === 'local' ? 'green' : m.kind === 'overseas' ? 'gray' : 'blue'}-fg)"></span><span class="grow"><div class="ttl">${esc(m.name)} <span class="t-3 t-xs">${esc(m.provider)}</span></div><div class="meta">${esc(m.desc)}</div></span>${(m.tags || []).slice(0, 1).map((t) => tag(t)).join('')}<span class="switch ${m.enabled ? 'on' : ''}" data-m="${m.id}" title="启用 / 停用"></span></div>`).join('')}</div></div>`).join('') + `<div class="sect">能力路由</div><div class="card tight"><div class="grid g2">${(r.capabilities || []).map((c) => `<div class="row"><span class="t-2" style="width:80px">${esc(c.name)}</span><span class="t-sm">${esc(c.route)}</span></div>`).join('')}</div></div>`;
      b.querySelectorAll('[data-m]').forEach((x) => (x.onclick = async () => { const on = !x.classList.contains('on'); if (x.dataset.m === 'auto' && !on) return toast('“自动选择”不能停用', { type: 'warn' }); try { await API.models.patch(x.dataset.m, { enabled: on }); x.classList.toggle('on', on); await SH.modelsReload(); toast(on ? '已启用' : '已停用'); } catch (e) { toast(e.message, { type: 'err' }); } }));
    },
    async skills(b, el) {
      const r = await API.reviews.list(); const list = (r.items || []).filter((x) => x.type === 'skill');
      b.innerHTML = `<div class="t-2 t-sm" style="margin-bottom:12px">同事申请“全区公开”的技能，审核通过后出现在技能中心的推荐里。</div><div class="card flat"><div class="list lined">${list.map((x) => `<div class="li" style="cursor:default">${appIcon('skills', 'sm')}<span class="grow"><div class="ttl">${esc(x.title.replace('技能上架申请：', ''))}</div><div class="meta">${esc(x.meta || '')}</div></span>${tag(x.status === 'pending' ? '待上架审核' : x.status === 'approved' ? '已上架' : '已驳回')}${x.status === 'pending' ? `<button class="btn sm" data-d="reject" data-id="${x.id}">驳回</button><button class="btn sm soft" data-d="approve" data-id="${x.id}" data-op="admin.skill-approve">通过上架</button>` : ''}</div>`).join('') || JK.empty({ icon: 'skill', title: '没有待审核的技能' })}</div></div>`;
      b.querySelectorAll('[data-d]').forEach((x) => (x.onclick = async () => { await API.reviews.decide(x.dataset.id, { decision: x.dataset.d, comment: x.dataset.d === 'reject' ? '请补充效果样例' : '' }); toast(x.dataset.d === 'approve' ? '已上架' : '已驳回'); re(el); }));
    },
    async audit(b, el) {
      const offset = Number(el.dataset.auditOffset) || 0;
      const r = await API.audit.list({ limit: AUDIT_PAGE, offset });
      if (!b.isConnected) return;
      const items = (r.items || []).map((x) => Array.isArray(x) ? { at: x[0], user: x[1], app: x[2], action: x[3], model: x[4] } : x);
      const total = r.total ?? items.length;
      if (!items.length && offset && total <= offset) { el.dataset.auditOffset = Math.max(0, offset - AUDIT_PAGE); return re(el); }
      const range = total ? `第 ${offset + 1}–${offset + items.length} 条 · 共 ${total} 条` : '暂无审计记录';
      b.innerHTML = `<div class="row wrap gap2" style="margin-bottom:16px"><div class="search grow" style="max-width:280px">${icon('filter')}<input class="input sm" placeholder="筛选本页人员、应用或动作" aria-label="筛选本页人员、应用或动作" value="${esc(el.dataset.af || '')}" data-af></div><span class="sp"></span><span class="t-3 t-sm">${range}</span><button class="btn sm" data-audit-step="-1" ${offset ? '' : 'disabled'}>上一页</button><button class="btn sm" data-audit-step="1" ${offset + items.length < total ? '' : 'disabled'}>下一页</button><button class="btn" title="导出本页筛选结果" data-csv>${icon('download')}导出 CSV</button></div>
        <div class="card flat" style="overflow:auto"><table class="tbl"><thead><tr><th>时间</th><th>人员</th><th>应用</th><th>动作</th><th>模型</th></tr></thead><tbody></tbody></table></div>`;
      const input = b.querySelector('[data-af]'), body = b.querySelector('tbody'), exportButton = b.querySelector('[data-csv]');
      let list = [];
      const draw = () => {
        const query = input.value.trim().toLowerCase();
        list = items.filter((x) => !query || [x.user, x.app, x.action, appLabel(x.app), actionLabel(x.action)].join(' ').toLowerCase().includes(query));
        body.innerHTML = list.map((x) => `<tr class="audit-row"><td class="num" title="${esc(x.at)}" style="white-space:nowrap">${esc(auditTime(x.at))}</td><td style="white-space:nowrap">${esc(x.user || '—')}</td><td title="${esc(x.app)}">${tag(appLabel(x.app), null, { cls: 'plain' })}</td><td title="${esc(x.action)}">${esc(actionLabel(x.action) || '—')}</td><td class="t-3" style="white-space:nowrap">${esc(x.model || '—')}</td></tr>`).join('') || `<tr><td colspan="5" class="t-3">${query ? '本页未找到符合条件的记录' : '暂无审计记录'}</td></tr>`;
        exportButton.disabled = !list.length;
      };
      input.oninput = () => { el.dataset.af = input.value; draw(); };
      draw();
      b.querySelectorAll('[data-audit-step]').forEach((button) => (button.onclick = () => { el.dataset.auditOffset = offset + Number(button.dataset.auditStep) * AUDIT_PAGE; return re(el); }));
      exportButton.onclick = () => { const csv = '\ufeff时间,人员,应用,动作,模型\r\n' + list.map((x) => [x.at, x.user, x.app, x.action, x.model || ''].map(csvCell).join(',')).join('\r\n'); JK.download('审计日志.csv', csv, 'text/csv;charset=utf-8'); toast('已导出本页审计日志'); };
    },
    async usage(b) {
      const { usage: u } = await API.admin.usage();
      if (!u) throw Error('用量接口未返回统计');
      const live = Array.isArray(u.byApp);
      const note = live ? `北京时间统计对话模型调用尝试，含失败与模拟；任务状态不计入调用。今日外发拦截 ${u.blockedToday} 次，本周 ${u.blockedWeek} 次，均未发给模型。` : '以下为离线演示数据。';
      const local = live ? u.localShare : (u.byModel || []).find(([name]) => /本地/.test(name))?.[1];
      const kpi = (label, count, title = '') => `<div class="card" title="${esc(title)}"><div class="kpi"><span class="v num">${esc(count)}</span><span class="l">${label}</span></div></div>`;
      const breakdown = (label, suffix, rows, isApp) => `<div class="card"><div class="card-h"><span class="ttl">${label}</span></div>${rows.map(({ name, calls }) => {
        const width = live ? (u.week ? calls * 100 / u.week : 0) : calls;
        return `<div class="bar-row"><span class="l clip">${esc(isApp ? appLabel(name) : name)}</span><span class="bar"><i style="width:${Math.max(0, Math.min(100, Number(width) || 0))}%"></i></span><span class="v num">${esc(calls)}${suffix}</span></div>`;
      }).join('') || '<div class="t-3 t-sm" style="padding:12px">本周暂无模型调用记录</div>'}</div>`;
      const arrays = (rows) => rows.map(([name, calls]) => ({ name, calls }));
      b.innerHTML = `<p class="t-3 t-sm" style="margin-bottom:12px">${esc(note)}</p><div class="grid g3" style="margin-bottom:16px">${kpi('今日调用', u.today ?? '—')}${kpi('本周调用', u.week ?? '—')}${kpi('本地模型占比', local == null ? '—' : `${local}%`, local == null ? '无调用或历史记录缺少模型来源' : '本周真实本地调用尝试占比，不含模拟')}</div>
        <div class="grid g2">${breakdown('按应用', live ? ' 次' : '%', live ? u.byApp : arrays(Object.entries(u.byApp || {})), true)}${breakdown('按模型', live ? ' 次' : '%', live ? u.byModel : arrays(u.byModel || []), false)}</div>`;
    },
  };
  window.JKAdmin = { render };
})();

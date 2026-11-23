/* =====================================================================
 * 管理后台（复用 haiknow core/web/admin 布局：左侧分类 + 右侧表格；接口对应 admin_identity / rbac / audit）
 * 账号 · 组织 · 角色与授权 · 模型 · 技能审核 · 审计日志 · 用量
 * ===================================================================== */
(function () {
  const { esc, icon, tag, toast, modal, confirm, appIcon } = JK; const API = window.JKApi;
  const TABS = [['users', '账号', 'users'], ['org', '组织', 'building'], ['grants', '角色与授权', 'shield'], ['models', '模型', 'cpu'], ['skills', '技能审核', 'skill'], ['audit', '审计日志', 'history'], ['usage', '用量', 'chart']];
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
  function issuePassword() {
    const bytes = crypto.getRandomValues(new Uint8Array(18));
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  }
  function showIssuedPassword(username, secret, created) {
    modal({ title: created ? '账号已创建' : '口令已重置', width: 460, okText: '我已保存', ok: () => {},
      body: `<div class="stack"><p ${created ? 'data-op="admin.u-created"' : ''}>账号 <b>${esc(username)}</b> 的口令仅在本次弹窗查看；关闭后无法找回。请在非共享屏幕下查看，并安全交付给本人。</p><div data-secret-slot></div><button class="btn" data-reveal-password>查看口令</button><p class="t-3 t-xs">登录后可在个人设置中修改口令。</p></div>`,
      onMount(d) {
        const reveal = d.querySelector('[data-reveal-password]');
        reveal.onclick = () => {
          reveal.disabled = true;
          const field = document.createElement('input');
          field.className = 'input mono'; field.readOnly = true; field.autocomplete = 'off'; field.spellcheck = false;
          field.setAttribute('aria-label', '本次生成的口令'); field.setAttribute('data-issued-password', '');
          field.value = secret; secret = '';
          d.querySelector('[data-secret-slot]').append(field);
          field.focus(); field.select();
        };
      },
    });
  }
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
        if (v === 'reset') {
          if (!(await confirm('将生成独立的新口令，原口令不再可用。确认重置？', { okText: '重置', danger: true }))) return;
          try {
            const password = issuePassword();
            const reply = await API.admin.patchUser(id, { resetPassword: password });
            if (reply.item?.id !== id) throw Error('没有收到口令重置回执，请核对账号状态');
            if (el.isConnected) showIssuedPassword(reply.item.username, password, false);
          } catch (e) { toast(e.message, { type: 'err' }); }
          return;
        }
        if (v === 'toggle') { if (on && !(await confirm('停用后该账号无法登录，已有数据保留。', { okText: '停用', danger: true }))) return; try { await API.admin.patchUser(id, { status: on ? 'disabled' : 'active' }); toast(on ? '已停用' : '已启用'); re(el); } catch (e) { toast(e.message, { type: 'err' }); } }
      }); }));
      b.querySelector('[data-op="admin.add-user"]').onclick = () => modal({ title: '新增账号', width: 460, okText: '创建', body: `<div class="col gap3"><div class="grid g2"><div class="field"><label>姓名</label><input class="input" data-op="admin.u-name" placeholder="如 张晓"></div><div class="field"><label>账号</label><input class="input" data-op="admin.u-username" placeholder="登录名，如 zhangxiao"></div></div><div class="grid g2"><div class="field"><label>角色</label><select class="select" data-op="admin.u-role">${roles.map((ro) => `<option value="${ro.id}" ${ro.id === 'member' ? 'selected' : ''}>${esc(ro.name)}</option>`).join('')}</select></div><div class="field"><label>部门</label><select class="select" data-op="admin.u-dept">${deps.filter((d) => d.parent).map((d) => `<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></div></div><div class="hint t-3 t-xs">系统为新账号生成独立口令。创建成功后，该口令可在结果弹窗查看一次。</div></div>`,
        foot: '', ok: async (d) => {
          const submit = d.querySelector('[data-ok]'); if (submit.disabled) return false;
          submit.disabled = true;
          const v = (s) => d.querySelector(`[data-op="admin.u-${s}"]`).value.trim();
          try {
            const password = issuePassword();
            const reply = await API.admin.createUser({ name: v('name'), username: v('username'), role: v('role'), deptId: v('dept') || null, password });
            if (!reply.item?.id || reply.item.status !== 'active') throw Error('没有收到账号创建并启用的回执，请核对账号状态');
            if (el.isConnected) { showIssuedPassword(reply.item.username, password, true); re(el); }
          } catch (e) { submit.disabled = false; toast(e.message, { type: 'err' }); return false; }
        },
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
      const r = await API.audit.list(); const items = (r.items || []).map((x) => Array.isArray(x) ? { at: x[0], user: x[1], app: x[2], action: x[3], model: x[4] } : x);
      const f = el.dataset.af || ''; const list = items.filter((x) => !f || [x.user, x.app, x.action].join(' ').includes(f));
      b.innerHTML = `<div class="row" style="margin-bottom:16px"><div class="search grow" style="max-width:280px">${icon('filter')}<input class="input sm" placeholder="按人 / 应用 / 动作筛选" value="${esc(f)}" data-af></div><span class="sp"></span><span class="t-3 t-sm">${list.length} 条</span><button class="btn" data-csv>${icon('download')}导出 CSV</button></div>
        <div class="card flat" style="overflow:auto"><table class="tbl"><thead><tr><th>时间</th><th>人员</th><th>应用</th><th>动作</th><th>模型</th></tr></thead><tbody>${list.slice(0, 60).map((x) => `<tr class="audit-row"><td class="num" style="white-space:nowrap">${esc((x.at || '').slice(5))}</td><td style="white-space:nowrap">${esc(x.user)}</td><td>${tag(x.app, null, { cls: 'plain' })}</td><td>${esc(x.action)}</td><td class="t-3" style="white-space:nowrap">${esc(x.model || '—')}</td></tr>`).join('')}</tbody></table></div>`;
      const fi = b.querySelector('[data-af]'); fi.oninput = () => { el.dataset.af = fi.value; clearTimeout(fi._t); fi._t = setTimeout(() => re(el).then(() => { const n = el.querySelector('[data-af]'); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }), 300); };
      b.querySelector('[data-csv]').onclick = () => { const csv = '\ufeff时间,人员,应用,动作,模型\n' + list.map((x) => [x.at, x.user, x.app, x.action, x.model || ''].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n'); JK.download('审计日志.csv', csv, 'text/csv;charset=utf-8'); toast('已导出'); };
    },
    async usage(b) {
      const r = await API.admin.usage(); const u = r.usage || {}; const byApp = u.byApp || {}; const names = { policy: '政策兑现', enterprise: '企业管理', meeting: '会议记录', document: '公文协作' }; const tot = Object.values(byApp).reduce((a, c) => a + c, 0) || 1;
      b.innerHTML = `<div class="grid g3" style="margin-bottom:16px"><div class="card"><div class="kpi"><span class="v num">${u.today || 0}</span><span class="l">今日调用</span></div></div><div class="card"><div class="kpi"><span class="v num">${u.week || 0}</span><span class="l">本周调用</span></div></div><div class="card"><div class="kpi"><span class="v num">${(u.byModel || []).find((x) => /本地/.test(x[0])) ? (u.byModel.find((x) => /本地/.test(x[0]))[1]) + '%' : '—'}</span><span class="l">本地模型占比</span></div></div></div>
        <div class="grid g2"><div class="card"><div class="card-h"><span class="ttl">按应用</span></div>${Object.entries(byApp).map(([k, v]) => `<div class="bar-row"><span class="l row">${appIcon(k, 'sm')}${names[k] || k}</span><span class="bar"><i style="width:${Math.round((v / tot) * 100)}%"></i></span><span class="v num">${v}%</span></div>`).join('')}</div>
        <div class="card"><div class="card-h"><span class="ttl">按模型</span></div>${(u.byModel || []).map(([k, v]) => `<div class="bar-row"><span class="l clip">${esc(k)}</span><span class="bar"><i style="width:${v}%"></i></span><span class="v num">${v}%</span></div>`).join('')}</div></div>`;
    },
  };
  window.JKAdmin = { render };
})();

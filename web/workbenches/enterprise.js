/* 企业服务工作台：仅使用既有企业 API，不持有第二份业务数据。 */
(function () {
  const { esc, icon, tag } = JK;
  const statuses = ['待分派', '办理中', '待补材料', '已办结'];
  const views = { overview: '工作概览', companies: '企业档案', visits: '联系与走访', issues: '诉求看板' };
  const route = (view, params = {}) => view + (Object.keys(params).length ? '?' + new URLSearchParams(params) : '');
  const day = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date());
  const overdue = i => i.status !== '已办结' && /^\d{4}-\d{2}-\d{2}$/.test(i.due || '') && i.due < day();
  const text = value => esc(value === undefined || value === null || value === '' ? '—' : value);
  const option = (value, label, selected) => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(label)}</option>`;
  const pill = status => tag(status, 'issueStatus');

  JKWorkbench.register('enterprise', { mount(el, ctx) {
    el.classList.add('wb-enterprise');
    const api = ctx.api, pieces = (ctx.recordId || 'overview').split('?');
    const view = [...Object.keys(views), 'company', 'issue'].includes(pieces[0]) ? pieces[0] : 'overview';
    const params = new URLSearchParams(pieces.slice(1).join('?'));
    let alive = true, sequence = 0, companies = [], issues = [], detail = null, form = null, notice = '', error = '', busy = false;
    const live = () => alive && ctx.can('view');
    const canWrite = () => live() && ctx.can('operate');
    const go = (v, p) => { const next = route(v, p); if (next === ctx.recordId) { form = null; return load(); } return ctx.open(next); };
    const name = id => { const e = companies.find(c => c.id === id); return e?.short || e?.name || '企业档案'; };
    const activeTab = view === 'company' ? 'companies' : view === 'issue' ? 'issues' : view;
    const currentCompany = () => view === 'company' ? params.get('id') : params.get('company');
    const button = (action, label, attrs = '', primary = false) => `<button type="button" class="btn ${primary ? 'primary' : ''}" data-action="${action}" ${attrs}>${label}</button>`;
    const writeButton = (action, label, attrs = '', primary = false) => canWrite() ? button(action, label, `data-write ${attrs}`, primary) : '';
    const empty = message => `<div class="ew-empty">${esc(message)}</div>`;
    const field = (label, key, value = '', type = 'text', required = false) => `<label class="ew-field">${label}<input class="input" name="${key}" type="${type}" value="${esc(value)}" ${required ? 'required' : ''} ${type === 'number' ? 'min="0" step="1"' : ''}></label>`;
    const area = (label, key, value = '', required = false) => `<label class="ew-field ew-wide">${label}<textarea class="input" name="${key}" rows="4" ${required ? 'required' : ''}>${esc(value)}</textarea></label>`;
    const select = (label, key, values, selected = '') => `<label class="ew-field">${label}<select class="select" name="${key}">${values.map(v => option(v, v || '未指定', selected)).join('')}</select></label>`;
    const companySelect = (selected = '', required = false) => `<label class="ew-field">选择企业<select class="select" name="company" ${required ? 'required' : ''}>${option('', '请选择企业', selected)}${companies.map(c => option(c.id, c.name, selected)).join('')}</select></label>`;

    function shell(content) {
      el.innerHTML = `<div class="ew-top"><nav class="ew-tabs" aria-label="企业服务导航">${Object.entries(views).map(([v, title]) => `<button type="button" class="${activeTab === v ? 'on' : ''}" data-route="${v}" ${activeTab === v ? 'aria-current="page"' : ''}>${title}</button>`).join('')}</nav>${JKHttp.mode('enterprise') === 'mock' ? '<span class="tag">演示数据 · 本机保存</span>' : ''}</div>
        ${notice ? `<div class="ew-notice" role="status">${esc(notice)}</div>` : ''}
        <div data-view="${view}">${content}</div>`;
    }
    async function load(message = '') {
      const ticket = ++sequence; error = ''; notice = message;
      shell('<div class="ew-empty" role="status">正在读取企业服务记录…</div>');
      try {
        const [c, i] = await Promise.all([api.list({ sort: 'name' }), api.issues()]);
        if (!live() || ticket !== sequence) return;
        companies = c.items; issues = i.items;
        const cid = view === 'company' ? params.get('id') : view === 'visits' ? params.get('company') : null;
        detail = cid ? await api.get(cid) : null;
        if (!live() || ticket !== sequence) return;
        render();
      } catch (e) {
        if (!live() || ticket !== sequence) return;
        error = e.message || '读取失败，请稍后重试';
        shell(`<div class="ew-empty" role="alert"><h2>暂时无法读取记录</h2><p>${esc(error)}</p>${button('retry', '重试')}</div>`);
      }
    }
    function issueCard(i) {
      return `<button type="button" class="ew-issue" data-issue-card="${esc(i.id)}"><span class="ew-card-meta">${esc(i.entName || name(i.entId))}${overdue(i) ? '<span class="tag">已逾期</span>' : ''}</span><strong>${esc(i.title)}</strong><span>${esc(i.next || '下一步待明确')}</span><span class="ew-card-meta">${esc(i.owner || '待分派')}<span>${i.due ? '期限 ' + esc(i.due) : '未设期限'}</span></span></button>`;
    }
    function overview() {
      const pending = issues.filter(i => i.status === '待分派'), handling = issues.filter(i => i.status === '办理中'), late = issues.filter(overdue);
      const metrics = [['companies', '企业档案', companies.length, 'companies'], ['pending', '待分派诉求', pending.length, route('issues', { status: '待分派' })], ['handling', '办理中诉求', handling.length, route('issues', { status: '办理中' })], ['overdue', '逾期未办结', late.length, route('issues', { overdue: '1' })]];
      const attention = issues.filter(i => i.status !== '已办结').sort((a, b) => Number(overdue(b)) - Number(overdue(a)) || (a.due || '9999').localeCompare(b.due || '9999')).slice(0, 6);
      return `<div class="ew-heading"><div><h2>把企业服务接着办下去</h2><p>查档案、记联系、跟诉求，每次从当前进展继续。</p></div><div class="ew-actions">${writeButton('new-visit', '记录联系或走访')}${writeButton('new-issue', '登记诉求', '', true)}</div></div>
        <div class="ew-metrics">${metrics.map(([id, title, count, target]) => `<button data-metric="${id}" data-target="${esc(target)}"><span>${title}</span><strong>${count}</strong><span>查看记录 ${icon('arrow-right', 14)}</span></button>`).join('')}</div>
        <div class="ew-section-head"><h3>需要跟进的诉求</h3><button class="btn ghost" data-route="issues">查看全部诉求</button></div>
        <div class="ew-attention">${attention.map(issueCard).join('') || empty('暂无待跟进诉求。登记新的企业需求后，可以在这里持续办理。')}</div>
        <div class="ew-section-head"><h3>企业联系</h3><button class="btn ghost" data-route="companies">查看全部企业</button></div>
        ${companyRows(companies.slice(0, 5))}`;
    }
    function companyRows(rows) {
      return rows.length ? `<div class="ew-company-list">${rows.map(c => `<button type="button" data-company-row="${esc(c.id)}"><span><strong>${esc(c.name)}</strong><small>${text(c.industry)} · ${text(c.scale)}${c.example ? ' · 示例企业' : ''}</small></span><span class="ew-company-tail">${text(c.servicer)}<small>最近联系 ${text(c.lastVisit)}</small></span>${icon('arrow-right', 16)}</button>`).join('')}</div>` : empty('没有符合条件的企业。可以修改筛选条件或新增企业档案。');
    }
    function companyList() {
      const q = params.get('q') || '';
      const rows = companies.filter(c => !q || [c.name, c.short, c.industry, c.creditCode].some(v => String(v || '').includes(q)));
      return `<div class="ew-heading"><div><h2>企业档案</h2><p>查看同一企业的资料、联系记录和办理进展。</p></div>${writeButton('new-company', '新增企业', '', true)}</div>
        <form class="ew-filter" data-form="search">${field('查找企业', 'q', q)}<button class="btn" type="submit">查询</button><span class="t-3">共 ${rows.length} 家</span></form>${companyRows(rows)}`;
    }
    function companyDetail() {
      if (!detail) return empty('企业不存在或当前账号无权查看。');
      const e = detail.item, related = issues.filter(i => i.entId === e.id);
      const contacts = e.contacts?.length ? e.contacts : e.contact ? [{ name: e.contact, title: '联系人', phone: e.phone }] : [];
      const kv = (label, value) => `<div><dt>${label}</dt><dd>${text(value)}</dd></div>`;
      return `<div class="ew-heading"><div><button class="btn ghost" data-route="companies">${icon('arrow-left', 14)} 返回企业档案</button><h2>${esc(e.name)}</h2><p>${text(e.industry)} · ${text(e.scale)}${e.example ? ' · 示例企业' : ''}</p></div><div class="ew-actions">${writeButton('edit-company', '编辑企业资料')}${writeButton('new-visit', '记录联系或走访')}${writeButton('new-issue', '登记诉求', '', true)}</div></div>
        <dl class="ew-profile">${kv('统一社会信用代码', e.creditCode)}${kv('服务专员', e.servicer)}${kv('从业人数', e.employees)}${kv('经营地址', e.opAddr || e.addr)}${kv('最近联系', e.lastVisit)}${kv('主要业务', e.products)}</dl>
        <div class="ew-section-head"><h3>联系人</h3></div><div class="ew-contacts">${contacts.map(c => `<p>${text(c.name)} · ${text(c.title)} <span>${text(c.phone)}</span></p>`).join('') || empty('暂无可见联系人信息。')}</div>
        <div class="ew-section-head"><h3>企业诉求 <span class="t-3">${related.length}</span></h3><button class="btn ghost" data-target="${esc(route('issues', { company: e.id }))}">查看诉求看板</button></div><div class="ew-attention">${related.map(issueCard).join('') || empty('该企业暂无诉求。')}</div>
        <div class="ew-section-head"><h3>最近联系与走访</h3><button class="btn ghost" data-target="${esc(route('visits', { company: e.id }))}">查看全部联系记录</button></div>${visitRows((detail.visits || []).slice(0, 3))}`;
    }
    function visitRows(rows) {
      return rows.length ? `<div class="ew-visits">${rows.map(v => `<article><div class="ew-card-meta"><strong>${esc(v.type || '联系记录')}</strong><span>${text(v.date)} · ${text(v.staff)}</span></div><p>${esc(v.notes || '当前账号仅可查看记录摘要')}</p>${v.warning ? `<p class="ew-note">${esc(v.warning)}</p>` : ''}</article>`).join('')}</div>` : empty('暂无联系记录。可以直接记录电话、线上沟通或上门走访。');
    }
    function visits() {
      return `<div class="ew-heading"><div><h2>联系与走访</h2><p>先选择企业，再查看或记录一次联系。整理建议经人工确认后才更新档案。</p></div>${writeButton('new-visit', '记录联系或走访', '', true)}</div>
        <form class="ew-filter" data-form="choose-company">${companySelect(params.get('company') || '')}<button class="btn" type="submit">查看记录</button></form>
        ${detail ? `<div class="ew-section-head"><h3>${esc(detail.item.name)}</h3>${writeButton('new-issue', '登记诉求')}</div>${visitRows(detail.visits || [])}${proposalList(detail.proposals || [])}` : empty('选择一家企业，查看它的联系和走访记录。')}`;
    }
    function proposalList(rows) {
      if (!canWrite() || !rows.length) return '';
      const value = v => typeof v === 'object' ? JSON.stringify(v) : String(v ?? '未记录');
      return `<div class="ew-section-head"><h3>待核对的档案更新建议</h3></div><p class="t-3">请对照联系记录核实。未确认的建议不会写入企业档案。</p><div class="ew-proposals">${rows.map(p => `<article><h4>${esc(p.label || p.field)}</h4><p>${esc(value(p.old))} → ${esc(value(p.new))}</p><blockquote>${esc(p.source || '请回到联系记录核对原文')}</blockquote><div class="ew-actions">${writeButton('proposal-accept', '确认写入', `data-id="${esc(p.id)}"`)}${writeButton('proposal-reject', '忽略建议', `data-id="${esc(p.id)}"`)}</div></article>`).join('')}</div>`;
    }
    function board() {
      const status = params.get('status') || '', company = params.get('company') || '', onlyLate = params.get('overdue') === '1';
      const rows = issues.filter(i => (!status || i.status === status) && (!company || i.entId === company) && (!onlyLate || overdue(i)));
      return `<div class="ew-heading"><div><h2>诉求看板</h2><p>分派负责人，明确办理期限，留下每次跟进的依据。</p></div>${writeButton('new-issue', '登记诉求', '', true)}</div>
        <form class="ew-filter" data-form="filter-issues">${companySelect(company)}${select('筛选状态', 'status', ['', ...statuses], status)}<label class="ew-check"><input type="checkbox" name="overdue" ${onlyLate ? 'checked' : ''}>只看逾期</label><button class="btn" type="submit">筛选</button><span class="t-3">${rows.length} 项诉求</span></form>
        <div class="ew-board">${statuses.map(s => `<section data-column="${s}"><header>${pill(s)}<span>${rows.filter(i => i.status === s).length}</span></header>${rows.filter(i => i.status === s).map(issueCard).join('') || '<p class="ew-column-empty">暂无诉求</p>'}</section>`).join('')}</div>`;
    }
    function issueDetail() {
      const i = issues.find(i => i.id === params.get('id'));
      if (!i) return empty('诉求不存在或当前账号无权查看。');
      return `<button class="btn ghost" data-route="issues">${icon('arrow-left', 14)} 返回诉求看板</button><div class="ew-heading"><div><p>${esc(i.entName || name(i.entId))} · ${esc(i.from || '来源待补充')} · ${text(i.created)}</p><h2>${esc(i.title)}</h2></div><div class="ew-actions"><span data-issue-status>${esc(i.status)}</span>${overdue(i) ? '<span class="tag">已逾期</span>' : ''}<button class="btn" data-company-row="${esc(i.entId)}">查看企业档案</button></div></div>
        <div class="ew-detail-grid"><section><h3>办理进展</h3><ol class="ew-timeline">${(i.steps || []).map(([date, content]) => `<li><time>${text(date)}</time><p>${esc(content)}</p></li>`).join('') || '<li>暂无办理记录</li>'}</ol></section><section>
        ${canWrite() ? `<form class="ew-form" data-form="update-issue" data-id="${esc(i.id)}"><h3 class="ew-wide">更新办理进展</h3>${field('负责人', 'owner', i.owner)}${field('办理期限', 'due', i.due, 'date')}${select('办理状态', 'status', statuses, i.status)}${field('下一步安排', 'next', i.next)}${area('本次进展与依据', 'note')}<p class="ew-wide t-3">可记录沟通结果、收到的材料和下一步安排；保存后保留修改记录。</p><div class="ew-wide ew-form-error" role="alert"></div><button class="btn primary" data-write type="submit">保存办理进展</button></form>` : `<dl class="ew-profile">${[['负责人', i.owner], ['办理期限', i.due], ['下一步安排', i.next]].map(([a, b]) => `<div><dt>${a}</dt><dd>${text(b)}</dd></div>`).join('')}</dl>`}</section></div>`;
    }
    function editForm() {
      const cid = currentCompany() || '', e = form === 'edit-company' ? detail.item : {};
      let title, fields, submit;
      if (form === 'new-company' || form === 'edit-company') {
        title = form === 'new-company' ? '新增企业' : '编辑企业资料'; submit = '保存企业档案';
        fields = field('企业全称', 'name', e.name, 'text', true) + field('企业简称', 'short', e.short) + field('统一社会信用代码', 'creditCode', e.creditCode) + field('所属行业', 'industry', e.industry) + field('企业规模', 'scale', e.scale) + field('从业人数', 'employees', e.employees || 0, 'number') + field('经营地址', 'opAddr', e.opAddr) + (form === 'new-company' ? field('联系人', 'contact') + field('联系电话', 'phone') : '');
      } else if (form === 'new-visit') {
        title = '记录联系或走访'; submit = '保存联系记录';
        fields = companySelect(cid, true) + select('联系类型', 'type', ['上门走访', '电话联系', '线上沟通', '会议座谈'], '上门走访') + area('记录内容', 'notes', '', true);
      } else {
        title = '登记诉求'; submit = '保存诉求';
        fields = companySelect(cid, true) + select('诉求来源', 'from', ['走访', '电话', '会议', '座谈', '政策咨询'], '走访') + area('诉求内容', 'title', '', true) + field('负责人', 'owner') + field('办理期限', 'due', '', 'date') + field('下一步安排', 'next');
      }
      return `<div class="ew-heading"><h2>${title}</h2>${button('cancel-form', '取消')}</div><form class="ew-form" data-form="${form}">${fields}<div class="ew-wide ew-form-error" role="alert"></div><div class="ew-wide ew-actions"><button class="btn primary" data-write type="submit">${submit}</button>${button('cancel-form', '取消填写')}</div></form>`;
    }
    function render() {
      if (!live()) return;
      shell(form ? editForm() : ({ overview, companies: companyList, company: companyDetail, visits, issues: board, issue: issueDetail }[view])());
    }
    async function mutate(fn, success) {
      if (!canWrite() || busy) return;
      busy = true; el.querySelectorAll('[data-write]').forEach(b => { b.disabled = true; });
      const targetError = el.querySelector('.ew-form-error'); if (targetError) targetError.textContent = '';
      try { const result = await fn(); window.dispatchEvent(new CustomEvent('jk:enterprise:changed')); JK.bus.emit('inbox:changed'); if (live()) await success(result); }
      catch (e) { if (live()) { const target = el.querySelector('.ew-form-error'); if (target) target.textContent = e.message || '保存失败，请重试'; else { notice = e.message || '保存失败，请重试'; render(); } } }
      finally { busy = false; if (live()) el.querySelectorAll('[data-write]').forEach(b => { b.disabled = false; }); }
    }
    el.onclick = event => {
      const b = event.target.closest('button'); if (!b || !el.contains(b) || busy) return;
      if (b.dataset.route) return go(b.dataset.route);
      if (b.dataset.target) return ctx.open(b.dataset.target);
      if (b.dataset.companyRow) return go('company', { id: b.dataset.companyRow });
      if (b.dataset.issueCard) return go('issue', { id: b.dataset.issueCard });
      const action = b.dataset.action;
      if (action === 'retry') return load();
      if (action === 'cancel-form') { form = null; return render(); }
      if (!canWrite()) return;
      if (['new-company', 'edit-company', 'new-visit', 'new-issue'].includes(action)) { form = action; notice = ''; render(); el.querySelector('input,select,textarea')?.focus(); }
      if (action === 'proposal-accept' || action === 'proposal-reject') mutate(() => api.decide(b.dataset.id, { decision: action === 'proposal-accept' ? 'accept' : 'reject' }), () => load('建议已处理，企业档案已同步。'));
    };
    el.onsubmit = event => {
      const f = event.target; if (!f.matches('[data-form]')) return;
      event.preventDefault(); if (busy) return;
      const data = Object.fromEntries(new FormData(f));
      if (f.dataset.form === 'search') return go('companies', data.q ? { q: data.q.trim() } : {});
      if (f.dataset.form === 'choose-company') return go('visits', data.company ? { company: data.company } : {});
      if (f.dataset.form === 'filter-issues') return go('issues', Object.fromEntries(Object.entries({ company: data.company, status: data.status, overdue: data.overdue ? '1' : '' }).filter(([, v]) => v)));
      if (!canWrite()) return;
      if (f.dataset.form === 'new-company' || f.dataset.form === 'edit-company') {
        data.name = data.name.trim(); data.employees = Number(data.employees);
        if (!data.name) { f.querySelector('[role="alert"]').textContent = '请填写企业全称'; return; }
        return mutate(() => form === 'edit-company' ? api.patch(detail.item.id, data) : api.create(data), r => go('company', { id: r.item.id }));
      }
      if (f.dataset.form === 'new-visit') return mutate(() => api.visit(data.company, { notes: data.notes.trim(), type: data.type }), () => { form = null; go('visits', { company: data.company }); });
      if (f.dataset.form === 'new-issue') return mutate(() => api.createIssue({ entId: data.company, title: data.title.trim(), from: data.from, owner: data.owner.trim(), due: data.due, next: data.next.trim() }), r => go('issue', { id: r.item.id }));
      if (f.dataset.form === 'update-issue') return mutate(() => api.patchIssue(f.dataset.id, data), () => load('办理进展已保存。'));
    };
    load();
    return { unmount() { alive = false; sequence++; el.onclick = el.onsubmit = null; } };
  } });
})();

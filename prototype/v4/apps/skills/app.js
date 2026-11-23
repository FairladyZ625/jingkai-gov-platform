/* =====================================================================
 * 技能中心 skills —— 看技能 / 用技能 / 做技能 / 分享技能 / 审核上架
 * 界面只调 ctx.api.skills（api/skills.js）与 ctx.kb；不碰模拟数据。
 * 制作流程（小白 4 步）：① 说一句话 → ② AI 起草，卡片里直接改 → ③ 用示例试运行 → ④ 选分享范围发布（全区需管理员审核）
 * ===================================================================== */
(function () {
  const COPY = {
    examples: ['帮我做一个技能：走访后把记录整理成台账更新建议', '做个技能，核对数据券申报材料齐不齐', '每周五把本周会议汇总成处室周报'],
    scopes: [
      { id: 'private', label: '仅自己', icon: 'lock', desc: '只有我能看到' },
      { id: 'people', label: '指定同事', icon: 'user', desc: '选几位同事' },
      { id: 'dept', label: '本部门', icon: 'users', desc: '部门同事都能用' },
      { id: 'zone', label: '全区', icon: 'globe', desc: '管理员审核后上架' },
    ],
    perms: [['view', '可查看'], ['use', '可使用'], ['edit', '可编辑']],
    stepTypes: { kb: ['book', '查知识库'], tool: ['bolt', '调用应用'], model: ['sparkles', 'AI 生成'], computer: ['computer', '电脑操作'] },
    inputTypes: [['text', '一行文字'], ['textarea', '一段文字'], ['number', '数字'], ['enterprise', '选企业'], ['date', '日期']],
    formats: ['要点', '表格', '清单', '公文'],
    cats: ['政策', '企业', '会议', '公文', '知识', '数据', '电脑操作'],
  };
  const statusName = { draft: '草稿', published: '已发布', in_review: '待上架审核', rejected: '已退回' };
  const scopeName = { private: '仅自己', people: '指定同事', dept: '本部门', zone: '全区' };

  JK.registerApp({
    manifest: {
      id: 'skills', name: '技能中心', short: '技能', icon: 'skill', hue: 'pink', version: '2.0.0', owner: 'AI 工作组',
      summary: '把常办的事做成一键技能', routes: ['home', 'mine', 'review', 'detail', 'make'],
      perms: { view: '浏览、使用技能', operate: '制作、分享技能', approve: '审核全区上架', admin: '管理所有技能' },
      tools: [
        { name: 'skills.run', desc: '运行一个技能', params: { skillId: 'string', inputs: 'object' } },
        { name: 'skills.create', desc: '用一句话起草一个新技能', params: { text: 'string' } },
      ],
      intents: [
        { id: 'skills.create', requires: 'operate', examples: ['帮我做一个技能：走访后把记录整理成台账更新建议', '做个技能，核对数据券申报材料齐不齐', '我想做一个周报技能'], keywords: ['做技能', '做个技能', '做一个技能', '造技能', '制作技能', '新建技能', '创建技能'], action: 'create', plan: ['打开技能中心', 'AI 起草技能', '用示例试运行', '选择分享范围'] },
        { id: 'skills.run', requires: 'operate', examples: ['用实体书店政策预判看看书香里', '运行处室周报整理', '用技能核对数据券材料'], keywords: ['用技能', '运行技能', '技能'], slots: { ent: 'enterprise' }, action: 'run', plan: ['找到技能', '填好要用的信息', '运行技能', '整理结果'] },
        { id: 'skills.share', requires: 'operate', examples: ['把处室周报整理分享给企业服务处', '把我的技能分享给王敏'], keywords: ['分享技能', '共享技能', '分享给'], action: 'share', plan: ['找到技能', '选择分享范围', '确认分享'], confirm: true },
        { id: 'skills.browse', examples: ['打开技能中心', '有哪些技能可以用'], keywords: ['技能中心', '技能广场', '有哪些技能'], action: 'browse', plan: ['打开技能中心'] },
        { id: 'skills.review', requires: 'approve', examples: ['审核技能上架申请'], keywords: ['技能审核', '上架审核', '审核技能'], action: 'review', plan: ['打开审核列表', '查看申请'] },
      ],
      starters: ['帮我做一个技能：走访后把记录整理成台账更新建议', '用实体书店政策预判看看书香里'],
      demo: [
        { title: '一句话做技能', say: '帮我做一个技能：核对数据券申报材料齐不齐' },
        { title: '用同事的技能', say: '用实体书店政策预判看看书香里' },
      ],
    },

    mount(el, ctx) {
      const { esc, tag, icon, toast } = ctx.ui;
      const API = (ctx.api && ctx.api.skills) || (window.JKApi && window.JKApi.skills);
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const canMake = () => ctx.perms.can('operate', 'skills');
      const canReview = () => ctx.perms.can('approve', 'skills');
      const catHue = (c) => ctx.ui.hue(c, 'skillCat');
      const st = { view: 'home', q: '', cat: '全部', list: [], apps: [], mine: [], review: [], detail: null, dtab: 'use', make: null, opts: null, ents: null, out: null };
      const reviewing = new Set();
      let alive = true;

      /* ---------- 数据 ---------- */
      async function loadLists() {
        const [a, m, r] = await Promise.all([API.list(), API.list({ mine: 1 }), canReview() ? API.list({ review: 1 }) : Promise.resolve({ items: [] })]);
        st.list = a.items; st.apps = (a.apps || []).filter((x) => ['policy', 'enterprise', 'meeting', 'document'].includes(x.id)); st.mine = m.items; st.review = r.items;
      }
      async function opts() { if (!st.opts) st.opts = await API.options(); return st.opts; }
      async function ents() {
        if (!st.ents) { try { const r = await ctx.api.get('/api/apps/enterprise/companies'); st.ents = (r.items || []).map((e) => ({ id: e.id, name: e.name, short: e.short })); } catch (e) { st.ents = []; } }
        return st.ents;
      }

      /* ---------- 通用片段 ---------- */
      const skIco = (s, size) => `<span class="app-ico ${size || ''} h-${catHue(s.spec ? s.spec.cat : '知识')} sk-glyph">${esc((s.icon || s.name || '技')[0])}</span>`;
      const stars = (s) => (s.rating ? `<span class="row sk-meta-i">${icon('star')}${s.rating}</span>` : '');
      const head = (right) => `<div class="app-head sk-head">${ctx.ui.appIcon('skills', 'lg')}<div class="grow"><h2 class="h2">技能中心</h2><div class="t-3 t-sm">把常办的事做成一键技能，分享给同事</div></div>${right || ''}</div>`;
      const tabs = () => `<div class="tabs sk-tabs">${[['home', '发现'], ['mine', '我的', st.mine.length], ...(canReview() ? [['review', '审核', st.review.length]] : [])].map(([v, l, n]) => `<button class="tab ${st.view === v ? 'on' : ''}" data-tab="${v}" data-op="skills.tab.${v}">${l}${n ? `<span class="count ${v === 'review' ? '' : 'muted'}">${n}</span>` : ''}</button>`).join('')}</div>`;

      function render() {
        if (!alive) return;
        if (st.view === 'detail') return renderDetail();
        if (st.view === 'make') return renderMake();
        const right = canMake() ? `<button class="btn primary" data-act="new" data-op="skills.new">${icon('plus')}制作技能</button>` : '';
        el.innerHTML = `<div class="sk-wrap">${head(right)}${tabs()}<div class="sk-body">${st.view === 'mine' ? viewMine() : st.view === 'review' ? viewReview() : viewHome()}</div></div>`;
        bindCommon();
      }

      /* ---------- 发现 ---------- */
      function viewHome() {
        const cats = ['全部', ...COPY.cats.filter((c) => st.list.some((s) => s.spec && s.spec.cat === c))];
        const items = st.list.filter((s) => s.status === 'published' && (st.cat === '全部' || s.spec.cat === st.cat) && (!st.q || (s.name + s.summary + (s.spec.triggers || []).join('')).includes(st.q)));
        return `<div class="row gap3 sk-filter"><div class="search grow">${icon('search')}<input class="input" placeholder="搜技能，比如：周报、数据券" value="${esc(st.q)}" data-q data-op="skills.search"></div>
            <div class="seg">${cats.map((c) => `<button class="${st.cat === c ? 'on' : ''}" data-cat="${esc(c)}">${esc(c)}</button>`).join('')}</div></div>
          ${st.q || st.cat !== '全部' ? '' : `<div class="sk-sec"><div class="sk-sec-h">官方应用</div><div class="grid sk-apps">${st.apps.map((a) => `<div class="card tight hoverable sk-app" data-open-app="${a.id}">${ctx.ui.appIcon(a.id)}<div class="grow"><div class="sk-name">${esc(a.short || a.name)}</div><div class="t-3 t-xs">${(a.uses || 0).toLocaleString()} 次使用</div></div></div>`).join('')}</div></div>`}
          <div class="sk-sec"><div class="sk-sec-h">同事做的技能 <span class="t-3">${items.length}</span></div>
          ${items.length ? `<div class="grid g2">${items.map(card).join('')}</div>` : ctx.ui.empty({ icon: 'skill', title: '没有找到', desc: '换个词试试，或者自己做一个', action: canMake() ? '制作技能' : '' })}</div>`;
      }
      const card = (s) => `<div class="card hoverable sk-card" data-open="${s.id}" data-op="skills.card.${s.id}">
          <div class="row gap3">${skIco(s)}<div class="grow"><div class="sk-name clip">${esc(s.name)}</div><div class="t-3 t-xs">${esc(s.author)} · ${esc(s.dept || '')}</div></div>${tag(s.spec.cat, 'skillCat')}</div>
          <div class="t-2 t-sm clamp2 sk-sum">${esc(s.summary)}</div>
          <div class="row sk-foot"><span class="sk-meta-i">${(s.uses || 0)} 次使用</span>${stars(s)}<span class="sp"></span><button class="btn sm ghost" data-use="${s.id}" data-op="skills.use.${s.id}">${icon('play')}使用</button></div></div>`;

      /* ---------- 我的 ---------- */
      function viewMine() {
        if (!st.mine.length) return ctx.ui.empty({ icon: 'skill', title: '还没有自己的技能', desc: '用一句话说说想让它做什么，AI 帮你做好', action: canMake() ? '制作第一个技能' : '' });
        return `<div class="card flat"><div class="list lined">${st.mine.map((s) => `<div class="li" data-open="${s.id}">${skIco(s, 'sm')}<div class="grow"><div class="ttl clip">${esc(s.name)}</div><div class="meta">v${esc(s.version)} · ${scopeName[s.share.scope]} · ${s.uses || 0} 次使用</div></div>${tag(statusName[s.status])}
            <button class="btn sm ghost" data-edit="${s.id}" title="编辑">${icon('edit')}编辑</button><button class="btn sm ghost" data-share="${s.id}" title="分享">${icon('users')}分享</button><button class="btn sm ghost" data-del="${s.id}" title="删除">${icon('trash')}</button></div>`).join('')}</div></div>`;
      }

      /* ---------- 审核 ---------- */
      function viewReview() {
        if (!st.review.length) return ctx.ui.empty({ icon: 'check', title: '没有待审核的技能', desc: '同事申请“全区公开”时会出现在这里' });
        return `<div class="col rows">${st.review.map((s) => `<div class="card sk-rv"><div class="row gap3">${skIco(s)}<div class="grow"><div class="sk-name">${esc(s.name)}</div><div class="t-3 t-xs">${esc(s.author)} · ${esc(s.dept || '')} · v${esc(s.contentVersion ?? s.version)} · 申请全区公开</div></div>${tag('待上架审核')}</div>
            <div class="t-2 t-sm sk-sum">${esc(s.summary)}</div>
            <div class="row wrap sk-chips">${s.spec.steps.map((x) => `<span class="sk-step-pill">${icon(COPY.stepTypes[x.type][0])}${esc(x.label)}</span>`).join('')}<span class="sk-step-pill">${icon('cpu')}${esc(modelName(s.spec.model))}</span></div>
            <div class="card-f"><button class="btn sm ghost" data-open="${s.id}">查看并试运行</button><span class="sp"></span><button class="btn sm" data-reject="${s.id}" data-op="skills.reject.${s.id}">退回</button><button class="btn sm soft" data-approve="${s.id}" data-op="skills.approve.${s.id}">${icon('check')}通过上架</button></div></div>`).join('')}</div>`;
      }
      const modelName = (id) => { const m = st.opts && st.opts.models.find((x) => x.id === id); return m ? m.name : id === 'auto' ? '自动选择' : id; };

      /* ---------- 详情 ---------- */
      function renderDetail() {
        const s = st.detail; if (!s) return;
        const more = s.canEdit ? `<button class="btn icon ghost" data-more title="更多">${icon('more')}</button>` : '';
        el.innerHTML = `<div class="sk-wrap"><button class="btn ghost sm sk-back" data-back>${icon('chevron-right')}技能中心</button>
          <div class="sk-dh row gap4">${skIco(s, 'lg')}<div class="grow"><h2 class="h2">${esc(s.name)}</h2><div class="row wrap sk-dmeta">${tag(s.spec.cat, 'skillCat')}${s.status !== 'published' ? tag(statusName[s.status]) : ''}<span class="t-3 t-xs">${esc(s.author)} · v${esc(s.version)} · ${s.uses || 0} 次使用${s.rating ? ' · ★ ' + s.rating : ''}${s.source ? ' · 改编自 ' + esc(s.source) : ''}</span></div></div>
            <div class="row gap2 sk-dact">${canMake() ? `<button class="btn" data-fork data-op="skills.fork">${icon('copy')}复制改一改</button>` : ''}${s.canEdit ? `<button class="btn" data-share="${s.id}" data-op="skills.share">${icon('users')}分享</button>` : ''}${more}</div></div>
          ${s.reviewNote && s.status === 'rejected' ? `<div class="callout h-red sk-note">${icon('info')}<div>退回原因：${esc(s.reviewNote)}</div></div>` : ''}
          <div class="tabs sk-tabs">${[['use', '使用'], ['how', '怎么做的'], ['ver', '版本', s.versions.length]].map(([v, l, n]) => `<button class="tab ${st.dtab === v ? 'on' : ''}" data-dtab="${v}" data-op="skills.dtab.${v}">${l}${n ? `<span class="count muted">${n}</span>` : ''}</button>`).join('')}</div>
          <div class="sk-body">${st.dtab === 'how' ? viewHow(s) : st.dtab === 'ver' ? viewVersions(s) : viewUse(s)}</div></div>`;
        bindCommon(); bindDetail(s);
      }
      function inputsForm(spec, vals, prefix) {
        return `<div class="col gap4 sk-form">${spec.inputs.map((f) => `<div class="field"><label>${esc(f.label)}${f.required ? '' : ' <span class="t-3">选填</span>'}</label>${inputCtl(f, vals[f.key], prefix)}</div>`).join('')}</div>`;
      }
      function inputCtl(f, v, prefix) {
        const op = `data-in="${f.key}" data-op="${prefix}.in.${f.key}"`; v = v == null ? '' : v;
        if (f.type === 'enterprise') return `<select class="select" ${op}><option value="">选择企业…</option>${(st.ents || []).map((e) => `<option value="${e.id}" ${v === e.id ? 'selected' : ''}>${esc(e.short)}　${esc(e.name)}</option>`).join('')}</select>`;
        if (f.type === 'textarea') return `<textarea class="textarea" rows="3" ${op} placeholder="${esc(f.sample ? '例如：' + String(f.sample).split('\n')[0] : '')}">${esc(v)}</textarea>`;
        return `<input class="input" ${f.type === 'number' ? 'type="number"' : f.type === 'date' ? 'type="date"' : ''} ${op} value="${esc(v)}" placeholder="${esc(f.sample ? '例如：' + f.sample : '')}">`;
      }
      const readInputs = (root, spec) => { const o = {}; spec.inputs.forEach((f) => { const x = root.querySelector(`[data-in="${f.key}"]`); if (x) o[f.key] = x.value.trim(); }); return o; };
      const sampleInputs = (spec) => { const o = {}; spec.inputs.forEach((f) => (o[f.key] = f.sample || '')); return o; };

      function viewUse(s) {
        return `<div class="sk-use"><div class="card">${inputsForm(s.spec, st.useVals || {}, 'skills')}
          <div class="card-f"><button class="btn ghost sm" data-sample>${icon('sparkles')}填入示例</button><span class="sp"></span><span class="t-3 t-xs">${esc(modelName(s.spec.model))}</span><button class="btn primary" data-run data-op="skills.run">${icon('play')}运行</button></div></div>
          <div data-out>${st.out ? outHtml(st.out) : ''}</div></div>`;
      }
      function viewHow(s) {
        const sp = s.spec;
        return `<div class="col gap4 sk-how">
          <div class="card"><div class="sk-sec-h">在对话里这样说就会用它</div><div class="row wrap gap2">${sp.triggers.map((t) => `<span class="tag lg sq" data-hue="gray">“${esc(t)}”</span>`).join('')}</div></div>
          <div class="card"><div class="sk-sec-h">要填的信息</div><div class="list">${sp.inputs.map((f) => `<div class="li sk-li-ro"><span class="grow">${esc(f.label)}</span><span class="t-3 t-xs">${esc((COPY.inputTypes.find((x) => x[0] === f.type) || [, f.type])[1])}${f.required ? ' · 必填' : ''}</span></div>`).join('')}</div></div>
          <div class="card"><div class="sk-sec-h">怎么做</div>${flow(sp)}</div>
          <div class="grid g3 sk-kv3">${[['cpu', '模型', modelName(sp.model)], ['book', '知识库', sp.kb.join('、') || '—'], ['file', '输出', sp.output.format]].map(([ic, l, v]) => `<div class="card tight"><div class="t-3 t-xs row">${icon(ic)}${l}</div><div class="sk-kv">${esc(v)}</div></div>`).join('')}</div>
          ${s.canEdit ? `<div><button class="btn" data-edit="${s.id}">${icon('edit')}编辑</button></div>` : ''}</div>`;
      }
      const flow = (sp) => `<div class="sk-flow">${sp.steps.map((x, i) => `<div class="sk-flow-i"><span class="sk-flow-n">${i + 1}</span>${icon(COPY.stepTypes[x.type][0])}<span>${esc(x.label)}</span>${x.space ? `<span class="t-3 t-xs">${esc(x.space)}</span>` : ''}${x.tool ? `<span class="t-3 t-xs mono">${esc(x.tool)}</span>` : ''}</div>`).join('')}</div>`;
      function viewVersions(s) {
        const vs = s.versions.slice().reverse();
        return `<div class="card"><div class="tl">${vs.map((v, i) => `<div class="tl-i"><div class="row"><span class="t">v${esc(v.v)}</span>${i === 0 ? tag('当前', null, { hue: 'blue' }) : ''}<span class="t-3 t-xs">${esc(v.at)} · ${esc(v.by)}</span><span class="sp"></span>${i > 0 && v.spec && s.canEdit ? `<button class="btn sm ghost" data-restore="${esc(v.v)}">回到此版本</button>` : ''}</div><div class="t-2 t-sm">${esc(v.note)}</div></div>`).join('')}</div></div>`;
      }

      /* ---------- 运行结果 ---------- */
      function mdToHtml(src) {
        const lines = String(src || '').split('\n'); const out = []; let tbl = null; let list = null;
        const inl = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\[(\d+)\]/g, '<span class="cite" data-cite="$1">$1</span>');
        const flush = () => { if (tbl) { out.push(`<table class="tbl sk-tbl"><thead><tr>${tbl[0].map((c) => `<th>${inl(c)}</th>`).join('')}</tr></thead><tbody>${tbl.slice(1).map((r) => `<tr>${r.map((c) => `<td>${inl(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`); tbl = null; } if (list) { out.push(`<div class="sk-ul">${list.join('')}</div>`); list = null; } };
        lines.forEach((l) => {
          if (/^\|/.test(l)) { if (/^\|[-| ]+\|$/.test(l)) return; (tbl = tbl || []).push(l.replace(/^\||\|$/g, '').split('|').map((c) => c.trim())); return; }
          const ck = l.match(/^- \[( |x)\] (.*)$/); if (ck) { (list = list || []).push(`<div class="sk-ck ${ck[1] === 'x' ? 'ok' : 'no'}">${icon(ck[1] === 'x' ? 'check' : 'x')}<span>${inl(ck[2])}</span></div>`); return; }
          const b = l.match(/^(?:- |\d+\. )(.*)$/); if (b) { (list = list || []).push(`<div class="sk-bl">${inl(b[1])}</div>`); return; }
          flush();
          if (/^### /.test(l)) out.push(`<div class="sk-out-t">${inl(l.slice(4))}</div>`);
          else if (/^> /.test(l)) out.push(`<div class="t-3 t-xs">${inl(l.slice(2))}</div>`);
          else if (l.trim()) out.push(`<p>${inl(l)}</p>`);
        });
        flush(); return out.join('');
      }
      function outHtml(o) {
        if (o.status !== 'done') return `<div class="plan sk-plan"><div class="plan-h">${icon('sparkles')}正在运行</div>${o.steps.map((x) => `<div class="pstep ${x.status === 'done' ? 'done' : x.status === 'run' ? 'run' : ''}"><span class="pi"></span>${esc(x.label)}</div>`).join('')}</div>`;
        const r = o.result;
        return `<div class="card sk-result" data-op="skills.result"><div class="sk-md">${mdToHtml(r.markdown)}</div>
          ${r.citations.length ? `<div class="sk-srcs">${r.citations.slice(0, 3).map((c) => `<div class="src" data-cite-open="${c.n}"><span class="cite">${c.n}</span><span class="clip grow">${esc(c.title)}</span>${icon('chevron-right')}</div>`).join('')}</div>` : ''}
          <div class="card-f"><span class="t-3 t-xs">${esc(r.model)}${o.trial ? ' · 试运行' : ''}</span><span class="sp"></span>
          ${r.computer ? `<button class="btn sm soft" data-computer>${icon('computer')}继续电脑操作</button>` : ''}
          <button class="btn sm ghost" data-copy title="复制">${icon('copy')}</button><button class="btn sm ghost" data-dl title="下载">${icon('download')}</button>${o.trial ? '' : `<button class="btn sm ghost" data-tochat title="发到对话">${icon('chat')}</button><button class="btn sm ghost" data-rate="1" title="有用">有用</button>`}</div></div>`;
      }
      async function execute(root, skill, inputs, trial) {
        const box = root.querySelector('[data-out]');
        const missing = skill.spec.inputs.filter((f) => f.required && !inputs[f.key]);
        if (missing.length) { toast('先填：' + missing.map((f) => f.label).join('、'), { type: 'warn' }); return null; }
        let { job } = trial ? await API.trial({ name: skill.name, spec: skill.spec }, inputs) : await API.run(skill.id, inputs);
        st.out = job; box.innerHTML = outHtml(job);
        while (job.status === 'running') { await sleep(220); job = (await API.job(job.id)).job; st.out = job; if (box.isConnected) box.innerHTML = outHtml(job); }
        if (job.status === 'failed') { toast('运行失败：' + job.error, { type: 'err' }); return null; }
        bindOut(box, job);
        if (job.result.computer) ctx.nav.open('computer', 'run', { task: job.result.computer.task, ent: job.result.computer.ent, from: skill.name });
        return job;
      }
      function bindOut(box, job) {
        const r = job.result; if (!r) return;
        box.querySelectorAll('[data-cite],[data-cite-open]').forEach((c) => (c.onclick = () => { const n = +(c.dataset.cite || c.dataset.citeOpen); const x = r.citations.find((y) => y.n === n); if (x && ctx.kb && ctx.kb.open) ctx.kb.open(x.id, { highlight: x.snippet }); }));
        const q = (s) => box.querySelector(s);
        if (q('[data-copy]')) q('[data-copy]').onclick = () => { navigator.clipboard && navigator.clipboard.writeText(r.markdown).catch(() => {}); toast('已复制'); };
        if (q('[data-dl]')) q('[data-dl]').onclick = () => ctx.ui.download(r.title + '.md', r.markdown, 'text/markdown;charset=utf-8');
        if (q('[data-tochat]')) q('[data-tochat]').onclick = () => { ctx.chat && ctx.chat.say ? ctx.chat.say(r.markdown) : ctx.nav.chat(r.title); toast('已发到对话'); };
        if (q('[data-rate]')) q('[data-rate]').onclick = async (e) => { await API.rate(st.detail.id, true); e.target.textContent = '已评价'; e.target.disabled = true; toast('谢谢反馈'); };
        if (q('[data-computer]')) q('[data-computer]').onclick = () => ctx.nav.open('computer', 'run', { task: r.computer.task, ent: r.computer.ent });
      }

      /* ---------- 制作 / 编辑（4 步向导） ---------- */
      const WIZ = ['说需求', '改一改', '试一试', '发布'];
      const modelOption = (id) => st.opts.models.find((option) => option.id === id);
      const localModelOption = (id) => {
        const current = modelOption(id);
        return current?.local && !current.disabled ? current : st.opts.models.find((option) => option.local && !option.disabled);
      };
      const localQuestion = (question) => /本地/.test(question);
      let NAV = 0;
      function newMake(o) { st.make = Object.assign({ step: 0, text: '', skill: null, id: null, editing: false, share: { scope: 'dept', people: [], perm: 'use' }, result: null, trialVals: null, done: null, note: '' }, o || {}); st.view = 'make'; }
      function renderMake() {
        const m = st.make; const back = `<button class="btn ghost sm sk-back" data-back>${icon('chevron-right')}技能中心</button>`;
        el.innerHTML = `<div class="sk-wrap">${back}<div class="row sk-mk-h"><h2 class="h2">${m.editing ? '编辑技能' : '制作技能'}</h2><span class="sp"></span>${m.skill ? `<span class="t-3 t-xs">${m.id ? '已自动保存为草稿' : ''}</span>` : ''}</div>
          ${ctx.ui.steps(m.editing ? ['改一改', '试一试', '保存'] : WIZ, m.editing ? m.step - 1 : m.step)}<div class="wiz-body sk-wiz" data-wiz>${[mk0, mk1, mk2, mk3][m.step]()}</div></div>`;
        bindCommon(); bindMake();
      }
      function mk0() {
        const m = st.make;
        return `<div class="sk-ask"><div class="h3">想让它帮你做什么？</div><div class="t-3 t-sm">用平常说话的方式写一句就行，AI 会帮你整理成技能</div>
          <textarea class="textarea sk-big" rows="4" data-desc data-op="skills.desc" placeholder="例如：走访完企业，把我随手记的内容整理成台账更新建议">${esc(m.text)}</textarea>
          <div class="row wrap gap2">${COPY.examples.map((x) => `<button class="btn sm ghost sk-ex" data-ex="${esc(x)}">${icon('sparkles')}${esc(x.replace(/^帮我做一个技能：|^做个技能，/, ''))}</button>`).join('')}</div></div>
          <div class="wiz-foot"><span class="sp"></span><button class="btn primary" data-draft data-op="skills.draft">${icon('sparkles')}AI 起草</button></div>`;
      }
      function mk1() {
        const m = st.make; const k = m.skill; const sp = k.spec; const o = st.opts;
        const currentModel = modelOption(sp.model);
        const localModel = localModelOption(sp.model);
        const localReason = o.models.find((option) => option.disabled)?.disabledReason;
        const unavailable = !currentModel || currentModel.disabled;
        const modelHint = unavailable ? `${currentModel?.disabledReason || '当前模型不可用，请联系管理员检查模型配置'}。${m.id ? '保存其他修改时会保留原模型。' : '请在更多设置中选择可用模型。'}` : '';
        const optionList = currentModel ? o.models : [
          { id: sp.model, name: modelName(sp.model), disabled: true }, ...o.models,
        ];
        const stepRow = (x, i) => `<div class="sk-ed-step" data-si="${i}"><span class="sk-flow-n">${i + 1}</span>${icon(COPY.stepTypes[x.type][0])}<span class="sk-ed-st">${COPY.stepTypes[x.type][1]}</span>
            ${x.type === 'kb' ? `<select class="select sm-sel" data-sf="space">${o.spaces.map((s) => `<option ${x.space === s ? 'selected' : ''}>${s}</option>`).join('')}</select>` : ''}
            ${x.type === 'tool' ? `<select class="select sm-sel" data-sf="tool">${o.tools.map((t) => `<option value="${t.id}" ${x.tool === t.id ? 'selected' : ''}>${t.label}</option>`).join('')}</select>` : ''}
            ${x.type === 'computer' ? `<select class="select sm-sel" data-sf="task">${o.computerTasks.map((t) => `<option value="${t.id}" ${x.task === t.id ? 'selected' : ''}>${t.label}</option>`).join('')}</select>` : ''}
            ${x.type === 'model' ? `<input class="input sm" data-sf="label" value="${esc(x.label)}">` : ''}<span class="sp"></span><button class="btn icon sm ghost" data-sdel="${i}" title="删除">${icon('x')}</button></div>`;
        return `<div class="col gap4">
          ${m.questions && m.questions.length ? `<div class="callout h-pink sk-ai">${icon('sparkles')}<div class="grow"><div>AI 已起草好，直接改就行。也可以一键：</div><div class="row wrap gap2 sk-ai-q">${m.questions.map((q) => `<button class="chip-btn" data-q2="${esc(q)}" ${localQuestion(q) && !localModel ? 'disabled aria-describedby="sk-local-hint"' : ''}>${esc(q)}</button>`).join('')}</div>${!localModel && m.questions.some(localQuestion) ? `<div class="t-3 t-xs" id="sk-local-hint">${esc(localReason || '没有可用的本地模型，请联系管理员检查模型配置')}。</div>` : ''}</div></div>` : ''}
          <div class="card"><div class="grid sk-basic"><div class="field"><label>名称</label><input class="input" data-k="name" data-op="skills.ed.name" value="${esc(k.name)}"></div>
            <div class="field"><label>分类</label><select class="select" data-k="cat">${COPY.cats.map((c) => `<option ${sp.cat === c ? 'selected' : ''}>${c}</option>`).join('')}</select></div></div>
            <div class="field sk-gap"><label>一句话说明</label><input class="input" data-k="summary" value="${esc(k.summary)}"></div></div>
          <div class="card"><div class="sk-sec-h">在对话里这样说就会用它</div><div class="row wrap gap2" data-trigs>${sp.triggers.map((t, i) => `<span class="tag lg sq" data-hue="gray">“${esc(t)}”<button class="sk-x" data-tdel="${i}">${icon('x')}</button></span>`).join('')}<input class="input sm sk-tadd" data-tadd placeholder="+ 再加一种说法，回车"></div></div>
          <div class="card"><div class="sk-sec-h">要填的信息</div><div class="col gap2">${sp.inputs.map((f, i) => `<div class="row gap2 sk-ed-in" data-ii="${i}"><input class="input" data-if="label" value="${esc(f.label)}"><select class="select sk-w140" data-if="type">${COPY.inputTypes.map(([v, l]) => `<option value="${v}" ${f.type === v ? 'selected' : ''}>${l}</option>`).join('')}</select><label class="check"><input type="checkbox" data-if="required" ${f.required ? 'checked' : ''}>必填</label><button class="btn icon sm ghost" data-idel="${i}">${icon('x')}</button></div>`).join('')}
            <div><button class="btn sm ghost" data-iadd>${icon('plus')}添加一项</button></div></div></div>
          <div class="card"><div class="sk-sec-h">怎么做</div><div class="col gap2">${sp.steps.map(stepRow).join('')}<div><button class="btn sm ghost" data-sadd>${icon('plus')}添加步骤</button></div></div></div>
          <div class="card"><div class="row gap3"><span class="sk-sec-h sk-m0">结果做成</span><div class="seg">${COPY.formats.map((f) => `<button class="${sp.output.format === f ? 'on' : ''}" data-fmt="${f}">${f}</button>`).join('')}</div><span class="sp"></span><span class="t-3 t-xs">${esc(modelName(sp.model))} · ${esc(sp.kb.join('、') || '不查知识库')}</span></div>
            ${modelHint ? `<div class="t-3 t-xs sk-gap" id="sk-model-hint">${esc(modelHint)}</div>` : ''}
            <details class="sk-adv" ${m.adv ? 'open' : ''} data-adv><summary class="t-3 t-sm">更多设置：模型、知识库、提示词</summary>
            <div class="field sk-gap"><label for="sk-model">用哪个模型</label><select class="select" id="sk-model" data-k="model" ${modelHint || localReason ? 'aria-describedby="sk-model-hint"' : ''}>${optionList.map((x) => `<option value="${esc(x.id)}" ${sp.model === x.id ? 'selected' : ''} ${x.disabled ? 'disabled' : ''}>${esc(x.name)}${x.disabled ? '（需配置）' : x.local ? '（数据不出局）' : ''}</option>`).join('')}</select>${!modelHint && localReason ? `<div class="t-3 t-xs" id="sk-model-hint">${esc(localReason)}。</div>` : ''}</div>
            <div class="field sk-gap"><label>参考知识库</label><div class="row wrap gap2">${o.spaces.map((s) => `<label class="check sk-kbc"><input type="checkbox" data-kb="${s}" ${sp.kb.includes(s) ? 'checked' : ''}>${tag(s, 'kbSpace', { cls: 'plain' })}</label>`).join('')}</div></div>
            <div class="field sk-gap"><label>提示词模板</label><textarea class="textarea mono" rows="5" data-k="prompt">${esc(sp.prompt || '')}</textarea><div class="t-3 t-xs">用 {{${sp.inputs.map((f) => f.key).join('}}、{{')}}} 引用填写的信息</div></div></details></div>
          <div class="wiz-foot">${st.make.editing ? '' : '<button class="btn" data-prev>上一步</button>'}<span class="sp"></span><button class="btn primary" data-next data-op="skills.next">下一步：试一试</button></div></div>`;
      }
      function mk2() {
        const k = st.make.skill;
        return `<div class="col gap4"><div class="card"><div class="row sk-sec-h"><span>${icon('play')}用示例跑一遍</span><span class="sp"></span><button class="btn ghost sm" data-sample>${icon('sparkles')}换回示例</button></div>
          ${inputsForm(k.spec, st.make.trialVals || sampleInputs(k.spec), 'skills.try')}
          <div class="card-f"><span class="t-3 t-xs">${esc(modelName(k.spec.model))} · ${k.spec.steps.length} 步</span><span class="sp"></span><button class="btn soft" data-trial data-op="skills.trial">${icon('play')}试运行</button></div></div>
          <div data-out>${st.out && st.out.trial ? outHtml(st.out) : ''}</div>
          <div class="wiz-foot"><button class="btn" data-prev>上一步</button><span class="sp"></span><button class="btn primary" data-next data-op="skills.next">${st.make.editing ? '下一步：保存' : '下一步：发布'}</button></div></div>`;
      }
      function mk3() {
        const m = st.make;
        if (m.done) return doneView();
        if (m.editing) return `<div class="card"><div class="field"><label>这次改了什么（会记进版本记录）</label><input class="input" data-note data-op="skills.note" value="${esc(m.note)}" placeholder="例如：输出改成表格"></div></div>
          <div class="wiz-foot"><button class="btn" data-prev>上一步</button><span class="sp"></span><button class="btn primary" data-save data-op="skills.save">${icon('check')}保存为新版本</button></div>`;
        return `${shareForm(m.share)}<div class="wiz-foot"><button class="btn" data-prev>上一步</button><span class="sp"></span><button class="btn primary" data-publish data-op="skills.publish">${m.share.scope === 'zone' ? '提交上架审核' : '发布'}</button></div>`;
      }
      function shareForm(sh) {
        const o = st.opts;
        return `<div class="col gap4" data-sharebox><div class="grid g4 sk-scopes">${COPY.scopes.map((x) => `<div class="card tight hoverable sk-scope ${sh.scope === x.id ? 'sel' : ''}" data-scope="${x.id}" data-op="skills.scope.${x.id}">${icon(x.icon)}<div class="sk-name">${x.label}</div><div class="t-3 t-xs">${x.id === 'dept' ? esc(o.myDept || x.desc) : x.desc}</div></div>`).join('')}</div>
          ${sh.scope === 'people' ? `<div class="card tight"><div class="row wrap gap2 sk-people">${o.users.map((u) => `<button class="btn sm ${sh.people.includes(u.id) ? 'soft' : 'ghost'}" data-person="${u.id}">${esc(u.name)}<span class="t-3 t-xs">${esc(u.dept)}</span></button>`).join('')}</div></div>` : ''}
          ${sh.scope !== 'private' ? `<div class="row gap3"><span class="t-2 t-sm">对方可以</span><div class="seg">${COPY.perms.map(([v, l]) => `<button class="${sh.perm === v ? 'on' : ''}" data-perm="${v}">${l}</button>`).join('')}</div></div>` : ''}
          ${sh.scope === 'zone' ? `<div class="callout h-amber">${icon('shield')}<div>全区公开前由管理员审核，通过后出现在所有人的技能中心</div></div>` : ''}</div>`;
      }
      function doneView() {
        const d = st.make.done; const link = `jkq://skills/${d.id}`;
        return `<div class="card sk-done"><div class="sk-done-i">${icon('check', 28)}</div><div class="h3">${d.review ? '已提交上架审核' : '已发布'}</div><div class="t-2 t-sm">${d.review ? '管理员审核通过后全区可用；现在你和' + (st.opts.myDept || '本部门') + '已经可以用' : scopeName[d.share.scope] + '可用'}</div>
          <div class="row gap2 sk-link"><span class="t-2 t-sm grow">同事在对话里说「${esc(d.spec.triggers[0])}」就能用</span><button class="btn sm" data-copylink="${esc(d.spec.triggers[0])}">${icon('copy')}复制这句话</button></div>
          <div class="row gap2 sk-done-a"><button class="btn" data-open="${d.id}">查看技能</button><button class="btn primary" data-trychat="${esc(d.spec.triggers[0])}">${icon('chat')}在对话里试试</button></div></div>`;
      }

      /* ---------- 事件 ---------- */
      function bindCommon() {
        el.querySelectorAll('[data-tab]').forEach((b) => (b.onclick = () => { st.view = b.dataset.tab; render(); }));
        el.querySelectorAll('[data-act="new"],.empty [data-empty-act],.empty .btn').forEach((b) => (b.onclick = () => { newMake(); render(); }));
        el.querySelectorAll('[data-cat]').forEach((b) => (b.onclick = () => { st.cat = b.dataset.cat; render(); }));
        const q = el.querySelector('[data-q]'); if (q) q.oninput = () => { st.q = q.value.trim(); const pos = q.selectionStart; render(); const q2 = el.querySelector('[data-q]'); q2.focus(); q2.setSelectionRange(pos, pos); };
        el.querySelectorAll('[data-open-app]').forEach((b) => (b.onclick = () => ctx.nav.open(b.dataset.openApp)));
        el.querySelectorAll('[data-open]').forEach((b) => (b.onclick = (e) => { if (e.target.closest('button') && e.target.closest('button') !== b && !e.target.closest('button').dataset.open) return; openDetail(b.dataset.open, 'use'); }));
        el.querySelectorAll('[data-use]').forEach((b) => (b.onclick = (e) => { e.stopPropagation(); openDetail(b.dataset.use, 'use'); }));
        el.querySelectorAll('[data-edit]').forEach((b) => (b.onclick = (e) => { e.stopPropagation(); editSkill(b.dataset.edit); }));
        el.querySelectorAll('[data-share]').forEach((b) => (b.onclick = (e) => { e.stopPropagation(); shareDialog(b.dataset.share); }));
        el.querySelectorAll('[data-del]').forEach((b) => (b.onclick = (e) => { e.stopPropagation(); delSkill(b.dataset.del); }));
        el.querySelectorAll('[data-approve]').forEach((b) => (b.onclick = () => decide(b.dataset.approve, 'approve')));
        el.querySelectorAll('[data-reject]').forEach((b) => (b.onclick = () => decide(b.dataset.reject, 'reject')));
        const bk = el.querySelector('[data-back]'); if (bk) bk.onclick = async () => { st.view = st.make && st.make.editing ? 'mine' : 'home'; st.out = null; await loadLists(); render(); };
      }
      function bindDetail(s) {
        el.querySelectorAll('[data-dtab]').forEach((b) => (b.onclick = () => { st.dtab = b.dataset.dtab; render(); }));
        const smp = el.querySelector('[data-sample]'); if (smp) smp.onclick = () => { st.useVals = sampleInputs(s.spec); st.out = null; render(); };
        const runB = el.querySelector('[data-run]'); if (runB) runB.onclick = async () => { st.useVals = readInputs(el, s.spec); runB.disabled = true; try { await execute(el, s, st.useVals, false); } catch (e) { toast(e.message || '运行失败', { type: 'err' }); } runB.disabled = false; };
        if (st.out && st.out.status === 'done') bindOut(el.querySelector('[data-out]'), st.out);
        const fk = el.querySelector('[data-fork]'); if (fk) fk.onclick = () => forkSkill(s.id);
        el.querySelectorAll('[data-restore]').forEach((b) => (b.onclick = async () => { if (!(await ctx.ui.confirm(`回到 v${b.dataset.restore} 的内容？会生成一个新版本，原版本保留。`))) return; const r = await API.restore(s.id, b.dataset.restore); st.detail = r.item; toast('已回到 v' + b.dataset.restore + '，当前 v' + r.item.version); render(); }));
        const mo = el.querySelector('[data-more]'); if (mo) mo.onclick = () => ctx.ui.menu ? ctx.ui.menu(mo, [{ v: 'edit', label: '编辑', icon: 'edit' }, { v: 'promote', label: '升级为小应用', icon: 'cube' }, { v: 'del', label: '删除', icon: 'trash' }], (v) => moreAct(v, s)) : (JK.menu && JK.menu(mo, [{ v: 'edit', label: '编辑', icon: 'edit' }, { v: 'promote', label: '升级为小应用', icon: 'cube' }, { v: 'del', label: '删除', icon: 'trash' }], (v) => moreAct(v, s)));
      }
      function moreAct(v, s) { if (v === 'edit') editSkill(s.id); else if (v === 'promote') promoteDialog(s); else if (v === 'del') delSkill(s.id); }
      function syncEditor() {
        const k = st.make.skill; const sp = k.spec; const w = el.querySelector('[data-wiz]'); if (!w || st.make.step !== 1) return;
        const gv = (s) => { const x = w.querySelector(s); return x ? x.value : null; };
        if (gv('[data-k="name"]') != null) { k.name = gv('[data-k="name"]').trim() || k.name; k.icon = k.name[0]; }
        if (gv('[data-k="summary"]') != null) k.summary = gv('[data-k="summary"]');
        if (gv('[data-k="cat"]')) sp.cat = gv('[data-k="cat"]');
        if (gv('[data-k="prompt"]') != null) sp.prompt = gv('[data-k="prompt"]');
        w.querySelectorAll('[data-ii]').forEach((r) => { const f = sp.inputs[+r.dataset.ii]; f.label = r.querySelector('[data-if="label"]').value.trim() || f.label; f.type = r.querySelector('[data-if="type"]').value; f.required = r.querySelector('[data-if="required"]').checked; });
        w.querySelectorAll('[data-si]').forEach((r) => { const x = sp.steps[+r.dataset.si]; r.querySelectorAll('[data-sf]').forEach((c) => { x[c.dataset.sf] = c.value; if (c.dataset.sf === 'space') { x.label = '查' + c.value; } if (c.dataset.sf === 'tool') { const t = st.opts.tools.find((y) => y.id === c.value); x.label = t.label; x.args = t.needs ? { [c.value === 'enterprise.get' ? 'id' : 'entId']: '{{ent}}' } : {}; } if (c.dataset.sf === 'task') x.label = st.opts.computerTasks.find((y) => y.id === c.value).label; }); });
        sp.kb = [...w.querySelectorAll('[data-kb]:checked')].map((c) => c.dataset.kb);
      }
      async function persist() {
        const m = st.make; const k = m.skill;
        if (!m.id) { const r = await API.create({ name: k.name, summary: k.summary, icon: k.icon, base: k.base, spec: k.spec, forkOf: m.forkOf }); m.id = r.item.id; }
        else if (!m.editing) await API.save(m.id, { name: k.name, summary: k.summary, icon: k.icon, spec: k.spec });
      }
      function bindMake() {
        const m = st.make; const w = el.querySelector('[data-wiz]'); const q = (s) => w.querySelector(s); const qa = (s) => w.querySelectorAll(s);
        const rerender = () => { syncEditor(); render(); };
        const adv = q('[data-adv]'); if (adv) adv.ontoggle = () => (m.adv = adv.open);
        if (m.step === 0) {
          const d = q('[data-desc]'); d.oninput = () => (m.text = d.value);
          qa('[data-ex]').forEach((b) => (b.onclick = () => { m.text = b.dataset.ex; d.value = m.text; d.focus(); }));
          q('[data-draft]').onclick = async (e) => { m.text = d.value.trim(); if (!m.text) { toast('先用一句话说说想让它做什么', { type: 'warn' }); return; } e.target.disabled = true; e.target.innerHTML = `${icon('sparkles')}AI 正在起草…`; try { await opts(); await ents(); const r = await API.draft(m.text); m.skill = { name: r.draft.name, icon: r.draft.icon, summary: r.draft.summary, base: r.draft.base, spec: r.draft.spec }; m.questions = r.draft.questions; m.step = 1; render(); } catch (err) { toast(err.message, { type: 'err' }); e.target.disabled = false; } };
          return;
        }
        if (m.step === 1) {
          const sp = m.skill.spec;
          const model = q('[data-k="model"]');
          model.onchange = () => {
            const option = modelOption(model.value);
            if (option && !option.disabled) sp.model = option.id;
            rerender();
            el.querySelector('[data-k="model"]').focus({ preventScroll: true });
          };
          qa('[data-q2]').forEach((b) => (b.onclick = () => {
            const t = b.dataset.q2;
            const local = localQuestion(t);
            const option = local ? localModelOption(sp.model) : null;
            if (local && !option) return;
            syncEditor();
            if (/表格/.test(t)) sp.output.format = '表格';
            if (/企业/.test(t) && !sp.inputs.find((f) => f.type === 'enterprise')) sp.inputs.unshift({ key: 'ent', label: '哪家企业', type: 'enterprise', required: true, sample: 'E002' });
            if (option) sp.model = option.id;
            m.questions = m.questions.filter((x) => x !== t);
            toast('已按“' + t + '”修改'); render();
          }));
          qa('[data-fmt]').forEach((b) => (b.onclick = () => { syncEditor(); sp.output.format = b.dataset.fmt; render(); }));
          qa('[data-tdel]').forEach((b) => (b.onclick = () => { syncEditor(); sp.triggers.splice(+b.dataset.tdel, 1); render(); }));
          const ta = q('[data-tadd]'); ta.onkeydown = (e) => { if (e.key === 'Enter' && ta.value.trim()) { syncEditor(); sp.triggers.push(ta.value.trim()); render(); el.querySelector('[data-tadd]').focus(); } };
          qa('[data-idel]').forEach((b) => (b.onclick = () => { syncEditor(); if (sp.inputs.length <= 1) return toast('至少保留一项', { type: 'warn' }); sp.inputs.splice(+b.dataset.idel, 1); render(); }));
          q('[data-iadd]').onclick = () => { syncEditor(); let n = sp.inputs.length + 1; while (sp.inputs.find((f) => f.key === 'f' + n)) n++; sp.inputs.push({ key: 'f' + n, label: '新的一项', type: 'text', required: false, sample: '' }); render(); };
          qa('[data-sdel]').forEach((b) => (b.onclick = () => { syncEditor(); if (sp.steps.length <= 1) return toast('至少保留一步', { type: 'warn' }); sp.steps.splice(+b.dataset.sdel, 1); render(); }));
          q('[data-sadd]').onclick = (e) => { const items = Object.entries(COPY.stepTypes).map(([v, [ic, l]]) => ({ v, label: l, icon: ic })); (JK.menu)(e.currentTarget, items, (v) => { syncEditor(); const o = st.opts; const x = v === 'kb' ? { type: 'kb', space: o.spaces[0], query: '{{' + sp.inputs[0].key + '}}', label: '查' + o.spaces[0] } : v === 'tool' ? { type: 'tool', tool: o.tools[0].id, args: { entId: '{{ent}}' }, label: o.tools[0].label } : v === 'computer' ? { type: 'computer', task: 'stats', label: '统计月报填报' } : { type: 'model', label: 'AI 生成' }; const mi = sp.steps.findIndex((y) => y.type === 'model'); if (v !== 'model' && mi >= 0) sp.steps.splice(mi, 0, x); else sp.steps.push(x); render(); }); };
          const pv = q('[data-prev]'); if (pv) pv.onclick = () => { syncEditor(); m.step = 0; render(); };
          q('[data-next]').onclick = async () => {
            syncEditor();
            if (!m.skill.name.trim()) return toast('起个名字吧', { type: 'warn' });
            const option = modelOption(sp.model);
            if (!m.id && (!option || option.disabled)) {
              adv.open = true;
              model.focus();
              return;
            }
            try { await persist(); } catch (e) { return toast(e.message, { type: 'err' }); }
            st.out = null; m.step = 2; render();
          };
          return;
        }
        if (m.step === 2) {
          const k = m.skill;
          q('[data-sample]').onclick = () => { m.trialVals = sampleInputs(k.spec); render(); };
          q('[data-trial]').onclick = async (e) => { m.trialVals = readInputs(w, k.spec); e.currentTarget.disabled = true; try { const j = await execute(w, k, m.trialVals, true); if (j) m.tried = true; } catch (err) { toast(err.message, { type: 'err' }); } const b = w.querySelector('[data-trial]'); if (b) b.disabled = false; };
          if (st.out && st.out.status === 'done' && st.out.trial) bindOut(w.querySelector('[data-out]'), st.out);
          q('[data-prev]').onclick = () => { m.trialVals = readInputs(w, k.spec); m.step = 1; render(); };
          q('[data-next]').onclick = () => { m.trialVals = readInputs(w, k.spec); if (!m.tried && !m.editing) toast('建议先试运行一次，确认结果对不对', { type: 'warn' }); m.step = 3; render(); };
          return;
        }
        if (m.step === 3) {
          if (m.done) {
            const cl = q('[data-copylink]'); cl.onclick = () => { navigator.clipboard && navigator.clipboard.writeText(cl.dataset.copylink).catch(() => {}); toast('已复制，发给同事就能用'); };
            q('[data-trychat]').onclick = () => ctx.nav.chat(q('[data-trychat]').dataset.trychat);
            q('[data-open]').onclick = () => openDetail(m.done.id, 'use');
            return;
          }
          const pv = q('[data-prev]'); if (pv) pv.onclick = () => { m.step = 2; render(); };
          if (m.editing) {
            q('[data-note]').oninput = (e) => (m.note = e.target.value);
            q('[data-save]').onclick = async () => { try { const r = await API.save(m.id, { name: m.skill.name, summary: m.skill.summary, icon: m.skill.icon, spec: m.skill.spec, note: m.note || '修改内容' }); toast(`已保存为 v${r.item.version}`); openDetail(m.id, 'ver'); } catch (e) { toast(e.message, { type: 'err' }); } };
            return;
          }
          bindShare(w, m.share, () => render());
          q('[data-publish]').onclick = async () => { if (m.share.scope === 'people' && !m.share.people.length) return toast('选几位同事', { type: 'warn' }); try { await persist(); const r = await API.publish(m.id, m.share); m.done = r.item; m.done.review = r.review; if (r.review) ctx.bus && ctx.bus.emit('inbox:changed'); toast(r.review ? '已提交审核' : '已发布'); render(); } catch (e) { toast(e.message, { type: 'err' }); } };
        }
      }
      function bindShare(root, sh, rerender) {
        root.querySelectorAll('[data-scope]').forEach((b) => (b.onclick = () => { sh.scope = b.dataset.scope; rerender(); }));
        root.querySelectorAll('[data-person]').forEach((b) => (b.onclick = () => { const id = b.dataset.person; sh.people = sh.people.includes(id) ? sh.people.filter((x) => x !== id) : sh.people.concat(id); rerender(); }));
        root.querySelectorAll('[data-perm]').forEach((b) => (b.onclick = () => { sh.perm = b.dataset.perm; rerender(); }));
      }

      /* ---------- 动作 ---------- */
      async function openDetail(id, tab) {
        try { await opts(); await ents(); const r = await API.get(id); st.detail = r.item; st.dtab = tab || 'use'; st.view = 'detail'; st.out = null; st.useVals = null; render(); }
        catch (e) { toast(e.message, { type: 'err' }); }
      }
      async function editSkill(id) { await opts(); await ents(); const r = await API.get(id); newMake({ step: 1, id, editing: r.item.status === 'published' || r.item.status === 'in_review', skill: JSON.parse(JSON.stringify({ name: r.item.name, icon: r.item.icon, summary: r.item.summary, base: r.item.base, spec: r.item.spec })), share: Object.assign({}, r.item.share) }); render(); }
      async function forkSkill(id) { await opts(); await ents(); const r = await API.fork(id); toast('已复制一份到“我的”，改好就能用'); newMake({ step: 1, id: r.item.id, skill: { name: r.item.name, icon: r.item.icon, summary: r.item.summary, base: r.item.base, spec: r.item.spec }, questions: [] }); render(); return r.item; }
      async function delSkill(id) {
        const s = st.mine.find((x) => x.id === id) || st.detail; if (!(await ctx.ui.confirm(`删除“${s.name}”？`, { danger: true, okText: '删除' }))) return;
        const r = await API.remove(id); await loadLists(); st.view = 'mine'; render();
        toast('已删除', { action: { label: '撤销', fn: async () => { await API.undoRemove(r.item); await loadLists(); render(); } } });
      }
      async function decide(id, decision) {
        const pending = st.review.find(s => s.id === id);
        if (!pending || !canReview() || reviewing.has(id)) return;
        const target = {};
        if (window.JKHttp.mode('skills') === 'http') {
          const { reviewId, version } = pending;
          if (typeof reviewId !== 'string' || !reviewId.trim() || !Number.isInteger(version) || version < 1) {
            toast('待审版本不可用，请刷新审核列表后重试', { type: 'err' });
            return;
          }
          Object.assign(target, { reviewId, version });
        }
        async function send(reason) {
          if (!alive || !canReview() || reviewing.has(id)) return false;
          reviewing.add(id);
          try {
            try {
              await API.review(id, { decision, reason, ...target });
            } catch (e) {
              toast(e.message || '审核请求失败，请刷新后重试', { type: 'err' });
              return false;
            }
            if (!alive) return true;
            ctx.bus?.emit('inbox:changed');
            toast(decision === 'approve' ? '已通过，全区可用' : '已退回');
            try { await loadLists(); render(); }
            catch { toast('审核结果已保存，但列表未刷新，请重试', { type: 'warn' }); }
            return true;
          } finally {
            reviewing.delete(id);
          }
        }
        if (decision === 'approve') return send('');
        return ctx.ui.modal({
          title: '退回原因', okText: '退回',
          body: '<textarea class="textarea" rows="3" data-rs aria-label="退回原因" placeholder="例如：输出里缺少政策依据"></textarea>',
          onMount: d => d.querySelector('[data-rs]').focus(),
          ok: async d => {
            const input = d.querySelector('[data-rs]'), reason = input.value.trim();
            if (!reason) { toast('请填写退回原因', { type: 'warn' }); input.focus(); return false; }
            const button = d.querySelector('[data-ok]');
            button.disabled = true;
            if (await send(reason)) return true;
            button.disabled = false;
            return false;
          },
        });
      }
      async function shareDialog(id) {
        await opts(); const r = await API.get(id); const s = r.item; const sh = Object.assign({ people: [] }, s.share); const link = `jkq://skills/${s.id}`;
        const body = () => `${shareForm(sh)}<div class="row gap2 sk-link"><input class="input mono" readonly value="${link}"><button class="btn" data-cl>${icon('link')}复制链接</button></div>`;
        ctx.ui.modal({ title: '分享“' + s.name + '”', width: 640, body: body(), okText: '保存', onMount: (d) => { const b = () => { d.querySelector('[data-cl]').onclick = () => { navigator.clipboard && navigator.clipboard.writeText(link).catch(() => {}); toast('链接已复制'); }; bindShare(d, sh, () => { d.querySelector('.ov-b').innerHTML = body(); b(); }); }; b(); },
          ok: async () => { try { const x = await API.share(s.id, sh); toast(x.review ? '已提交全区上架审核' : '分享已更新：' + scopeName[sh.scope]); if (x.review) ctx.bus && ctx.bus.emit('inbox:changed'); await loadLists(); if (st.view === 'detail') st.detail = x.item; render(); } catch (e) { toast(e.message, { type: 'err' }); return false; } } });
      }
      async function promoteDialog(s) {
        const r = await API.manifest(s.id); const json = JSON.stringify(r.appJson, null, 2);
        ctx.ui.modal({ title: '升级为小应用', width: 640, okText: '提交开发组', body: `<div class="t-2 t-sm sk-gap0">技能用得多、需要固定界面时，可升级成平台小应用（apps/&lt;id&gt; 规范），由开发组评审后上架。</div>
            <div class="seg sk-gap"><button class="on" data-pv="json">app.json</button><button data-pv="md">SKILL.md</button></div><pre class="sk-code scroll" data-code>${esc(json)}</pre><div class="row"><button class="btn sm ghost" data-dlm>${icon('download')}下载</button></div>`,
          onMount: (d) => { let cur = 'json'; d.querySelectorAll('[data-pv]').forEach((b) => (b.onclick = () => { cur = b.dataset.pv; d.querySelectorAll('[data-pv]').forEach((x) => x.classList.toggle('on', x === b)); d.querySelector('[data-code]').textContent = cur === 'json' ? json : r.skillMd; })); d.querySelector('[data-dlm]').onclick = () => ctx.ui.download(cur === 'json' ? 'app.json' : 'SKILL.md', cur === 'json' ? json : r.skillMd); },
          ok: async () => { await API.promote(s.id, r.appJson.id); toast('已提交开发组评审（走 MR 门禁）'); ctx.bus && ctx.bus.emit('inbox:changed'); } });
      }

      /* ---------- 操作员动作（AI 替你操作） ---------- */
      const findSkill = async (text, id) => { if (id) return (await API.get(id)).item; const m = await API.match(text || ''); if (m.skill) return m.skill; const all = (await API.list()).items; return all.find((s) => (text || '').includes(s.name)) || null; };
      const entId = (slot) => { if (!slot) return ''; if (typeof slot === 'object') return slot.id; const e = (st.ents || []).find((x) => slot.includes(x.short) || x.name.includes(slot) || slot.includes(x.name)); return e ? e.id : ''; };
      const actions = {
        async browse(slots, run) { st.view = 'home'; await loadLists(); render(); run && run.done && run.done(`技能中心有 ${st.list.length} 个技能可用`, [{ label: '做一个技能', say: '帮我做一个技能' }]); },
        async review(slots, run) { st.view = 'review'; await loadLists(); render(); if (run) { await run.step(1); if (st.review[0]) await run.highlight(`[data-op="skills.approve.${st.review[0].id}"]`, '点这里通过'); run.done(st.review.length ? `有 ${st.review.length} 个技能等你审核` : '没有待审核的技能'); } },
        async create(slots, run) {
          const text = String((slots && (slots.text || slots.desc)) || '').replace(/^(帮我|请)?(做|造|制作|创建|新建)(一个|个)?技能[：:，,]?/, '').trim() || '核对数据券申报材料齐不齐';
          if (!canMake()) { run.fail('当前账号没有制作技能的权限'); return; }
          newMake(); render(); await run.step(1);
          await run.fill('[data-op="skills.desc"]', text); st.make.text = text;
          await run.click('[data-op="skills.draft"]');
          await run.wait(() => el.querySelector('[data-op="skills.ed.name"]'), 8000);
          await run.highlight('[data-op="skills.ed.name"]', 'AI 起草好了，可以直接改');
          await run.sleep(600); await run.step(2);
          await run.click('[data-op="skills.next"]');
          await run.wait(() => el.querySelector('[data-op="skills.trial"]'));
          st.out = null; await run.click('[data-op="skills.trial"]');
          await run.wait(() => el.querySelector('[data-op="skills.result"]') || (st.out && st.out.status === 'failed'), 12000);
          // 无模型的演示配置下试运行会因密级路由失败：不放宽路由，演示到保存草稿为止，跳过分享与发布。
          if (!el.querySelector('[data-op="skills.result"]')) { run.done(`技能「${st.make.skill.name}」已起草。演示配置没有可处理该密级的模型，试运行、分享与发布这一步演示时跳过`); return; }
          await run.scroll('[data-op="skills.result"]'); await run.sleep(500);
          await run.step(3);
          const c = await run.ask('试运行结果出来了。要把这个技能发布给谁用？', ['发布到本部门', '先只给自己用', '申请全区公开（需审核）']);
          if (run.stopped) return;
          await run.click('[data-op="skills.next"]'); await run.wait(() => el.querySelector('[data-op="skills.publish"]'));
          const scope = /全区/.test(c) ? 'zone' : /自己/.test(c) ? 'private' : 'dept';
          await run.click(`[data-op="skills.scope.${scope}"]`);
          await run.click('[data-op="skills.publish"]');
          await run.wait(() => el.querySelector('.sk-done'), 6000);
          const d = st.make.done;
          run.done(`技能「${d.name}」${d.review ? '已提交全区上架审核' : '已发布（' + scopeName[d.share.scope] + '）'}，以后说“${d.spec.triggers[0]}”就能直接用`, [{ label: '现在用一次', say: d.spec.triggers[0] }, { label: '分享给同事', say: `把${d.name}分享给企业服务处` }]);
        },
        async run(slots, run) {
          slots = slots || {}; await ents(); await opts();
          const s = await findSkill(slots.text, slots.skillId);
          if (!s) { run.fail('没找到对应的技能，可以说“帮我做一个技能…”'); return; }
          await openDetail(s.id, 'use'); await run.step(1);
          const vals = sampleInputs(s.spec); const eid = entId(slots.ent) || entId(slots.text || '');
          for (const f of s.spec.inputs) {
            const v = f.type === 'enterprise' ? (eid || vals[f.key]) : (slots.inputs && slots.inputs[f.key]) || vals[f.key];
            if (!v) continue;
            if (f.type === 'enterprise') await run.select(`[data-op="skills.in.${f.key}"]`, v); else await run.fill(`[data-op="skills.in.${f.key}"]`, v);
          }
          await run.step(2); await run.click('[data-op="skills.run"]');
          await run.wait(() => el.querySelector('[data-op="skills.result"]'), 15000);
          await run.step(3); await run.scroll('[data-op="skills.result"]');
          const r = st.out.result; const firstLine = (r.markdown.split('\n').find((l) => l && !l.startsWith('#')) || '').replace(/\*\*/g, '');
          run.done(`「${s.name}」已运行：${firstLine}`, r.computer ? [] : [{ label: '复制改一改', say: `把${s.name}复制一份改成我的` }]);
        },
        async share(slots, run) {
          const text = (slots && slots.text) || ''; await opts();
          const s = await findSkill(text); if (!s) { run.fail('没找到要分享的技能'); return; }
          if (!s.canEdit) { run.fail(`「${s.name}」不是你做的，可以先“复制改一改”再分享`); return; }
          await openDetail(s.id, 'how'); await run.step(1);
          const dept = (text.match(/给(.+?)(?:用|$|，|。)/) || [])[1] || '';
          const person = st.opts.users.find((u) => dept && dept.includes(u.name));
          const sh = person ? { scope: 'people', people: [person.id], perm: 'use' } : /全区|所有人|大家/.test(text) ? { scope: 'zone', people: [], perm: 'use' } : { scope: 'dept', people: [], perm: 'use' };
          await run.highlight('[data-op="skills.share"]', '分享'); await run.step(2);
          const c = await run.ask(`把「${s.name}」分享给${person ? person.name : scopeName[sh.scope]}，对方可以使用。确认吗？`, ['确认分享', '先不分享']);
          if (!/确认/.test(c)) { run.done('已取消分享'); return; }
          const x = await API.share(s.id, sh); st.detail = x.item; render(); if (x.review) ctx.bus && ctx.bus.emit('inbox:changed');
          run.done(x.review ? `已提交「${s.name}」全区上架审核，管理员通过后所有人可用` : `已把「${s.name}」分享给${person ? person.name : scopeName[sh.scope]}`, []);
        },
        async fork(slots, run) { const s = await findSkill(slots && slots.text); if (!s) return run.fail('没找到技能'); const f = await forkSkill(s.id); run.done(`已复制为「${f.name}」，在“改一改”里调整后发布`); },
      };

      /* ---------- 启动 ---------- */
      (async () => { const nav = NAV; await loadLists(); if (nav !== NAV) return; opts(); ents(); const p = ctx.params || {}; if (p.skillId) openDetail(p.skillId, p.tab); else if (p.route === 'make' || p.text) { newMake({ text: p.text || '' }); render(); } else render(); })();
      // 对话操作一开始就作废尚未返回的异步 go()，避免外壳打开应用时把操作界面盖回首页
      Object.keys(actions).forEach((k) => { const f = actions[k]; actions[k] = function () { NAV++; return f.apply(this, arguments); }; });
      const onReset = () => { st.opts = null; st.ents = null; st.view = 'home'; loadLists().then(render); };
      if (ctx.bus) ctx.bus.on('data:reset', onReset);
      return {
        async go(route, params) { params = params || {}; const nav = ++NAV; await loadLists(); if (nav !== NAV) return; if (route === 'detail' && params.skillId) return openDetail(params.skillId, params.tab); if (route === 'make') { await opts(); await ents(); newMake({ text: params.text || '' }); return render(); } st.view = ['home', 'mine', 'review'].includes(route) ? route : 'home'; render(); },
        actions,
        unmount() { alive = false; },
      };
    },
  });

  /* 对话服务：外壳用 match 判断一句话是否该交给某个自制技能（CONTRACT_REQUESTS #2） */
  const api = () => window.JKApi && window.JKApi.skills;
  JK.provide && JK.provide('skills', {
    async match(text) { const r = await api().match(text); return r.skill ? { skill: r.skill, score: r.score } : null; },
    async list() { return (await api().list()).items; },
    async run(skillId, inputs) { let { job } = await api().run(skillId, inputs || {}); while (job.status === 'running') { await new Promise((r) => setTimeout(r, 200)); job = (await api().job(job.id)).job; } return job.result; },
  });
})();

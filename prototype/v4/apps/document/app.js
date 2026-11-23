/* 公文协作（app id: document）· v4 综合版
 * 合并：v2 四步向导（要办什么事→填要素→初稿与核查→批注与送审）+ 10 类事项卡片；v3 红头稿纸就地改 + 版本对比（+x/−y）/恢复 + 导出 Word（未定稿水印）；
 *       v1 核查分级（必须改/建议改/提示）+ 一键修正、润色预览、批注回复/解决、审签（复用卫华 reviews）、定稿锁定（409）。
 * 人把关点：送审签、审签通过（领导）。外部协作者：无此应用权限。 */
(function () {
  const DEF = { name: '公文协作', summary: '选事项、填要素，AI 起草并核查', steps: ['要办什么事', '填要素', '初稿与核查', '批注与送审'], tabs: [['flow', '起草'], ['list', '可见文稿']], redHead: '', approvers: ['李阳'], inputTypes: {}, intentMap: [], levels: { error: '必须改', warn: '建议改', info: '提示', ok: '通过' }, polishStyles: [['formal', '更正式']], text: {} };
  const C = Object.assign({}, DEF, (window.JK_APPCFG || {}).document || {});
  const T = Object.assign({ pickQ: '要办什么事？', pickSub: '', fillQ: '填要素', fillSub: '', draftQ: '初稿', draftSub: '', reviewQ: '批注与送审', reviewSub: '', watermark: '未定稿' }, C.text);
  const CN = '一二三四五六七八九十';

  const bookShort = window.JK_DATA?.enterprises.find((e) => e.id === 'E001')?.short;
  const bookReply = `打开${bookShort ? bookShort + '的' : ''}答复意见`;
  const numberLabel = '发文字号（请填写）';
  const fieldLabels = { title: '标题', docNo: '发文字号', to: '主送机关', sign: '发文机关', date: '成文日期' };

  JK.registerApp({
    manifest: {
      id: 'document', name: C.name, short: '公文', icon: 'doc', hue: 'orange', version: '4.0.0', owner: 'AI 工作组',
      summary: C.summary, routes: ['flow', 'new', 'detail', 'compare', 'list'],
      perms: { view: '看文稿', operate: '起草、核查、送审', approve: '审签定稿' },
      tools: [
        { name: 'document.templates', desc: '10 类公文事项模板', params: {} },
        { name: 'document.draft', desc: '按模板和要素生成初稿', params: { templateId: 'string', inputs: 'object' } },
        { name: 'document.check', desc: '核查文号/日期/数字/错别字/语体', params: { id: 'string' } },
        { name: 'document.polish', desc: '润色预览（不直接改）', params: { id: 'string', style: 'formal|concise' } },
        { name: 'document.compare', desc: '两个版本比对', params: { id: 'string', a: 'number', b: 'number' } },
      ],
      accepts: [{ kind: '公文范文 / 待改文稿', ext: ['doc', 'docx', 'txt', 'pdf', 'wps'], match: /通知|公文|意见|方案|函|公示|请示|报告|纪要|范文/ }],
      intents: [
        { id: 'document.draft', requires: 'operate', action: 'draft', examples: ['起草一份数据券申报延期通知', '写一份企业诉求答复意见', '帮我起草 AI 场景征集通知'], keywords: ['起草', '写一份', '拟一份', '草拟'], slots: { template: 'docTemplate' }, plan: ['选事项模板', '填要素', '生成初稿', '自动核查'] },
        { id: 'document.check', action: 'check', examples: ['核查一下这份公文', '检查文号日期有没有问题'], keywords: ['核查', '检查', '校对'], plan: ['打开初稿', '逐项核查', '列出问题'] },
        { id: 'document.fix', requires: 'operate', action: 'fix', examples: ['一键修正核查出的问题', '把能改的都改了'], keywords: ['修正', '改掉', '一键修'], plan: ['核查', '一键修正', '生成新版本'] },
        { id: 'document.polish', requires: 'operate', action: 'polish', examples: ['润色一下，更正式些', '精简一下这份公文'], keywords: ['润色', '精简', '正式一点'], plan: ['润色预览', '看修改对比', '等你决定是否采用'] },
        { id: 'document.compare', action: 'compare', examples: ['对比一下第1版和第2版', '这版改了哪些地方'], keywords: ['对比', '比对', '改了哪些', '版本'], plan: ['打开版本', '选两版', '标出增删'] },
        { id: 'document.submit', requires: 'operate', action: 'submit', examples: ['送审签', '提交给李阳审签'], keywords: ['送审', '审签', '提交审核'], plan: ['核查无必须改问题', '等你确认', '提交审签'] },
        { id: 'document.approve', requires: 'approve', action: 'approve', examples: ['审签通过', '把这份公文退回修改'], keywords: ['通过', '退回', '签发'], plan: ['打开待审文稿', '等你确认', '通过或退回'] },
        { id: 'document.export', action: 'export', examples: ['导出 Word', '把答复意见导出成 Word'], keywords: ['导出', 'Word'], plan: ['打开文稿', '导出公文版式 Word'] },
        { id: 'document.open', action: 'open', examples: [bookReply, '看看我的文稿'], keywords: ['打开', '我的文稿', '文稿'], plan: ['打开我的文稿', '找到文稿'] },
      ],
      starters: ['起草一份数据券申报延期通知', bookReply, '对比一下第1版和第2版'],
      demo: [
        { title: '起草+核查', say: '起草一份数据券申报延期通知' },
        { title: '版本对比', say: `${bookReply}，对比一下第1版和第2版` },
      ],
    },

    mount(el, ctx) {
      const { ui, api, perms } = ctx; const D = api.document; const esc = ui.esc, icon = ui.icon, tag = ui.tag;
      const canView = perms.can('view') && !perms.isPartner, canOp = canView && perms.can('operate'), canApprove = canView && perms.can('approve');
      const S = { tab: 'flow', step: 0, tpl: null, inputs: {}, from: null, refs: new Set(), hits: null, id: null, doc: null, view: null, panel: 'check', issues: null, polish: null, pstyle: 'formal', cmp: null, cmpA: null, cmpB: null, edit: null, editing: null, hl: null, cpara: 0, busy: false };
      // 起草要素按草稿隔离，仅在当前公文会话保存；不从正文猜字段，也不写入共享记录。
      const draftForms = new Map();
      let TPLS = [], GROUPS = [], DOCS = [], POLS = null, ENTS = null, loaded = false, loadErr = null;
      let saving = false;
      const $ = (s) => el.querySelector(s);
      const tplOf = (id) => TPLS.find((t) => t.id === id);
      const latest = () => S.doc.versions[S.doc.versions.length - 1];
      const shown = () => (S.view != null ? S.doc.versions.find((v) => v.v === S.view).content : S.edit || latest().content);
      const locked = () => S.doc && S.doc.status === '已定稿';
      const lvl = (l) => C.levels[l] || l;
      let submitFailure;
      const submitNotice = () => submitFailure?.doc === S.doc
        ? `<div class="callout h-red" role="alert">${esc(submitFailure.message)}</div>` : '';
      const updatedLabel = value => {
        const match = /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))?/.exec(value || '');
        return match ? ui.fmtDate(match[1]) + (match[2] ? ' ' + match[2] : '') : value || '—';
      };

      async function load() {
        if (!canView) { loaded = true; return render(); }
        try { const [t, l] = await Promise.all([D.templates(), D.list()]); TPLS = t.items; GROUPS = t.groups || []; DOCS = l.items; loaded = true; loadErr = null; } catch (e) { loadErr = e; }
        render();
      }
      async function refreshList() { try { DOCS = (await D.list()).items; } catch (e) { /* 列表刷新失败不影响当前稿 */ } }
      async function allowLeavingDraft() {
        if (saving) { ui.toast('正在保存，请稍候', { type: 'warn' }); return false; }
        flushEditor();
        if (!S.edit) return true;
        const discard = await ui.confirm('这份公文有未保存的修改，离开后会放弃这些修改。', {
          title: '未保存的修改', danger: true, okText: '放弃修改',
        });
        if (!discard) return false;
        S.edit = null; S.editing = null;
        return true;
      }
      async function switchTab(tab) {
        if (S.tab === tab) return true;
        if (!await allowLeavingDraft()) return false;
        S.tab = tab; render();
        return true;
      }
      async function openDoc(id, step) {
        if (!await allowLeavingDraft()) return false;
        S.id = id; S.doc = null; S.view = null; S.edit = null; S.editing = null; S.issues = null; S.polish = null; S.cmp = null; S.hl = null; S.panel = 'check';
        S.inputs = {}; S.from = null; S.refs = new Set(); S.hits = [];
        S.tab = 'flow'; S.step = step == null ? 2 : step; render();
        try {
          const { item } = await D.get(id);
          if (S.id !== id) return false;
          S.doc = item; S.tpl = tplOf(item.templateId);
          const form = draftForms.get(id);
          if (form) {
            S.inputs = { ...form.inputs }; S.from = form.from;
            S.refs = new Set(form.refs); S.hits = form.hits.slice();
          } else if (item.policyId && S.tpl?.inputs.some(([key]) => key === 'policy')) {
            S.inputs.policy = item.policyId;
          }
          if (step == null && ['审签中', '已定稿', '已退回'].includes(item.status)) S.step = 3;
        } catch (e) {
          if (S.id !== id) return false;
          ui.toast(e.message, { type: 'err' }); S.step = 0;
        }
        body();
        return !!S.doc;
      }

      /* ---------- 框架 ---------- */
      function render() {
        el.innerHTML = `<div class="ap ${S.tab === 'flow' && S.step >= 2 ? 'wide' : ''}"><div class="ap-h">${ui.appIcon('document', 'lg')}<div class="grow"><h2>${esc(C.name)}</h2><div class="ap-sum">${esc(C.summary)}</div></div>${canView ? `<button class="btn ghost sm" data-act="ask" data-op="document.ask">${icon('sparkles')}问 AI</button>` : ''}</div>
          ${canView ? `<div class="tabs ap-tabs">${C.tabs.map(([k, l]) => `<button class="tab ${S.tab === k ? 'on' : ''}" data-tab="${k}" data-op="document.tab-${k}">${esc(l)}${k === 'list' && DOCS.length ? `<span class="count muted">${DOCS.length}</span>` : ''}</button>`).join('')}</div>` : ''}
          <div class="ap-body" id="db"></div></div>`;
        body();
      }
      function body() {
        const b = $('#db'); if (!b) return;
        const ap = el.querySelector('.ap'); if (ap) ap.classList.toggle('wide', S.tab === 'flow' && S.step >= 2);
        if (!canView) { b.innerHTML = ui.empty({ icon: 'lock', title: '你的账号没有公文协作的权限', desc: '如需使用，请联系管理员开通' }); return; }
        if (loadErr) { b.innerHTML = ui.empty({ icon: 'alert', title: '模板没加载出来', desc: loadErr.message || '', action: '重试' }); return; }
        if (!loaded) { b.innerHTML = '<div class="skel-list"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>'; return; }
        if (S.tab === 'list') return renderList(b);
        b.innerHTML = stepsBar() + '<div class="wiz-body" id="ds"></div><div class="wiz-foot" id="df"></div>';
        [step0, step1, step2, step3][S.step]();
      }
      function stepsBar() {
        const max = S.doc ? 3 : S.tpl ? 1 : 0;
        return `<div class="wiz-steps">${C.steps.map((s, i) => `${i ? `<i class="wiz-line ${i <= S.step ? 'done' : ''}"></i>` : ''}<div class="wiz-step ${i === S.step ? 'on' : i < S.step ? 'done' : ''}" ${i !== S.step && i <= max ? `data-step="${i}"` : ''} data-op="document.step-${i}"><span class="n">${i < S.step ? '✓' : i + 1}</span>${esc(s)}</div>`).join('')}</div>`;
      }
      const foot = (l, r) => { const f = $('#df'); if (f) f.innerHTML = `${l || ''}<span class="sp"></span>${r || ''}`; };
      const skel = () => '<div class="skel-list"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>';

      /* ---------- 第 1 步：要办什么事 ---------- */
      function step0() {
        $('#ds').innerHTML = `<div class="q">${esc(T.pickQ)}</div><div class="q-sub">${esc(T.pickSub)}</div>
          ${GROUPS.map(([g, name]) => `<div class="sec row"><span class="dc-gdot h-${ui.hue(name, 'docGroup')}"></span>${esc(name)}</div><div class="stack rows dc-tpls">${TPLS.filter((t) => t.group === g).map((t) => `<button class="card tight dc-tpl ${S.tpl && S.tpl.id === t.id ? 'on sel' : ''}" data-tpl="${t.id}" data-op="document.tpl-${t.id}" ${canOp ? '' : 'disabled'}><div class="row"><b class="grow">${esc(t.name)}</b>${tag(t.kind, 'docType')}</div><div class="meta">${esc(t.purpose)}</div></button>`).join('')}</div>`).join('')}
          ${DOCS.length ? `<div class="sec row">最近的文稿<span class="sp"></span><button class="link" data-tab="list">全部 ${DOCS.length} 份</button></div><div class="stack rows">${DOCS.slice(0, 3).map(docRow).join('')}</div>` : ''}`;
        foot('', canOp ? '' : '<span class="meta">只读：没有起草权限</span>');
      }
      const docRow = (d) => `<div class="card tight li" data-open="${d.id}" data-op="document.doc-${d.id}"><span class="ini h-${ui.hue((tplOf(d.templateId) || {}).groupName || '', 'docGroup')}">${icon('doc')}</span><div class="grow"><div class="t clip">${esc(d.title)}</div><div class="s">${esc((tplOf(d.templateId) || {}).name || '')} · ${esc(d.author)} · ${esc(updatedLabel(d.updated))} · 第 ${d.versions} 版</div></div>${tag(d.status, 'docStatus')}</div>`;
      function pickTpl(id, inputs, from) {
        S.tpl = tplOf(id); S.inputs = {}; S.tpl.inputs.forEach(([k]) => (S.inputs[k] = inputs && inputs[k] != null ? String(inputs[k]) : ''));
        S.from = from || null; S.refs = new Set(); S.hits = null; S.doc = null; S.id = null; S.step = 1; body(); loadRefs();
      }

      /* ---------- 第 2 步：填要素 ---------- */
      async function ensureOpts() {
        const need = S.tpl.inputs.map(([k]) => C.inputTypes[k]);
        try { if (need.includes('policy') && !POLS && api.policy) { const r = await api.policy.items({}); POLS = r.items.slice().sort((a, b) => (b.real ? 1 : 0) - (a.real ? 1 : 0)); } } catch (e) { POLS = []; }
        try { if (need.includes('ent') && !ENTS && api.enterprise) ENTS = (await api.enterprise.list({})).items; } catch (e) { ENTS = []; }
      }
      function inputCtl(k, label) {
        const ty = C.inputTypes[k] || 'text'; const v = S.inputs[k] || ''; const op = `data-op="document.in-${k}" data-in="${k}"`;
        if (ty === 'policy') return `<select class="select" ${op}><option value="">请选择政策事项</option>${(POLS || []).slice(0, 120).map((p) => `<option value="${esc(p.id)}" ${p.id === v ? 'selected' : ''}>${esc(p.title)}${p.example ? ' · 示例（无对应原文）' : ''}</option>`).join('')}</select>`;
        if (ty === 'ent') return `<select class="select" ${op}><option value="">请选择企业</option>${(ENTS || []).map((e) => `<option value="${e.id}" ${e.id === v ? 'selected' : ''}>${esc(e.name)}</option>`).join('')}</select>`;
        if (ty === 'date') return `<input class="input" type="date" ${op} value="${esc(v)}">`;
        if (ty === 'long') return `<textarea class="textarea" rows="2" ${op} placeholder="${esc(label)}">${esc(v)}</textarea>`;
        return `<input class="input" ${op} value="${esc(v)}" placeholder="${esc(label)}">`;
      }
      async function step1() {
        const ds = $('#ds'); const t = S.tpl; if (!t) { S.step = 0; return body(); }
        if (!POLS && !ENTS && t.inputs.some(([k]) => ['policy', 'ent'].includes(C.inputTypes[k]))) { ds.innerHTML = skel(); await ensureOpts(); if (S.step !== 1 || !$('#ds')) return; }
        const pol = S.inputs.policy && (POLS || []).find((p) => p.id === S.inputs.policy);
        const missing = t.inputs.filter(([k]) => !String(S.inputs[k] || '').trim()).length;
        $('#ds').innerHTML = `<div class="q">${esc(T.fillQ)} <span class="t-3">· ${esc(t.name)}</span></div><div class="q-sub">${esc(T.fillSub)}</div>
          ${S.doc ? `<div class="callout h-blue"><div>重新生成会新建草稿，当前文稿和历史版本保留。</div>${draftForms.has(S.doc.id) ? '' : '<div class="meta">当前会话没有这份草稿的完整起草要素，缺失字段需重新填写。</div>'}</div>` : ''}
          ${S.from ? `<div class="callout h-indigo" style="margin-bottom:var(--s4)">${icon('link')}<div>来自${esc(S.from.label || S.from)}：已带上相关要素</div></div>` : ''}
          <div class="dc-fill"><div class="stack">${t.inputs.map(([k, label]) => `<div class="field"><label>${esc(label)}</label>${inputCtl(k, label)}</div>`).join('')}
            <div class="row" style="margin-top:var(--s2)"><button class="btn sm ghost" data-act="sample" data-op="document.sample">${icon('sparkles')}用示例填好</button><span class="sp"></span><span class="meta">${missing ? `还有 ${missing} 项没填` : '要素已齐'}</span></div>
            ${pol ? `<div class="dc-pol"><div class="meta">政策依据</div><b>${esc(pol.title)}</b><div class="meta">${esc(pol.docNo || '无文号')}${!pol.example && pol.source?.url ? ` · <a class="link" href="${esc(pol.source.url)}" target="_blank" rel="noopener">官网原文 ${icon('external')}</a>` : ''}</div></div>` : ''}</div>
            <div><div class="sec">参考范文 <span class="meta">${t.id === 'T03' ? '（初稿按公开政策与已填要素生成；勾选的范文仅供查阅）' : '（勾选后保留为文稿参考）'}</span></div><div id="drefs">${refsHtml()}</div></div></div>`;
        foot(`<button class="btn ghost" data-step="0">换一类</button>`, `<button class="btn primary" data-act="gen" data-op="document.gen" ${S.busy ? 'disabled' : ''}>${S.busy ? '<span class="dc-spin"></span>起草中…' : `${icon('sparkles')}${S.doc ? '重新生成初稿' : '生成初稿'}`}</button>`);
      }
      const refsHtml = () => (S.hits == null ? '<div class="skel-list"><div class="skel"></div><div class="skel"></div></div>' : S.hits.length ? `<div class="stack rows">${S.hits.map((h) => `<label class="card tight li dc-ref"><input type="checkbox" class="cb" data-ref="${esc(h.id)}" ${S.refs.has(h.id) ? 'checked' : ''}><div class="grow"><div class="t clip">${esc(h.title)}</div><div class="s clip2">${esc((h.snippet || '').replace(/<[^>]+>/g, '').slice(0, 70))}</div></div><button class="btn icon sm ghost" data-kb="${esc(h.id)}" title="看原文">${icon('external')}</button></label>`).join('')}</div>` : '<div class="meta">知识库里暂时没有相近的范文</div>');
      async function loadRefs() {
        const t = S.tpl, inputs = S.inputs; let hits = [];
        try { const q = `${t.name.replace(/通知|公示|意见/g, '')} ${String(S.inputs[t.inputs[0][0]] || t.inputs[0][2] || '').slice(0, 20)}`; const r = await ctx.kb.search(q, { space: 'template', limit: 8 }); const seen = new Set(); hits = (r.hits || []).filter((h) => !seen.has(h.title) && seen.add(h.title)).slice(0, 4); } catch (e) { hits = []; }
        if (S.tpl !== t || S.inputs !== inputs) return; S.hits = hits; if (hits[0]) S.refs.add(hits[0].id); const b = $('#drefs'); if (b) b.innerHTML = refsHtml();
      }
      async function generate() {
        if (S.busy) return; S.busy = true; if (S.step === 1) step1();
        try {
          const form = { inputs: { ...S.inputs }, from: S.from, hits: (S.hits || []).slice(), refs: [...S.refs] };
          const refs = form.hits.filter((h) => form.refs.includes(h.id)).map((h) => ({ id: h.id, title: h.title }));
          const r = await D.draft({ templateId: S.tpl.id, inputs: form.inputs, refs });
          draftForms.set(r.item.id, form);
          if (draftForms.size > 50) draftForms.delete(draftForms.keys().next().value);
          S.doc = r.item; S.id = r.item.id; S.view = null; S.edit = null; S.issues = null; S.panel = 'check'; S.step = 2; ctx.audit('生成公文初稿', `${S.tpl.name} · ${r.item.title}`);
          await refreshList(); S.busy = false; render(); await runCheck(true);
        } catch (e) { S.busy = false; ui.toast(e.message, { type: 'err' }); if (S.step === 1) step1(); }
      }

      /* ---------- 稿纸 ---------- */
      function paraHtml(p) { return esc(p).replace(/【待补：(.+?)】/g, '<mark class="dc-miss">待补：$1</mark>'); }
      function paper(c, mode) {
        const editable = mode === 'edit' && canOp && !locked() && !S.view;
        const field = (key, cls) => {
          const label = fieldLabels[key];
          if (editable && S.editing === key) return `<textarea class="textarea dc-ed dc-ed-t" data-ed="${key}" aria-label="${label}">${esc(c[key] || '')}</textarea>`;
          if (!editable && !c[key] && key !== 'docNo') return '';
          return `<div class="${cls}" ${editable ? `data-pe="${key}" title="编辑${label}"` : ''}>${paraHtml(c[key] || (key === 'docNo' ? numberLabel : label + '（点此填写）'))}</div>`;
        };
        const cm = mode === 'comment' ? S.doc.comments || [] : [];
        const badge = (i) => { const n = cm.filter((x) => x.para === i && !x.resolved).length; return mode === 'comment' ? `<button class="dc-cb ${n ? 'on' : ''}" data-cpara="${i}" title="批注">${icon('chat')}${n || ''}</button>` : ''; };
        return `<div class="dc-paper ${locked() ? 'final' : ''}" data-op="document.paper">${locked() ? '' : `<div class="dc-wm">${esc(T.watermark)}</div>`}
          <div class="dc-red" ${editable ? 'data-pe="sign" title="编辑发文机关"' : ''}>${esc(c.sign || C.redHead)}</div>
          ${field('docNo', 'dc-no')}<div class="dc-rule"></div>
          ${S.editing === 'title' && editable ? `<textarea class="textarea dc-ed dc-ed-t" data-ed="title">${esc(c.title)}</textarea>` : `<h1 class="dc-title" ${editable ? 'data-pe="title"' : ''}>${esc(c.title)}</h1>`}
          ${field('to', 'dc-to')}
          ${c.paragraphs.map((p, i) => S.editing === i && editable ? `<textarea class="textarea dc-ed" data-ed="${i}" data-op="document.ed-${i}">${esc(p)}</textarea>` : `<div class="dc-pw">${badge(i)}<p class="dc-p ${S.hl === i ? 'dc-hl' : ''} ${mode === 'comment' && S.cpara === i ? 'sel' : ''}" ${editable ? `data-pe="${i}"` : mode === 'comment' ? `data-cpara="${i}"` : ''} data-op="document.p-${i}">${paraHtml(p)}</p></div>`).join('')}
          ${field('sign', 'dc-sign')}${field('date', 'dc-sign')}</div>`;
      }
      function startEdit(k) { if (saving || !canOp || locked() || S.view != null) return; if (!S.edit) S.edit = JSON.parse(JSON.stringify(latest().content)); S.editing = Object.hasOwn(fieldLabels, k) ? k : +k; step2(); const t = el.querySelector('.dc-ed'); if (t) { t.focus(); t.style.height = t.scrollHeight + 4 + 'px'; } }
      function endEdit(t) {
        if (!S.edit || String(S.editing) !== t.dataset.ed) return;
        const k = t.dataset.ed, value = t.value.trim();
        if (Object.hasOwn(fieldLabels, k)) S.edit[k] = value; else S.edit.paragraphs[+k] = value;
        S.editing = null;
        if (JSON.stringify(S.edit) === JSON.stringify(latest().content)) S.edit = null;
        // 失焦只替换正在编辑的字段，不能移除同一次点击的保存按钮或其他控件。
        if (t.isConnected) {
          const template = document.createElement('template');
          template.innerHTML = paper(shown(), 'edit');
          const selector = k === 'sign' ? '.dc-sign[data-pe="sign"]' : `[data-pe="${CSS.escape(k)}"]`;
          const field = template.content.querySelector(selector);
          if (field) t.replaceWith(field.closest('.dc-pw') || field);
          if (k === 'sign') {
            const red = el.querySelector('.dc-paper .dc-red');
            if (red) red.textContent = (S.edit || latest().content).sign || C.redHead;
          }
        }
        if (!S.edit) $('#dc-unsaved')?.remove();
      }
      function flushEditor() {
        const editor = $('.dc-paper [data-ed]');
        if (editor) endEdit(editor);
      }
      function updateSavedSummary() {
        const { id, title, templateId, status, author } = S.doc;
        const { v, at } = latest();
        const summary = { id, title, templateId, status, author, versions: v, updated: at };
        const existing = DOCS.findIndex(row => row.id === id);
        if (existing >= 0) DOCS[existing] = { ...DOCS[existing], ...summary };
        else DOCS.unshift(summary);
      }
      async function saveEdit(note) {
        if (saving) return false;
        flushEditor();
        if (!S.edit) return true;
        saving = true;
        try {
          const r = await D.save(S.id, { content: S.edit, note: note || '手动修改' });
          S.doc = r.item; S.edit = null; S.issues = null;
          updateSavedSummary();
          ctx.audit('保存公文', `${S.doc.title} · 第 ${latest().v} 版`);
          ui.toast(`已保存为第 ${latest().v} 版`, { type: 'ok' });
          return true;
        } catch (e) {
          ui.toast(e.code === 'LOCKED' ? '已定稿文稿不能修改，请另存新稿' : e.message || '保存失败，修改仍保留', { type: 'err' });
          return false;
        } finally { saving = false; }
      }

      /* ---------- 第 3 步：初稿与核查 ---------- */
      function step2() {
        const ds = $('#ds'); if (!ds) return; if (!S.doc) { ds.innerHTML = skel(); foot(); return; }
        const c = shown(); const vs = S.doc.versions;
        ds.innerHTML = `<div class="row" style="margin-bottom:var(--s3)"><div class="grow"><div class="q" style="margin:0">${esc(T.draftQ)} ${tag(S.doc.status, 'docStatus')} <span class="meta">第 ${S.view ?? latest().v} 版${S.view != null ? '（只读）' : ''}</span></div><div class="q-sub" style="margin:2px 0 0">${esc(locked() ? '已定稿，内容已锁定' : T.draftSub)}</div></div></div>
          ${submitNotice()}${S.view != null ? `<div class="callout h-amber" style="margin-bottom:var(--s3)">${icon('history')}<div class="grow">正在看第 ${S.view} 版（${esc(vs.find((v) => v.v === S.view).by)} · ${esc(updatedLabel(vs.find((v) => v.v === S.view).at))}）</div><button class="btn sm" data-act="latest">回到最新</button>${canOp && !locked() ? `<button class="btn sm" data-act="restore" data-op="document.restore">恢复这一版</button>` : ''}</div>` : ''}
          ${S.edit ? `<div id="dc-unsaved" class="callout h-blue" style="margin-bottom:var(--s3)">${icon('edit')}<div class="grow">有未保存的修改</div><button class="btn sm" data-act="discard">放弃</button><button class="btn sm" data-act="saveEdit" data-op="document.save">保存为第 ${latest().v + 1} 版</button></div>` : ''}
          <div class="dc-split"><div>${paper(c, 'edit')}</div><div class="dc-side">${sidePanel()}</div></div>`;
        foot(`<button class="btn ghost" data-step="1" ${S.tpl ? '' : 'disabled'}>${icon('chevron-left')}要素</button><button class="btn" data-act="word" data-op="document.word">${icon('download')}导出 Word</button>`,
          `<button class="btn primary" data-step="3" data-op="document.to-review">批注与送审 ${icon('arrow-right')}</button>`);
      }
      function sidePanel() {
        const n = S.issues ? S.issues.filter((i) => i.level !== 'ok').length : null;
        const tabs = [['check', `核查${n ? ` <span class="num">${n}</span>` : ''}`], ['polish', '润色'], ['versions', `版本 <span class="num">${S.doc.versions.length}</span>`]];
        return `<div class="seg dc-seg">${tabs.map(([k, l]) => `<button class="${S.panel === k ? 'on' : ''}" data-panel="${k}" data-op="document.panel-${k}">${l}</button>`).join('')}</div><div class="dc-pan">${S.panel === 'check' ? checkPanel() : S.panel === 'polish' ? polishPanel() : versionsPanel()}</div>`;
      }
      const fixable = (i) => i.fix || /^c-(ni|bb)$/.test(i.id);
      function issueAction(i) {
        if (!canOp || locked() || S.view) return '';
        if (fixable(i)) return `<button class="btn sm" data-fix="${esc(i.id)}">修正</button>`;
        const field = i.field || i.target;
        if (Object.hasOwn(fieldLabels, field)) return `<button class="btn sm ghost" data-pe="${field}">填写${fieldLabels[field]}</button>`;
        return i.para != null ? `<button class="btn sm ghost" data-goto="${i.para}">去改</button>` : '';
      }
      function checkPanel() {
        if (!S.issues) return `<div class="dc-empty">${icon('shield', 20)}<div class="meta">核对文号、日期、数字一致、错别字、语体</div><button class="btn sm" data-act="check" data-op="document.check" ${canOp ? '' : 'disabled'}>开始核查</button></div>`;
        const ok = S.issues.length === 1 && S.issues[0].level === 'ok';
        if (ok) return `<div class="dc-empty">${tag('通过', 'checkLevel')}<div>${esc(S.issues[0].text)}</div><button class="btn sm ghost" data-act="check">再核查一次</button></div>`;
        const cnt = (l) => S.issues.filter((i) => i.level === l).length; const nf = S.issues.filter(fixable).length;
        return `<div class="row wrap gap2" style="margin-bottom:var(--s3)">${['error', 'warn', 'info'].filter((l) => cnt(l)).map((l) => `${tag(lvl(l) + ' ' + cnt(l), 'checkLevel', { hue: ui.hue(lvl(l), 'checkLevel') })}`).join('')}<span class="sp"></span><button class="btn sm ghost" data-act="check" title="重新核查">${icon('refresh')}</button></div>
          <div class="stack rows dc-iss">${S.issues.map((i) => `<div class="card tight li" data-iss="${esc(i.id)}"><div class="grow"><div class="row gap2">${tag(lvl(i.level), 'checkLevel')}<b class="t-sm">${esc(i.kind)}</b></div><div class="s" style="margin-top:4px">${esc(i.text)}</div></div>${issueAction(i)}</div>`).join('')}</div>
          ${canOp && nf && !locked() ? `<button class="btn sm" style="width:100%;margin-top:var(--s3)" data-act="fixAll" data-op="document.fix-all">${icon('bolt')}一键修正 ${nf} 处</button>` : ''}`;
      }
      function diffHtml(parts) { return `<div class="diff dc-diff">${parts.map((p) => (p.op === 'eq' ? esc(p.t).slice(0, 4000) : p.op === 'add' ? `<ins>${esc(p.t)}</ins>` : `<del>${esc(p.t)}</del>`)).join('').replace(/\n/g, '<br>')}</div>`; }
      const shortEq = (parts) => parts.map((p) => (p.op === 'eq' && p.t.length > 60 ? { op: 'eq', t: p.t.slice(0, 24) + ' … ' + p.t.slice(-24) } : p));
      function polishPanel() {
        const p = S.polish;
        return `<div class="seg" style="margin-bottom:var(--s3)">${C.polishStyles.map(([k, l]) => `<button class="${S.pstyle === k ? 'on' : ''}" data-pstyle="${k}" data-op="document.pstyle-${k}">${esc(l)}</button>`).join('')}</div>
          ${!p ? `<div class="dc-empty">${icon('sparkles', 20)}<div class="meta">先预览修改，满意再采用；不会直接改稿</div><button class="btn sm" data-act="polish" data-op="document.polish" ${canOp && !locked() ? '' : 'disabled'}>预览润色</button></div>`
            : p.changed ? `${diffHtml(shortEq(p.parts))}<div class="row" style="margin-top:var(--s3)"><button class="btn sm" data-act="polishNo">放弃</button><span class="sp"></span><button class="btn sm" data-act="polishYes" data-op="document.polish-yes">采用（存为新版）</button></div>` : '<div class="dc-empty"><div class="meta">已经很规范，没有需要润色的地方</div></div>'}`;
      }
      function versionsPanel() {
        const vs = S.doc.versions; const a = S.cmpA || (vs.length > 1 ? vs[vs.length - 2].v : 1), b = S.cmpB || vs[vs.length - 1].v;
        const opt = (sel) => vs.map((v) => `<option value="${v.v}" ${v.v === sel ? 'selected' : ''}>第 ${v.v} 版</option>`).join('');
        return `<div class="tl dc-vs">${vs.slice().reverse().map((v) => `<div class="tl-i ${(S.view || vs.length) === v.v ? 'on' : ''}" data-ver="${v.v}" data-op="document.ver-${v.v}"><div class="t">第 ${v.v} 版 ${(S.view || vs.length) === v.v ? '<span class="tag" data-hue="blue">正在看</span>' : ''}</div><div class="m">${esc(v.by)} · ${esc(v.at)}</div></div>`).join('')}</div>
          ${vs.length > 1 ? `<div class="sec">对比</div><div class="row gap2"><select class="select sm" data-cmp="a" data-op="document.cmp-a">${opt(a)}</select><span class="t-3">→</span><select class="select sm" data-cmp="b" data-op="document.cmp-b">${opt(b)}</select><button class="btn sm" data-act="compare" data-op="document.compare">对比</button></div>
            ${S.cmp ? `<div class="row gap2" style="margin:var(--s3) 0 var(--s2)"><span class="tag" data-hue="green">+${S.cmp.stats.add} 字</span><span class="tag" data-hue="red">−${S.cmp.stats.del} 字</span><span class="meta">第 ${S.cmp.a} 版 → 第 ${S.cmp.b} 版</span></div>${diffHtml(shortEq(S.cmp.parts))}` : ''}` : '<div class="meta">只有一个版本。修改、润色、一键修正都会生成新版本。</div>'}`;
      }
      async function runCheck(silent) {
        if (S.edit) await saveEdit();
        try { S.issues = (await D.check(S.id)).issues; } catch (e) { ui.toast(e.message, { type: 'err' }); return; }
        S.panel = 'check'; if (S.step === 2) step2();
        if (!silent) { const e = S.issues.filter((i) => i.level === 'error').length; ui.toast(e ? `核查完成：${e} 处必须改` : '核查完成', { type: e ? 'warn' : 'ok' }); }
        return S.issues;
      }
      async function fix(ids) {
        if (S.edit) await saveEdit();
        try { const r = await D.fix(S.id, { ids }); S.doc = r.item; S.issues = r.issues; S.view = null; ctx.audit('一键修正', `${S.doc.title} · ${ids.length} 处`); ui.toast(`已修正 ${ids.length} 处，生成第 ${S.doc.versions.length} 版`, { type: 'ok' }); step2(); return r; }
        catch (e) { ui.toast(e.message, { type: 'err' }); }
      }
      async function polishPreview() { if (S.edit) await saveEdit(); try { S.polish = await D.polish(S.id, { style: S.pstyle }); S.panel = 'polish'; step2(); return S.polish; } catch (e) { ui.toast(e.message, { type: 'err' }); } }
      async function polishApply() { S.edit = S.polish.preview; S.polish = null; await saveEdit(`润色·${(C.polishStyles.find((x) => x[0] === S.pstyle) || [, ''])[1]}`); step2(); }
      async function compare(a, b) { S.cmpA = a; S.cmpB = b; try { const r = await D.compare({ a: { id: S.id, v: a }, b: { id: S.id, v: b } }); S.cmp = Object.assign(r, { a, b }); S.panel = 'versions'; step2(); return S.cmp; } catch (e) { ui.toast(e.message, { type: 'err' }); } }
      async function restore() { const v = S.view; S.edit = JSON.parse(JSON.stringify(S.doc.versions.find((x) => x.v === v).content)); S.view = null; await saveEdit(`恢复第 ${v} 版`); step2(); }
      async function exportWord() { try { const r = await D.exportWord(S.id); ui.download(r.filename, r.html, 'application/msword'); ctx.audit('导出 Word', r.filename); ui.toast(r.final ? '已导出 Word（正式版式）' : `已导出 Word（带“${T.watermark}”水印）`, { type: 'ok' }); return r; } catch (e) { ui.toast(e.message, { type: 'err' }); } }

      /* ---------- 第 4 步：批注与送审 ---------- */
      function step3() {
        const ds = $('#ds'); if (!ds) return; if (!S.doc) { ds.innerHTML = skel(); foot(); return; }
        const d = S.doc; const cm = d.comments || []; const open = cm.filter((x) => !x.resolved).length;
        ds.innerHTML = `<div class="q">${esc(T.reviewQ)}</div><div class="q-sub">${esc(T.reviewSub)}</div>${submitNotice()}
          ${locked() ? `<div class="callout h-green" style="margin-bottom:var(--s3)">${icon('lock')}<div class="grow">已定稿 · ${esc(latest().content.docNo || numberLabel)}。内容已锁定，需要改请另存新稿</div>${canOp ? '<button class="btn sm" data-act="saveAs" data-op="document.save-as">另存新稿</button>' : ''}</div>` : d.status === '已退回' ? `<div class="callout h-red" style="margin-bottom:var(--s3)">${icon('alert')}<div>审签退回${d.returnReason ? '：' + esc(d.returnReason) : '，请核对批注并修改后重新送审'}</div></div>` : ''}
          <div class="dc-split"><div>${paper(latest().content, 'comment')}</div><div class="dc-side">
            <div class="dc-status"><div class="row gap2">${tag(d.status, 'docStatus')}<span class="meta">第 ${latest().v} 版 · ${esc(d.author)}</span></div>
              <div class="dc-flow">${['草稿', '审签中', '已定稿'].map((s, i) => `<div class="dc-fs ${s === d.status || (d.status === '已退回' && i === 0) ? 'on' : ['草稿', '审签中', '已定稿'].indexOf(d.status) > i ? 'done' : ''}"><span class="dc-si">${['草稿', '审签中', '已定稿'].indexOf(d.status) > i || (d.status === '已定稿' && s === '已定稿') ? icon('check') : ''}</span>${s}</div>`).join('')}</div>
              ${d.status === '审签中' && !canApprove ? `<div class="meta">${icon('clock')}等待审签人处理</div>` : ''}</div>
            <div class="sec">引用资料</div>
            ${(d.refs || []).length ? d.refs.map(ref => `<div class="meta">${esc(ref.marker || '')} ${esc(ref.title || '未提供标题')}${ref.version != null ? ' · 第 ' + esc(ref.version) + ' 版' : ''}</div>`).join('') : '<div class="meta">这份文稿未附引用资料</div>'}
            <div class="sec row">批注 <span class="meta">${open ? `${open} 条未解决` : cm.length ? '都已解决' : ''}</span></div>
            ${cm.length ? `<div class="stack rows dc-cms">${cm.map(cmHtml).join('')}</div>` : '<div class="meta">还没有批注。点左侧段落旁的气泡可加批注</div>'}
            ${!locked() ? `<div class="dc-newc"><div class="meta">给第 ${S.cpara + 1} 段加批注</div><textarea class="textarea" rows="2" id="dcn" data-op="document.cm-text" placeholder="写下修改意见"></textarea><div class="row" style="margin-top:6px"><span class="sp"></span><button class="btn sm" data-act="addCm" data-op="document.cm-add">添加批注</button></div></div>` : ''}
          </div></div>`;
        const right = locked() ? `<button class="btn primary" data-act="word" data-op="document.word">${icon('download')}导出 Word</button>`
          : d.status === '审签中' ? (canApprove ? `<button class="btn" data-act="reject" data-op="document.reject">退回</button><button class="btn primary" data-act="approve" data-op="document.approve">${icon('check')}审签通过</button>` : '')
          : canOp ? `<button class="btn primary" data-act="submit" data-op="document.submit">${icon('send')}送审签</button>` : '';
        foot(`<button class="btn ghost" data-step="2">${icon('chevron-left')}初稿</button>${locked() ? '' : `<button class="btn" data-act="word" data-op="document.word">${icon('download')}导出 Word</button>`}`, right);
      }
      function cmHtml(c) {
        const q = (latest().content.paragraphs[c.para] || '').slice(0, 26);
        return `<div class="card tight dc-cm ${c.resolved ? 'done' : ''}" data-cm="${c.id}"><div class="row gap2"><span class="ini sm h-${ui.hue(c.by)}">${esc(c.by[0])}</span><b class="t-sm">${esc(c.by)}</b><span class="meta">${esc(c.at)}</span><span class="sp"></span>${c.resolved ? tag('已解决', null, { hue: 'green' }) : ''}</div>
          <button class="dc-q" data-cpara="${c.para}">第 ${c.para + 1} 段 · ${esc(q)}…</button><div class="dc-ct">${esc(c.text)}</div>
          ${(c.replies || []).map((r) => `<div class="dc-rp"><b>${esc(r.by)}</b>：${esc(r.text)}</div>`).join('')}
          ${!locked() && canOp ? `<div class="row gap2" style="margin-top:6px"><input class="input sm grow" data-reply="${c.id}" placeholder="回复…"><button class="btn sm ghost" data-resolve="${c.id}">${c.resolved ? '重新打开' : '解决'}</button></div>` : ''}</div>`;
      }
      async function addComment(text) { const t = (text || ($('#dcn') || {}).value || '').trim(); if (!t) return; const r = await D.comment(S.id, { para: S.cpara, text: t }); S.doc.comments.push(r.item); ctx.audit('添加批注', `${S.doc.title} · 第 ${S.cpara + 1} 段`); step3(); return r.item; }
      function submitModal() {
        if (S.edit) { S.step = 2; body(); ui.toast('请先保存修改，核对版本后再送审', { type: 'warn' }); return; }
        const open = (S.doc.comments || []).filter((c) => !c.resolved).length;
        return ui.modal({ title: '送审签', okText: '确认送审', body: `<div class="field"><label for="dsa">审签人</label><select class="select" id="dsa">${C.approvers.map((a) => `<option>${esc(a)}</option>`).join('')}</select></div><div>《${esc(S.doc.title)}》 · 第 ${latest().v} 版</div><div class="meta">${open ? `还有 ${open} 条批注未解决。` : ''}确认后才会送审；取消不提交。</div>`, ok: async (box) => {
          box.querySelector('[data-ok]').disabled = true;
          await doSubmit(box.querySelector('#dsa').value);
        } });
      }
      async function doSubmit(assignee) {
        try { const r = await D.submit(S.id, { assignee }); S.doc = r.item; ctx.audit('送审签', `${S.doc.title} → ${assignee}`); ctx.bus.emit('inbox:changed', { app: 'document', ref: S.id }); await refreshList(); ui.toast(`已送 ${assignee} 审签`, { type: 'ok' }); step3(); return r; }
        catch (e) {
          const message = (e.status >= 400 && e.status < 500 ? '未送审：' : '送审结果未确认：') + (e.message || '请求失败，请刷新文稿核对');
          submitFailure = { doc: S.doc, message };
          ui.toast(message, { type: 'err' });
          if (e.code === 'CHECK_FAILED') { S.step = 2; body(); await runCheck(true); } else step3();
          return { error: e };
        }
      }
      async function decide(decision, comment) {
        try { const rs = (await api.reviews.list()).items; const r = rs.find((x) => x.ref === S.id && x.status === 'pending'); if (!r) { ui.toast('没有找到待审签记录', { type: 'err' }); return; }
          await api.reviews.decide(r.id, { decision, comment, reason: comment }); S.doc = (await D.get(S.id)).item; ctx.audit(decision === 'approve' ? '审签通过' : '审签退回', S.doc.title); ctx.bus.emit('inbox:changed', { app: 'document' }); await refreshList();
          ui.toast(decision === 'approve' ? `已定稿 · ${latest().content.docNo || numberLabel}` : '已退回起草人', { type: 'ok' }); step3(); return S.doc; }
        catch (e) { ui.toast(e.message, { type: 'err' }); return { error: e }; }
      }
      function rejectModal() { return ui.modal({ title: '退回修改', okText: '退回', danger: true, body: '<div class="field"><label for="drj">退回意见</label><textarea class="textarea" id="drj" rows="3" placeholder="写明需要修改的地方"></textarea></div>', ok: async (box) => {
        const input = box.querySelector('#drj'), reason = input.value.trim();
        if (!reason) { ui.toast('请填写退回意见', { type: 'warn' }); input.focus(); return false; }
        await decide('reject', reason);
      } }); }
      async function saveAs() {
        const c = latest().content;
        const { templateId, policyId } = S.doc;
        const r = await D.draft({ templateId, inputs: { policy: policyId } }).catch((e) => {
          if (e.status !== 404 || e.code !== 'NOT_FOUND' || !policyId) throw e;
          return D.draft({ templateId, inputs: {} });
        });
        await D.save(r.item.id, { content: { ...c, docNo: '' }, note: '另存自已定稿文稿' });
        ui.toast('已另存为新稿', { type: 'ok' });
        await refreshList();
        return openDoc(r.item.id, 2);
      }

      /* ---------- 可见文稿 ---------- */
      function renderList(b) {
        const q = (S.lq || '').trim(); const rows = DOCS.filter((d) => !q || d.title.includes(q) || d.status === q);
        b.innerHTML = `<div class="row gap2" style="margin-bottom:var(--s3)"><div class="dc-search grow">${icon('search')}<input class="input" id="dlq" placeholder="标题或状态" value="${esc(S.lq || '')}"></div>${canOp ? `<button class="btn primary" data-act="new">${icon('plus')}起草新公文</button>` : ''}</div>
          <div class="meta" style="margin-bottom:var(--s3)">当前账号有权查看的文稿，不限本人创建。</div>
          ${rows.length ? `<div class="card dc-tblw"><table class="tbl"><thead><tr><th>标题</th><th>事项</th><th>版本</th><th>更新</th><th>状态</th></tr></thead><tbody>${rows.map((d) => `<tr class="click" data-open="${d.id}" data-op="document.row-${d.id}"><td><b>${esc(d.title)}</b><div class="meta">${esc(d.author)}</div></td><td>${tag((tplOf(d.templateId) || {}).groupName || '—', 'docGroup')}</td><td class="num">${d.versions}</td><td class="num meta">${esc(updatedLabel(d.updated))}</td><td>${tag(d.status, 'docStatus')}</td></tr>`).join('')}</tbody></table></div>` : ui.empty({ icon: 'doc', title: q ? '没有匹配的文稿' : '还没有文稿', desc: q ? '换个关键词' : '从“起草”开始写第一份', action: q ? '清空搜索' : '起草新公文' })}`;
      }

      /* ---------- 事件 ---------- */
      el.addEventListener('click', async (ev) => {
        const x = ev.target.closest('[data-tab],[data-step],[data-tpl],[data-open],[data-act],[data-pe],[data-panel],[data-fix],[data-goto],[data-iss],[data-pstyle],[data-ver],[data-cpara],[data-resolve],[data-kb],[data-empty-action]'); if (!x || x.disabled) return; const d = x.dataset;
        if (d.tab) return switchTab(d.tab);
        if (d.step != null && !x.classList.contains('on')) { const k = +d.step; if (k >= 2 && !S.doc) return; if (k === 1 && !S.tpl) return; if (k !== 2 && !await saveEdit()) return; S.step = k; body(); return; }
        if (d.tpl) { if (await allowLeavingDraft()) return pickTpl(d.tpl); return; }
        if (d.open) return openDoc(d.open);
        if (d.kb) { ev.preventDefault(); return ctx.kb.open(d.kb); }
        if (d.pe != null) return startEdit(d.pe);
        if (d.panel) { S.panel = d.panel; step2(); return; }
        if (d.fix) return fix([d.fix]);
        if (d.goto != null) { S.hl = +d.goto; return startEdit(d.goto); }
        if (d.iss) { const i = S.issues.find((y) => y.id === d.iss); if (i && i.para != null) { S.hl = i.para; step2(); const p = el.querySelector(`[data-op="document.p-${i.para}"]`); if (p) p.scrollIntoView({ block: 'center', behavior: 'smooth' }); } return; }
        if (d.pstyle) { S.pstyle = d.pstyle; S.polish = null; step2(); return; }
        if (d.ver) { if (!await allowLeavingDraft()) return; const v = +d.ver; S.view = v === latest().v ? null : v; step2(); return; }
        if (d.cpara != null) { S.cpara = +d.cpara; step3(); const t = $('#dcn'); if (t) t.focus(); return; }
        if (d.resolve) { const c = S.doc.comments.find((y) => y.id === d.resolve); const r = await D.patchComment(S.id, c.id, { resolved: !c.resolved }); Object.assign(c, r.item); step3(); return; }
        if (d.emptyAction != null) { if (loadErr) { loaded = false; body(); return load(); } if (S.lq) { S.lq = ''; return renderList($('#db')); } S.tab = 'flow'; S.step = 0; render(); return; }
        const a = d.act;
        if (a === 'ask') return ctx.nav.chat(S.doc ? `「${S.doc.title}」还有哪些地方要改？` : '公文里日期、文号有哪些规范？');
        if (a === 'new') { if (!await allowLeavingDraft()) return; S.tab = 'flow'; S.step = 0; S.tpl = null; S.doc = null; render(); return; }
        if (a === 'sample') { S.tpl.inputs.forEach(([k, , v]) => { if (!String(S.inputs[k] || '').trim()) S.inputs[k] = v; }); return step1(); }
        if (a === 'gen') return generate();
        if (a === 'check') return runCheck();
        if (a === 'fixAll') return fix(S.issues.filter(fixable).map((i) => i.id));
        if (a === 'polish') return polishPreview();
        if (a === 'polishYes') return polishApply();
        if (a === 'polishNo') { S.polish = null; step2(); return; }
        if (a === 'compare') return compare(+$('[data-cmp="a"]').value, +$('[data-cmp="b"]').value);
        if (a === 'latest') { S.view = null; step2(); return; }
        if (a === 'restore') return restore();
        if (a === 'saveEdit') { await saveEdit(); step2(); return; }
        if (a === 'discard' && !saving) { S.edit = null; S.editing = null; step2(); return; }
        if (a === 'word') return exportWord();
        if (a === 'addCm') return addComment();
        if (a === 'submit') return submitModal();
        if (a === 'approve') return decideConfirm();
        if (a === 'reject') return rejectModal();
        if (a === 'saveAs') return saveAs();
      });
      const decideConfirm = () => ui.modal({ title: '审签通过', okText: '通过并定稿', body: '<div>通过后文稿定稿，保留当前文号，内容锁定。</div>', ok: async () => { await decide('approve', '同意'); } });
      el.addEventListener('focusout', (ev) => { const t = ev.target; if (t.dataset && t.dataset.ed != null && S.editing != null) endEdit(t); });
      el.addEventListener('keydown', (ev) => { const t = ev.target; if (t.dataset && t.dataset.reply && ev.key === 'Enter' && t.value.trim()) { const id = t.dataset.reply; D.patchComment(S.id, id, { reply: t.value.trim() }).then((r) => { Object.assign(S.doc.comments.find((c) => c.id === id), r.item); step3(); }); } if (t.dataset && t.dataset.ed != null && ev.key === 'Escape') { S.editing = null; step2(); } });
      el.addEventListener('change', (ev) => { const t = ev.target; if (t.dataset.in) { S.inputs[t.dataset.in] = t.value; if (C.inputTypes[t.dataset.in] === 'policy') step1(); } if (t.dataset.ref) { t.checked ? S.refs.add(t.dataset.ref) : S.refs.delete(t.dataset.ref); } });
      el.addEventListener('input', (ev) => { const t = ev.target; if (t.dataset.in) S.inputs[t.dataset.in] = t.value; if (t.classList.contains('dc-ed')) { t.style.height = 'auto'; t.style.height = t.scrollHeight + 4 + 'px'; } if (t.id === 'dlq') { S.lq = t.value; clearTimeout(S._q); S._q = setTimeout(() => { renderList($('#db')); const i = $('#dlq'); if (i) { i.focus(); i.setSelectionRange(i.value.length, i.value.length); } }, 200); } });

      load();

      /* ---------- 操作员动作 ---------- */
      const ready = async () => { for (let i = 0; i < 60 && !loaded; i++) await new Promise((r) => setTimeout(r, 50)); };
      const noPerm = (run, w) => run && run.fail(w || '你的账号没有公文协作的操作权限');
      function resolveTpl(slot, text) { const s = String(slot || '') + ' ' + String(text || ''); const byId = TPLS.find((t) => s.includes(t.id) || s.includes(t.name)); if (byId) return byId.id; const m = C.intentMap.find(([re]) => re.test(s)); return m ? m[1] : null; }
      function resolveDoc(text, pool) {
        const s = String(text || '').replace(/打开|对比|导出|审签|通过|退回|一下|看看|这份|第\s*\d+\s*版/g, ' ');
        const bi = new Set(); for (let i = 0; i < s.length - 1; i++) { const w = s.slice(i, i + 2); if (/^[\u4e00-\u9fa5]{2}$/.test(w) && !/关于|通知|的通|意见/.test(w)) bi.add(w); }
        const sc = (pool || DOCS).map((d) => [d, [...bi].filter((w) => d.title.includes(w)).length]).sort((a, b) => b[1] - a[1]);
        return sc.length && sc[0][1] >= 2 && (!sc[1] || sc[0][1] > sc[1][1]) ? sc[0][0].id : null;
      }
      const inFlow = () => { if (S.tab !== 'flow') { S.tab = 'flow'; render(); } };
      async function needDoc(text, run, step) {
        const id = resolveDoc(text) || S.id; if (!id) { run && run.fail('先打开或起草一份文稿'); return null; }
        inFlow(); if (S.id !== id || !S.doc) { if (run && S.id !== id) { if (S.tab !== 'list') await run.click('[data-op="document.tab-list"]'); await run.click(`[data-op="document.row-${id}"]`); await run.wait(() => S.doc && S.doc.id === id); } else await openDoc(id, step); }
        if (S.step !== step) { S.step = step; body(); }
        return S.doc;
      }
      const sumIssues = () => { const c = (l) => S.issues.filter((i) => i.level === l).length; return S.issues.length === 1 && S.issues[0].level === 'ok' ? '核查通过' : `核查：${['error', 'warn', 'info'].filter((l) => c(l)).map((l) => `${lvl(l)} ${c(l)} 处`).join('、')}`; };
      const actions = {
        async draft({ template, text, inputs } = {}, run) {
          await ready(); if (!canOp) return noPerm(run); const id = resolveTpl(template, text); if (!id) { run && run.fail('没认出是哪类公文，可以说“申报通知”“延期通知”“答复意见”等'); return; }
          inFlow(); if (!run) { pickTpl(id, inputs); if (!inputs) S.tpl.inputs.forEach(([k, , v]) => { if (!S.inputs[k]) S.inputs[k] = v; }); await generate(); return S.doc; }
          if (S.step !== 0) { S.step = 0; body(); }
          await run.step(1); await run.click(`[data-op="document.tpl-${id}"]`); await run.wait('[data-op="document.sample"]', 6000);
          await run.step(2); if (inputs) { for (const [k, v] of Object.entries(inputs)) if (el.querySelector(`[data-op="document.in-${k}"]`)) { S.inputs[k] = String(v); } step1(); await run.sleep(300); }
          if (window.JKDemo && JKDemo.state && JKDemo.state.on && C.demoInputs) Object.entries(C.demoInputs).forEach(([k, v]) => { if (!String(S.inputs[k] || '').trim()) S.inputs[k] = v; });
          await run.click('[data-op="document.sample"]');
          await run.step(3); await run.click('[data-op="document.gen"]'); await run.wait(() => S.doc && S.issues && el.querySelector('[data-op="document.paper"]'), 10000);
          await run.step(4); await run.highlight('.dc-side'); const nf = S.issues.filter(fixable).length;
          run.done(`已起草「${S.doc.title}」，${sumIssues()}`, [...(nf ? [{ label: `一键修正 ${nf} 处`, say: '一键修正核查出的问题' }] : []), { label: '润色', say: '润色一下，更正式些' }, { label: '送审签', say: '送审签' }]);
          return S.doc;
        },
        async check({ text } = {}, run) {
          await ready(); if (!(await needDoc(text, run, 2))) return;
          if (run) { await run.step(1); await run.click('[data-op="document.panel-check"]'); if (el.querySelector('[data-op="document.check"]')) await run.click('[data-op="document.check"]'); else await runCheck(true); await run.wait(() => S.issues); await run.step(2); await run.highlight('.dc-side'); const nf = S.issues.filter(fixable).length; run.done(sumIssues(), nf ? [{ label: `一键修正 ${nf} 处`, say: '一键修正核查出的问题' }] : []); }
          else await runCheck(true);
          return S.issues;
        },
        async fix({ text } = {}, run) {
          await ready(); if (!canOp) return noPerm(run); if (!(await needDoc(text, run, 2))) return; if (locked()) { run && run.fail('已定稿，不能修改'); return; }
          if (!S.issues) await runCheck(true); const ids = S.issues.filter(fixable).map((i) => i.id);
          if (!ids.length) { run && run.done(`没有可自动修正的问题。${sumIssues()}`); return; }
          if (run) { await run.step(1); await run.click('[data-op="document.panel-check"]'); await run.click('[data-op="document.fix-all"]'); const n0 = S.doc.versions.length; await run.wait(() => S.doc.versions.length > n0); await run.step(2); const left = S.issues.filter((i) => i.level === 'error').length; run.done(`已修正 ${ids.length} 处，生成第 ${S.doc.versions.length} 版。${left ? `还有 ${left} 处必须人工改` : sumIssues()}`, [{ label: '看改了什么', say: '这版改了哪些地方' }]); }
          else await fix(ids);
        },
        async polish({ style, text } = {}, run) {
          await ready(); if (!canOp) return noPerm(run); if (!(await needDoc(text, run, 2))) return; if (locked()) { run && run.fail('已定稿，不能修改'); return; }
          const st = style || (/精简|简洁|压缩/.test(text || '') ? 'concise' : 'formal');
          if (!run) { S.pstyle = st; return polishPreview(); }
          await run.step(1); await run.click('[data-op="document.panel-polish"]'); await run.click(`[data-op="document.pstyle-${st}"]`); await run.click('[data-op="document.polish"]'); await run.wait(() => S.polish);
          await run.step(2); if (!S.polish.changed) { run.done('已经很规范，没有需要润色的地方'); return; }
          const c = await run.ask('润色修改已标出（绿色新增、红色删除），采用吗？', ['采用', '放弃']);
          if (c === '采用') { await run.click('[data-op="document.polish-yes"]'); await run.wait(() => !S.polish && !S.edit); run.done(`已采用，存为第 ${S.doc.versions.length} 版`); } else { S.polish = null; step2(); run.done('已放弃，原稿未改'); }
        },
        async compare({ text, a, b } = {}, run) {
          await ready(); if (!(await needDoc(text, run, 2))) return; const vs = S.doc.versions; if (vs.length < 2) { run && run.done('这份文稿只有一个版本'); return; }
          const nums = String(text || '').match(/第\s*(\d+)\s*版/g); let va = a, vb = b; if (nums && nums.length >= 2) { va = +nums[0].match(/\d+/)[0]; vb = +nums[1].match(/\d+/)[0]; } va = va || vs[vs.length - 2].v; vb = vb || vs[vs.length - 1].v;
          if (!run) return compare(va, vb);
          await run.step(1); await run.click('[data-op="document.panel-versions"]'); await run.select('[data-op="document.cmp-a"]', String(va)); await run.select('[data-op="document.cmp-b"]', String(vb)); await run.step(2); await run.click('[data-op="document.compare"]'); await run.wait(() => S.cmp && S.cmp.a === va && S.cmp.b === vb);
          await run.highlight('.dc-diff'); run.done(`第 ${va} 版 → 第 ${vb} 版：新增 ${S.cmp.stats.add} 字、删除 ${S.cmp.stats.del} 字（绿色新增、红色删除）`, canOp && !locked() ? [{ label: `恢复第 ${va} 版`, say: `恢复第 ${va} 版` }] : []);
          return S.cmp;
        },
        async submit({ text } = {}, run) {
          await ready(); if (!canOp) return noPerm(run); if (!(await needDoc(text, run, 3))) return;
          if (S.doc.status === '审签中' || locked()) { run && run.done(`这份文稿${S.doc.status}，不需要再送审`); return; }
          if (!run) return submitModal();
          await run.step(1); const iss = (await D.check(S.id)).issues; const errs = iss.filter((i) => i.level === 'error');
          if (errs.length) { S.issues = iss; S.step = 2; body(); await run.highlight('.dc-side'); run.fail(`还有 ${errs.length} 处必须改的问题：${errs.map((e) => e.text).join('；')}`); return; }
          await run.step(2); await run.highlight('[data-op="document.submit"]', '确认后才送审');
          const open = (S.doc.comments || []).filter((c) => !c.resolved).length;
          const c = await run.ask(`送 ${C.approvers[0]} 审签第 ${latest().v} 版「${S.doc.title}」${open ? `（还有 ${open} 条批注未解决）` : ''}，确认吗？`, ['确认送审', '再看看']);
          if (c !== '确认送审') { run.done('好的，没有送审'); return; }
          await run.step(3); await run.click('[data-op="document.submit"]'); await run.wait('[role="dialog"] [data-ok]'); await run.click('[role="dialog"] [data-ok]'); await run.wait(() => S.doc.status === '审签中');
          run.done(`已送 ${C.approvers[0]} 审签`);
        },
        async approve({ text } = {}, run) {
          await ready(); if (!canApprove) return noPerm(run, '需要审签权限：请用审签领导账号（如 李阳）处理');
          const pend = DOCS.filter((d) => d.status === '审签中'); const id = resolveDoc(text, pend) || (S.doc && S.doc.status === '审签中' ? S.id : pend[0] && pend[0].id); if (!id) { run && run.done('没有待审签的文稿'); return; }
          const rej = /退回|驳回|不同意/.test(text || '');
          if (!(await needDoc(id === S.id ? '' : (DOCS.find((d) => d.id === id) || {}).title, run, 3))) return;
          if (!run) return decide(rej ? 'reject' : 'approve', rej ? '请修改' : '同意');
          await run.step(1); await run.highlight('[data-op="document.paper"]');
          const c = await run.ask(rej ? `退回「${S.doc.title}」给 ${S.doc.author} 修改吗？` : `审签通过「${S.doc.title}」？通过后定稿，内容锁定。`, [rej ? '确认退回' : '确认通过', '再看看']);
          if (!/^确认/.test(c || '')) { run.done('好的，暂不处理'); return; }
          await run.step(2);
          const result = await decide(rej ? 'reject' : 'approve', rej ? '请按批注修改' : '同意');
          if (result?.error) return run.fail(result.error.message);
          if (!result) return run.fail('没有找到待审签记录');
          run.done(rej ? '已退回起草人' : `已定稿 · ${latest().content.docNo || numberLabel}`);
        },
        async export({ text } = {}, run) {
          await ready(); if (!(await needDoc(text, run, S.step >= 2 ? S.step : 2))) return;
          if (run) { await run.step(1); await run.click('[data-op="document.word"]'); run.done(`已导出「${S.doc.title}」Word${locked() ? '（正式版式）' : `（带“${T.watermark}”水印）`}`); } else return exportWord();
        },
        async open({ text } = {}, run) {
          await ready(); const id = resolveDoc(text);
          if (!id) { if (run) { await run.click('[data-op="document.tab-list"]'); run.done(`你有 ${DOCS.length} 份文稿：${DOCS.slice(0, 4).map((d) => `${d.title}（${d.status}）`).join('；')}`); } else { S.tab = 'list'; render(); } return; }
          if (run) { await run.step(1); if (S.tab !== 'list') await run.click('[data-op="document.tab-list"]'); await run.click(`[data-op="document.row-${id}"]`); await run.wait(() => S.doc && S.doc.id === id && el.querySelector('[data-op="document.paper"]'));
            const d = S.doc; const open = (d.comments || []).filter((c) => !c.resolved).length;
            if (/对比|改了/.test(text || '')) return actions.compare({ text }, run);
            run.done(`「${d.title}」${d.status}，第 ${d.versions.length} 版${open ? `，${open} 条批注未解决` : ''}`, [...(d.versions.length > 1 ? [{ label: '版本对比', say: '这版改了哪些地方' }] : []), { label: '导出 Word', say: '导出 Word' }]); }
          else await openDoc(id);
        },
        async intake({ file } = {}, run) {
          await ready(); let n = 0; try { const r = await ctx.kb.import([file], { space: 'template', from: '公文协作' }); n = (r.docs || []).length; } catch (e) { /* 知识库不可用时只提示 */ }
          const id = resolveTpl('', file.name + ' ' + String(file.text || '').slice(0, 200));
          inFlow(); if (id && canOp) { pickTpl(id); S.from = { label: `范文「${file.name}」` }; step1(); }
          run && run.done(`「${file.name}」${n ? '已存入知识库“公文范文”' : '已收到'}${id ? `，识别为“${tplOf(id).name}”，已按它打开起草` : ''}`, id ? [{ label: '用示例填好并起草', say: `起草一份${tplOf(id).name}` }] : []);
        },
      };
      return {
        go(route, params = {}) {
          ready().then(() => {
            if (route === 'list') { S.tab = 'list'; render(); return; }
            if (route === 'new') { S.tab = 'flow'; render(); if (params.templateId && tplOf(params.templateId)) { const fromMap = { policy: '政策匹配', meeting: '会议纪要', enterprise: '企业管理' }; const f = params.from; pickTpl(params.templateId, params.inputs, f ? { label: typeof f === 'string' ? fromMap[f] || f : `${fromMap[f.app] || f.app}${f.title ? `「${f.title}」` : ''}` } : null); } else { S.step = 0; S.tpl = null; S.doc = null; body(); } return; }
            if ((route === 'detail' || route === 'compare') && params.id) { openDoc(params.id, route === 'compare' ? 2 : null).then(() => { if (route === 'compare' && S.doc && S.doc.versions.length > 1) compare(S.doc.versions[S.doc.versions.length - 2].v, latest().v); }); return; }
            S.tab = 'flow'; render();
          });
        },
        actions,
        unmount() {},
      };
    },
  });
})();

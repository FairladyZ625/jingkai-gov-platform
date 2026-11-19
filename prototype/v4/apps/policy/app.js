/* 政策兑现（app id: policy）· v4 综合版
 * 合并：v2 四步向导（选对象→核对→试算→告知单） + v1 手动画像/试算预设/data-op 锚点 + v3 补数即重算、告知单可编辑
 * 契约：APP_CONTRACT.md（mount(el, ctx) 返回 { go, actions }）；颜色只走 ctx.ui.tag / theme 变量；文案在 config.js */
(function () {
  const clz = (c) => String(c || '').replace(/第\s*([^\s第]+?)\s*(项|条|款|章)/g, '第$1$2').replace(/、\s+/g, '、');
  const seedShort = (id) => window.JK_DATA?.enterprises?.find((e) => e.id === id)?.short || '示例企业';
  const DEF = { name: '政策兑现', summary: '按企业情况逐条核对兑现事项', steps: ['选对象', '核对条件', '试算额度', '告知单'], tabs: [['flow', '办理'], ['items', '事项库'], ['docs', '政策文件']], samples: [], objects: ['企业', '个人', '其他组织'], manualTags: [], licenses: [], fields: {}, sampleFill: {}, levels: { ok: ['可进一步核对'], check: ['待确认'], no: ['不满足'] }, windowText: { open: '申报中', ended: '本批已结束', unknown: '窗口待通知' }, text: {} };
  const C = Object.assign({}, DEF, (window.JK_APPCFG || {}).policy || {});
  const T = Object.assign({ pickQ: '为谁核对？', pickSub: '搜企业，或手动描述情况', resultEmpty: '没有适用事项', resultEmptyDesc: '检查企业标签是否完整', viewOnly: '你的角色只能查看事项库', demoBadge: '示例（无对应原文）' }, C.text);

  JK.registerApp({
    manifest: {
      id: 'policy', name: C.name, short: '政策', icon: 'policy', hue: 'indigo', version: '4.0.0', owner: 'AI 工作组',
      summary: C.summary, routes: ['flow', 'match', 'calc', 'notice', 'items', 'detail', 'docs'],
      perms: { view: '查看事项库与原文', operate: '匹配 / 试算 / 告知单', approve: '—' },
      tools: [
        { name: 'policy.match', desc: '为企业逐条核对兑现事项', params: { entId: 'string' } },
        { name: 'policy.calc', desc: '按原文规则试算额度', params: { itemId: 'string', amount: 'number' } },
        { name: 'policy.notice', desc: '生成一次性告知单', params: { entId: 'string', itemIds: 'string[]' } },
        { name: 'policy.search', desc: '按口语搜索兑现事项', params: { q: 'string' } },
      ],
      accepts: [{ kind: '政策文件', ext: ['pdf', 'doc', 'docx', 'txt', 'wps'], match: /政策|办法|细则|措施|若干|实施意见|申报指南/ }],
      intents: [
        { id: 'policy.match', action: 'match', examples: [`帮我查一下${seedShort('E002')}能申报哪些政策`, `${seedShort('E001')}能申请哪些支持？`], keywords: ['政策', '申报', '补贴', '兑现', '能报', '支持', '奖励'], slots: { ent: 'enterprise' }, plan: ['打开政策兑现', '选择企业', '逐条核对事项', '汇总结论'] },
        { id: 'policy.fill', action: 'fill', examples: ['补填数据采购额 30 万', '数据采购额是 30 万'], keywords: ['补填', '补充', '采购额', '重算'], slots: { amount: 'amount' }, plan: ['找到待确认项', '填入数值', '重新核对'] },
        { id: 'policy.calc', action: 'calc', examples: ['数据采购 200 万能补多少', '书店年房租 42 万能补多少', '算一下算力采购 680 万的补贴'], keywords: ['能补多少', '试算', '算一下', '额度'], slots: { amount: 'amount', policy: 'policy' }, plan: ['打开试算', '选择事项', '填入金额', '给出额度'] },
        { id: 'policy.notice', action: 'notice', examples: [`给${seedShort('E002')}生成政策告知单`, '生成一次性告知单'], keywords: ['告知单', '告知书', '告知'], slots: { ent: 'enterprise' }, plan: ['核对事项', '试算额度', '生成告知单', '等你确认'] },
        { id: 'policy.detail', action: 'detail', examples: ['实体书店房租补贴的条件是什么', '数据券的申报条件'], keywords: ['条件是什么', '什么条件', '怎么申请', '要求'], slots: { policy: 'policy' }, plan: ['打开事项库', '找到事项', '展示条件与原文'] },
        { id: 'policy.items', action: 'items', examples: ['看看面向个人的政策', '打开政策事项库'], keywords: ['事项库', '有哪些政策', '个人政策'], plan: ['打开事项库', '筛选'] },
        { id: 'policy.toDocument', action: 'toDocument', examples: ['把告知单转成公文答复'], keywords: ['转公文', '答复函', '答复意见'], plan: ['带上企业与政策', '打开公文协作'] },
      ],
      starters: [`${seedShort('E001')}能申请哪些支持？`, '数据采购 200 万能补多少', '实体书店房租补贴的条件是什么'],
      // 一键演示主演企业 E020：无数据采购额，补填 30 万后数据券两项可核对并出额度。
      demo: [
        { title: '政策匹配', say: `帮我查一下${seedShort('E020')}能申报哪些政策` },
        { title: '补填再算', say: '补填数据采购额 30 万' },
        { title: '告知单', say: `给${seedShort('E020')}生成政策告知单` },
      ],
    },

    mount(el, ctx) {
      const { ui, api, perms } = ctx; const P = api.policy, E = api.enterprise; const esc = ui.esc, icon = ui.icon, tag = ui.tag;
      const canOp = perms.can('operate');
      const S = { tab: canOp ? 'flow' : 'items', step: 0, mode: 'ent', entId: null, manual: { object: '企业', tags: [], license: [], yearsInZone: '', amounts: {} }, overrides: {}, match: null, filter: null, picked: new Set(), open: new Set(), calc: {}, notice: '', q: '', obj: '', win: '', busy: false, error: null };
      let ITEMS = [], DOCS = [], ENTS = [], loaded = false, loadErr = null;
      const byId = (id) => ITEMS.find((x) => x.id === id);
      const ent = () => ENTS.find((e) => e.id === S.entId);
      const F = (k) => C.fields[k] || [k, '', 1];
      const winOf = (p) => (p.times && p.times.open === true ? C.windowText.open : p.times && p.times.open === false ? C.windowText.ended : C.windowText.unknown);
      const toUnit = (k, v) => (v == null || v === '' ? '' : +(v / F(k)[2]).toFixed(2));
      const fmt = ui.fmtMoney;
      const docOf = (p) => DOCS.find((d) => d.id === p.doc) || {};
      const srcUrl = (p) => p.example ? '' : p.source?.url || p.url || docOf(p).url || '';
      const refOf = (p) => p.example ? T.demoBadge : [p.docNo, clz(p.clause)].filter(Boolean).join(' ');
      const exampleTag = (p) => p.example ? tag(T.demoBadge, 'status', { cls: 'plain' }) : '';

      /* ---------- 加载 ---------- */
      async function load() {
        try {
          const [it, en] = await Promise.all([P.items(), E.list({ sort: 'name' }).catch(() => ({ items: [] }))]);
          ITEMS = it.items.filter((p) => !perms.isPartner || !p.status || p.status === '已发布'); DOCS = it.docs || []; ENTS = en.items || []; loaded = true; loadErr = null;
        } catch (e) { loadErr = e; }
        render();
      }

      /* ---------- 框架 ---------- */
      function render() {
        const tabs = C.tabs.map(([k, l]) => `<button class="tab ${S.tab === k ? 'on' : ''}" data-tab="${k}" data-op="policy.tab-${k}">${esc(l)}${k === 'items' && ITEMS.length ? `<span class="count muted">${ITEMS.length}</span>` : ''}</button>`).join('');
        el.innerHTML = `<div class="ap"><div class="ap-h">${ui.appIcon('policy', 'lg')}<div class="grow"><h2>${esc(C.name)}</h2><div class="ap-sum">${esc(C.summary)}</div></div><button class="btn ghost sm" data-act="ask" data-op="policy.ask">${icon('sparkles')}问 AI</button></div>
          <div class="tabs ap-tabs">${tabs}</div><div class="ap-body" id="pb"></div></div>`;
        body();
      }
      function body() {
        const pb = el.querySelector('#pb'); if (!pb) return;
        if (loadErr) { pb.innerHTML = `<div class="err-box">${ui.empty({ icon: 'alert', title: '数据没加载出来', desc: loadErr.message || '请稍后重试', action: '重试' })}</div>`; return; }
        if (!loaded) { pb.innerHTML = '<div class="skel-list"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>'; return; }
        if (S.tab === 'items') return renderItems(pb);
        if (S.tab === 'docs') return renderDocs(pb);
        if (!canOp) { pb.innerHTML = `<div class="callout h-amber">${icon('lock')}<div class="grow">${esc(T.viewOnly)}</div><button class="btn sm" data-tab="items">去事项库</button></div>`; return; }
        pb.innerHTML = stepsBar() + `<div class="wiz-body pol-step" id="ps"></div><div class="wiz-foot" id="pf"></div>`;
        [step0, step1, step2, step3][S.step]();
      }
      function stepsBar() {
        return `<div class="wiz-steps">${C.steps.map((s, i) => `${i ? `<i class="wiz-line ${i <= S.step ? 'done' : ''}"></i>` : ''}<div class="wiz-step ${i === S.step ? 'on' : i < S.step ? 'done' : ''}" ${i < S.step ? `data-step="${i}"` : ''} data-op="policy.step-${i}"><span class="n">${i < S.step ? '✓' : i + 1}</span>${esc(s)}</div>`).join('')}</div>`;
      }
      const $ = (s) => el.querySelector(s);
      const foot = (left, right) => { $('#pf').innerHTML = `${left || ''}<span class="sp"></span>${right || ''}`; };
      const back = () => (S.step > 0 ? `<button class="btn ghost" data-step="${S.step - 1}" data-op="policy.back">上一步</button>` : '');

      /* ---------- 第 1 步：选对象 ---------- */
      function step0() {
        const e = ent();
        $('#ps').innerHTML = `<div class="q">${esc(T.pickQ)}</div><div class="q-sub">${esc(T.pickSub)}</div>
          <div class="seg" style="margin-bottom:var(--s4)"><button class="${S.mode === 'ent' ? 'on' : ''}" data-mode="ent" data-op="policy.mode-ent">从企业台账选</button><button class="${S.mode === 'manual' ? 'on' : ''}" data-mode="manual" data-op="policy.mode-manual">手动描述</button></div>
          ${S.mode === 'ent' ? `<div class="pick"><div class="search">${icon('search')}<input class="input" id="pq" data-op="policy.ent" placeholder="企业名称、简称或信用代码" autocomplete="off" value="${e ? esc(e.short) : ''}"></div><div id="pdd"></div></div>
            ${e ? profileCard(e) : `<div class="sec">常用示例</div><div class="chips">${C.samples.map((id) => ENTS.find((x) => x.id === id)).filter(Boolean).map((e) => `<button class="chip-btn" data-ent="${e.id}" data-op="policy.sample-${e.id}">${esc(e.short)}</button>`).join('')}</div>`}`
          : manualForm()}`;
        foot('', `<button class="btn primary" data-act="run" data-op="policy.go" ${S.mode === 'ent' && !e ? 'disabled' : ''}>开始核对${ITEMS.length ? ` ${ITEMS.length} 项` : ''}</button>`);
        const q = $('#pq'); if (q) { q.oninput = () => showDD(q.value.trim()); q.onfocus = () => showDD(q.value.trim() === (e && e.short) ? '' : q.value.trim()); q.onblur = () => setTimeout(() => { const d = $('#pdd'); if (d) d.innerHTML = ''; }, 200); }
      }
      function showDD(v) {
        const list = ENTS.filter((x) => !v || (x.name + x.short + x.creditCode + x.industry + (x.formerNames || []).join('')).includes(v)).slice(0, 6);
        $('#pdd').innerHTML = `<div class="dd">${list.map((x) => `<div class="mi" data-ent="${x.id}" data-op="policy.opt-${x.id}"><span class="ini h-${ui.hue(x.industry.split(' · ')[0])}">${esc(x.short[0])}</span><div class="grow"><div>${esc(x.short)}</div><div class="meta">${esc(x.industry)} · ${esc(x.creditCode)}</div></div></div>`).join('') || `<div class="meta" style="padding:10px">台账里没有，试试“手动描述”</div>`}</div>`;
      }
      function profileCard(e) {
        const lic = (e.license || []).slice(0, 2).map((l) => tag(l, 'entTag')).join('');
        const amt = Object.entries(e.amounts || {}).filter(([k]) => C.fields[k]).slice(0, 2).map(([k, v]) => `<div><div class="meta">${esc(F(k)[0])}</div><div class="num">${F(k)[2] > 1 ? fmt(v) : v + F(k)[1]}</div></div>`).join('');
        return `<div class="pol-prof" data-op="policy.profile"><div class="row gap3"><span class="ini lg h-${ui.hue(e.industry.split(' · ')[0])}">${esc(e.short[0])}</span><div class="grow"><div class="t-lg" style="font-weight:500">${esc(e.short)}</div><div class="meta">${esc(e.name)}</div></div><button class="btn ghost sm" data-act="clear">换一家</button></div>
          <div class="pol-facts"><div><div class="meta">主体</div><div>${esc(e.subjectType)} · ${esc(e.industry.split(' · ').pop())}</div></div><div><div class="meta">入区经营</div><div class="num">${e.yearsInZone} 年</div></div>${amt}</div>
          ${lic ? `<div class="row wrap" style="margin-top:var(--s3)">${lic}</div>` : ''}</div>`;
      }
      function manualForm() {
        const m = S.manual;
        return `<div class="stack pol-manual">
          <div class="field"><label>对象类型</label><div class="chips">${C.objects.map((o) => `<button class="chip-btn ${m.object === o ? 'on' : ''}" data-mobj="${o}">${esc(o)}</button>`).join('')}</div></div>
          <div class="field"><label>身份 / 经营类型</label><div class="chips">${C.manualTags.map((t) => `<button class="chip-btn ${m.tags.includes(t) ? 'on' : ''}" data-mtag="${esc(t)}" data-op="policy.mtag-${esc(t)}">${esc(t)}</button>`).join('')}</div></div>
          <div class="field"><label>已有资质</label><div class="chips">${C.licenses.map((t) => `<button class="chip-btn ${m.license.includes(t) ? 'on' : ''}" data-mlic="${esc(t)}">${esc(t)}</button>`).join('')}</div></div>
          <div class="grid g2"><div class="field"><label>入区经营年限（年）</label><input class="input" type="number" min="0" step="0.5" data-mnum="yearsInZone" data-op="policy.m-years" value="${esc(m.yearsInZone)}"></div>
          <div class="field"><label>年房租 / 物业费（万元，可不填）</label><input class="input" type="number" min="0" data-mamt="rent" value="${esc(toUnit('rent', m.amounts.rent))}"></div></div></div>`;
      }

      /* ---------- 第 2 步：核对条件 ---------- */
      function who() { const e = ent(); return S.mode === 'ent' && e ? e.short : `${S.manual.object}${S.manual.tags.length ? '（' + S.manual.tags.slice(0, 2).join('、') + '）' : ''}`; }
      function step1() {
        const r = S.match; if (!r) { $('#ps').innerHTML = '<div class="skel-list"><div class="skel"></div><div class="skel"></div></div>'; foot(back(), ''); return; }
        const sm = r.summary; const L = C.levels;
        const grpH = (lv, n) => `<div class="sect pol-gh"><span class="x-ring h-${ui.hue(L[lv][0], 'policyLevel')}"></span>${esc(L[lv][0])}<span class="t-3 num">${n}</span></div>`;
        const kp = (lv, n) => `<button class="kpi-c h-${ui.hue(L[lv][0], 'policyLevel')} ${S.filter === lv ? 'on' : ''}" data-filter="${lv}" data-op="policy.kpi-${lv}"><div class="v num">${n}</div><div class="l">${esc(L[lv][0])}</div></button>`;
        const list = r.results.filter((x) => !S.filter || x.level === S.filter);
        const okCheckAll = list.filter((x) => x.level !== 'no'), no = list.filter((x) => x.level === 'no'); const okCheck = S.showAll ? okCheckAll : okCheckAll.slice(0, 6);
        $('#ps').innerHTML = `<div class="q">${esc(who())}：${sm.ok} 项可核对${sm.check ? `，${sm.check} 项待确认` : ''}</div><div class="q-sub">勾选要告知企业的事项；待确认项补一个数就能重算</div>
          <div class="kpis pol-kpis x-stats">${kp('ok', sm.ok)}${kp('check', sm.check)}${kp('no', sm.no)}</div>
          <div class="pol-groups" id="pres">${!r.results.length ? ui.empty({ icon: 'search', title: T.resultEmpty, desc: T.resultEmptyDesc }) : ['ok', 'check'].map((lv) => { const g = okCheck.filter((x) => x.level === lv); return g.length ? `${grpH(lv, okCheckAll.filter((x) => x.level === lv).length)}<div class="stack rows">${g.map(resCard).join('')}</div>` : ''; }).join('')}${okCheckAll.length > okCheck.length ? `<button class="btn ghost sm pol-more" data-act="showAll" data-op="policy.show-all">再看 ${okCheckAll.length - okCheck.length} 项</button>` : ''}
          ${no.length ? `<details class="pol-no" ${S.filter === 'no' ? 'open' : ''}><summary class="sect" data-op="policy.no-toggle"><span class="x-ring h-${ui.hue(L.no[0], 'policyLevel')}"></span>${esc(L.no[0])}<span class="t-3 num">${no.length}</span><span class="sp"></span><span class="t-3 pol-why-t">看原因</span></summary><div class="stack rows">${no.map(resCard).join('')}</div></details>` : ''}</div>`;
        const pick = chosen();
        foot(back(), `<span class="meta" data-op="policy.selection">已选 ${pick.length} 项 · 默认选中 ${r.defaultItemIds.length} 项 · 本批已结束 ${sm.ended} 项</span><button class="btn primary" data-act="toCalc" data-op="policy.next" ${pick.length ? '' : 'disabled'}>试算额度</button>`);
      }
      function resCard(x) {
        const p = byId(x.id) || {}; const L = C.levels[x.level]; const open = S.open.has(x.id);
        const amount = x.calc ? `<div class="pol-amt num ${x.calc.upTo ? 't-2' : ''}">${x.calc.upTo ? '最高 ' : ''}${fmt(x.calc.amount)}</div>` : p.rule && p.rule.cap ? `<div class="pol-amt num t-2">最高 ${fmt(p.rule.cap)}</div>` : '';
        const unknown = x.checks.map((c, i) => ({ c, cond: (p.conditions || [])[i] })).filter((o) => o.c.state === 'unknown' && o.cond);
        const failed = x.checks.filter((c) => c.state === 'no');
        const hint = x.level === 'no' ? noHint(p, x) : '';
        return `<div class="card tight pol-res lv-${x.level}" data-res="${x.id}">
          <div class="pol-r1">${x.level !== 'no' ? `<input type="checkbox" class="cb pol-ck" data-pick="${x.id}" data-op="policy.pick-${x.id}" ${S.picked.has(x.id) ? 'checked' : ''}>` : ''}
            <div class="grow row-click" data-toggle="${x.id}"><div class="pol-t">${esc(x.title)}</div><div class="meta clip">${esc(refOf({ ...x, docNo: x.doc }))}${x.category ? ' · ' + esc(x.category) : ''}</div></div>
            ${amount}</div>
          ${x.level === 'check' && unknown.length ? `<div class="pol-fill">${unknown.map(({ c, cond }) => fillCtl(x.id, cond, c)).join('')}</div>` : ''}
          ${x.level === 'no' ? `<div class="pol-why">${failed.map((c) => `<span class="pol-x"><span class="ck h-red">✕</span>${esc(c.label)}</span>`).join('')}${hint ? `<div class="meta">${esc(hint)}</div>` : ''}</div>` : ''}
          ${open ? detailFold(x, p) : ''}
          <div class="pol-r2 ${x.level !== 'no' ? 'ind' : ''}">${tag(winOf(p), 'policyWindow')}<span class="sp"></span><button class="link" data-toggle="${x.id}" data-op="policy.more-${x.id}">${open ? '收起' : '条件与时间'}</button><button class="link" data-src="${x.id}" data-op="policy.src-${x.id}">${p.example ? '看示例说明' : '看原文'}</button></div></div>`;
      }
      function fillCtl(id, cond, c) {
        if (cond.trigger && /有相关投入/.test(cond.label || '')) return `<div class="pol-fill-i"><span class="ck h-amber">?</span><span>需人工确认：投入是否属于本事项支持范围</span><button class="link" data-src="${id}">看原文</button></div>`;
        if (cond.f === 'license' || cond.op === 'has') return `<label class="check pol-fill-i"><input type="checkbox" data-lic="${esc([].concat(cond.v)[0])}" data-op="policy.fill-license">${esc(c.label)}？已持有</label>`;
        const f = F(cond.f);
        return `<div class="pol-fill-i"><span class="ck h-amber">?</span><span>缺：${esc(f[0] || c.label)}</span><input class="input sm num" type="number" min="0" data-fill="${cond.f}" data-op="policy.fill-${cond.f}" placeholder="${esc(f[1])}" style="width:110px"><span class="meta">${esc(f[1])}</span><button class="btn sm" data-act="refill" data-op="policy.refill-${cond.f}">重算</button><button class="link" data-sample="${cond.f}">填入示例</button></div>`;
      }
      function noHint(p, x) {
        const c = (p.conditions || []).find((cd, i) => cd.f === 'yearsInZone' && x.checks[i] && x.checks[i].state === 'no');
        const e = ent(); if (!c || !e || !e.established) return '';
        const d = new Date(e.established); d.setFullYear(d.getFullYear() + Math.ceil(c.v)); return `满 ${c.v} 年后（约 ${d.getFullYear()} 年 ${d.getMonth() + 1} 月）可再看`;
      }
      function detailFold(x, p) {
        const t = p.times || {};
        return `<div class="fold stack">${x.checks.map((c) => `<div class="ck-row"><span class="ck h-${c.state === 'ok' ? 'green' : c.state === 'no' ? 'red' : 'amber'}">${c.state === 'ok' ? '✓' : c.state === 'no' ? '✕' : '?'}</span>${esc(c.label)}</div>`).join('')}
          <div class="times"><div><b>政策有效期</b>${esc(t.valid || '—')}</div><div><b>事项发生期</b>${esc(t.occur || '—')}</div><div><b>申报窗口</b>${esc(t.deadlineText || t.window || '—')}</div></div>
          <div class="meta">支持标准：${esc(x.rule || (p.rule && p.rule.text) || '—')}</div>
          ${(x.pending || []).length ? `<div class="meta">尚需确认：${x.pending.map(esc).join('、')}</div>` : ''}${p.versionNote ? `<div class="callout h-amber">${icon('alert')}<div>${esc(p.versionNote)}</div></div>` : ''}</div>`;
      }

      /* ---------- 第 3 步：试算 ---------- */
      const chosen = () => (S.match ? S.match.results.filter((x) => x.level !== 'no' && S.picked.has(x.id)) : []);
      const profile = () => (S.match && S.match.profile) || {};
      const baseAmount = (x) => {
        const base = byId(x.id)?.rule?.base;
        return x.calc?.base ?? (base ? profile()[base] : null);
      };
      function step2() {
        const list = chosen();
        list.forEach((x) => { S.calc[x.id] ??= { amount: baseAmount(x), result: x.calc, edited: false }; });
        $('#ps').innerHTML = `<div class="pol-calc-summary">${calcSummary(list)}</div><div class="q-sub" style="margin-top:4px">各项金额单独列示，叠加规则和实际支持额度以正式审核为准。</div>
          <div class="stack rows">${list.map((x) => calcRow(x)).join('')}</div>`;
        foot(back(), `<button class="btn primary" data-act="toNotice" data-op="policy.to-notice">生成告知单</button>`);
      }
      function calcSummary(list) {
        const ratios = list.map((x) => S.calc[x.id]?.result).filter((r) => r?.kind === 'ratio');
        const summary = ratios.length === 1 ? fmt(ratios[0].amount) : `${ratios.length} 项`;
        return `<div class="q">${ratios.length === 1 ? '按比例试算金额' : '已按比例试算'}</div><div class="big pol-total num" data-op="policy.total">${summary}</div>`;
      }
      function calcRow(x) {
        const p = byId(x.id) || {}; const base = p.rule && p.rule.base; const c = S.calc[x.id] || {}; const r = c.result;
        return `<div class="card tight pol-calc"><div class="grow pol-cl"><div class="pol-t">${esc(x.title)} ${exampleTag(p)}</div><div class="meta clip" title="${esc(p.rule ? p.rule.text : '')}">${esc(p.rule ? p.rule.text : '')}</div><div class="pol-calc-text">${calcResultText(r)}</div></div>
          ${base ? `<div class="field pol-cf"><label class="meta">${esc(F(base)[0])}（${esc(F(base)[1])}）</label><input class="input sm num" type="number" min="0" data-camt="${x.id}" data-op="policy.calc-${x.id}" value="${esc(toUnit(base, c.amount))}"></div>` : ''}
          <div class="pol-amt pol-ca num">${calcResultAmount(p, r)}</div></div>`;
      }
      const calcResultText = (r) => r && r.kind !== 'fixed' ? `<div class="t-sm t-2 num" style="margin-top:4px">${esc(r.text)} ${r.capped ? tag('已按封顶', 'status', { cls: 'plain' }) : ''}</div>` : '';
      const calcResultAmount = (p, r) => r ? (r.upTo ? '<span class="meta">最高</span> ' : '') + fmt(r.amount) : p.rule?.manual ? '<span class="meta">需人工核对</span>' : '<span class="meta">经评审确定</span>';
      function setCalcAmount(input) {
        const id = input.dataset.camt;
        const base = byId(id).rule.base;
        const amount = input.valueAsNumber > 0 ? input.valueAsNumber * F(base)[2] : null;
        S.calc[id] = { amount, result: null, edited: true };
      }
      async function recalc(id) {
        const calc = S.calc[id];
        try {
          const result = calc.amount == null ? null : (await P.calc({ itemId: id, amount: calc.amount })).result;
          if (S.calc[id] !== calc) return;
          calc.result = result;
          if (S.tab !== 'flow' || S.step !== 2) return;
          const row = $(`[data-camt="${id}"]`)?.closest('.pol-calc');
          if (!row) return;
          row.querySelector('.pol-calc-text').innerHTML = calcResultText(result);
          row.querySelector('.pol-ca').innerHTML = calcResultAmount(byId(id), result);
          $('.pol-calc-summary').innerHTML = calcSummary(chosen());
        } catch (e) {
          if (S.calc[id] === calc) ui.toast(e.message || '试算失败', { type: 'err' });
        }
      }

      /* ---------- 第 4 步：告知单 ---------- */
      async function showNotice() {
        if (!chosen().length || S.busy) return;
        const match = S.match, step = S.step;
        const list = chosen();
        const inputs = list.map((x) => [x, S.calc[x.id]]);
        const amounts = Object.fromEntries(inputs.map(([x, calc]) => [
          x.id, calc ? calc.amount : x.calc?.base ?? null,
        ]));
        S.busy = true;
        try {
          const { text } = await P.notice({ entId: S.mode === 'ent' ? S.entId : undefined, itemIds: list.map((x) => x.id), amounts });
          if (S.match !== match || S.step !== step) return;
          if (inputs.some(([x, calc]) => S.calc[x.id] !== calc)) return;
          S.notice = text;
          S.step = 3;
          if (S.tab === 'flow') body();
        } catch (e) {
          ui.toast(e.message || '生成告知单失败', { type: 'err' });
        } finally {
          S.busy = false;
        }
      }
      function step3() {
        const e = ent();
        $('#ps').innerHTML = `<div class="q">告知单已生成</div><div class="q-sub">可直接修改，复制后发给企业</div>
          <textarea class="textarea pol-notice" id="pn" data-op="policy.notice-text" spellcheck="false">${esc(S.notice)}</textarea>
          <div class="row wrap" style="margin-top:var(--s3)"><button class="btn sm" data-act="download" data-op="policy.download">${icon('download')}下载</button><button class="btn sm" data-act="toDoc" data-op="policy.to-doc">${icon('doc')}转为公文答复</button>
          ${e && S.mode === 'ent' ? `<button class="btn sm" data-act="issue" data-op="policy.issue">${icon('flag')}记入企业诉求</button>` : ''}<button class="btn sm ghost" data-act="skill" data-op="policy.skill">${icon('skill')}存为技能</button></div>`;
        $('#pn').oninput = (ev) => (S.notice = ev.target.value);
        foot(back(), `<button class="btn primary" data-act="copy" data-op="policy.copy">${icon('copy')}复制告知单</button>`);
      }

      /* ---------- 事项库 ---------- */
      function renderItems(pb) {
        const q = S.q.trim();
        const list = ITEMS.filter((p) => (!S.obj || p.object === S.obj) && (!S.win || winOf(p) === S.win) && (!q || (p.title + (p.keywords || []).join('') + (p.sub || '') + (p.original || '') + (p.docNo || '')).includes(q)));
        pb.innerHTML = `<div class="row gap3 wrap pol-filt" style="margin-bottom:var(--s4)"><div class="search grow">${icon('search')}<input class="input" id="iq" data-op="policy.items-q" placeholder="说法也能搜：买数据、房租、首店…" value="${esc(S.q)}"></div>
          <div class="seg">${['', ...C.objects].map((o) => `<button class="${S.obj === o ? 'on' : ''}" data-obj="${o}" data-op="policy.obj-${o || 'all'}">${o || '全部'}</button>`).join('')}</div>
          <select class="select" style="width:130px" id="iw" data-op="policy.items-win"><option value="">全部窗口</option>${Object.values(C.windowText).map((w) => `<option ${S.win === w ? 'selected' : ''}>${w}</option>`).join('')}</select></div>
          <div class="meta" style="margin-bottom:var(--s2)">${list.length} 项</div>
          ${list.length ? `<div class="card flat"><div class="list lined">${list.map((p) => `<div class="li" data-detail="${p.id}" data-op="policy.item-${p.id}"><div class="grow"><div class="ttl clip">${esc(p.title)}</div><div class="meta clip">${esc(p.sub || '')} · ${esc(p.rule ? p.rule.text : '')}</div></div><span class="pol-tg">${exampleTag(p)}${tag(p.object, 'policyObj', { cls: 'plain' })}${tag(winOf(p), 'policyWindow')}</span><span class="t-3">${icon('chevron-right')}</span></div>`).join('')}</div></div>` : ui.empty({ icon: 'search', title: '没有找到事项', desc: '换个说法，或清空筛选', action: '清空筛选' })}`;
        const iq = pb.querySelector('#iq'); let tm; iq.oninput = () => { clearTimeout(tm); tm = setTimeout(() => { S.q = iq.value; body(); const n = el.querySelector('#iq'); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 220); };
        pb.querySelector('#iw').onchange = (ev) => { S.win = ev.target.value; body(); };
      }
      function renderDocs(pb) {
        pb.innerHTML = DOCS.length ? `<div class="card flat"><div class="list lined">${DOCS.map((d) => { const n = ITEMS.filter((p) => p.doc === d.id).length; return `<div class="li" data-doc="${d.id}" data-op="policy.doc-${d.id}"><span class="t-3">${icon('file')}</span><div class="grow"><div class="ttl clamp2">${esc(d.title)}</div><div class="meta">${esc(d.no || '')}${d.year ? ' · ' + d.year : ''} · 拆出 ${n} 项</div></div>${tag(d.state || '现行有效', 'status', { cls: 'plain' })}${d.url ? `<a class="btn ghost icon sm" href="${esc(d.url)}" target="_blank" rel="noopener" title="官网原文">${icon('external')}</a>` : ''}</div>`; }).join('')}</div></div>` : ui.empty({ icon: 'file', title: '还没有政策文件', desc: '把政策文件拖进对话框，会自动入库并拆出事项' });
      }

      /* ---------- 抽屉：原文 / 事项详情 / 试算器 ---------- */
      async function openSource(id) {
        const p = byId(id); if (!p) return; const d = docOf(p); const u = srcUrl(p);
        const dr = ui.drawer({ title: p.example ? '示例说明' : '原文依据', body: `<div class="stack app-policy">
          <div><div class="t-lg" style="font-weight:500">${esc(p.docTitle || d.title || '')}</div><div class="meta">${esc(refOf(p) || '无文号')}</div></div>
          <div class="row wrap">${p.example ? exampleTag(p) : tag(p.docState || d.state || '有效状态待核实', 'status')}${p.verifiedAt ? `<span class="meta">核验 ${esc(p.verifiedAt)}</span>` : ''}</div>
          <div class="quote"><mark>${esc(p.original || '')}</mark></div>
          ${p.versionNote ? `<div class="callout h-amber">${icon('alert')}<div>${esc(p.versionNote)}</div></div>` : ''}
          ${u ? `<a class="btn sm" href="${esc(u)}" target="_blank" rel="noopener">${icon('external')}打开官网原文</a>` : ''}
          ${p.example ? '' : '<div class="sec">知识库里的相关内容</div><div id="kbrel" class="stack"><div class="skel"></div></div>'}</div>`, width: 520 });
        if (p.example) return;
        try {
          const r = await ctx.kb.search(`${p.title} ${p.docNo || ''}`, { space: 'policy', limit: 3 });
          const box = dr.el.querySelector('#kbrel'); const hits = (r.hits || []).slice(0, 3);
          box.innerHTML = hits.length ? hits.map((h) => `<div class="src" data-kb="${esc(h.id)}"><span class="t-3">${icon('book')}</span><div class="grow"><div class="clip">${esc(h.title)}</div><div class="meta clamp2">${esc(h.snippet || '')}</div></div></div>`).join('') : '<div class="meta">暂无</div>';
          box.querySelectorAll('[data-kb]').forEach((n) => (n.onclick = () => ctx.kb.open(n.dataset.kb, { highlight: p.original })));
        } catch (e) { const box = dr.el.querySelector('#kbrel'); if (box) box.innerHTML = '<div class="meta">知识库暂不可用</div>'; }
      }
      function openDetail(id) {
        const p = byId(id); if (!p) return; const t = p.times || {};
        const dr = ui.drawer({ title: p.title, body: `<div class="stack app-policy">
          <div class="row wrap">${tag(p.object, 'policyObj')}${tag(winOf(p), 'policyWindow')}${exampleTag(p)}${p.sub ? `<span class="meta">${esc(p.sub)}</span>` : ''}</div>
          <div><div class="meta">支持标准</div><div class="t-lg" style="font-weight:500">${esc(p.rule ? p.rule.text : '—')}</div></div>
          <div><div class="sec" style="margin-top:0">条件</div>${(p.conditions || []).map((c) => `<div class="ck-row"><span class="ck h-gray">·</span>${esc(c.label)}</div>`).join('')}</div>
          <div class="times"><div><b>政策有效期</b>${esc(t.valid || '—')}</div><div><b>事项发生期</b>${esc(t.occur || '—')}</div><div><b>申报窗口</b>${esc(t.window || '—')}</div></div>
          ${(p.materials || []).length ? `<div><div class="sec">材料</div><div class="meta">${p.materials.map(esc).join('、')}</div></div>` : ''}
          ${(p.pending || []).length ? `<div><div class="sec">尚需确认</div><div class="meta">${p.pending.map(esc).join('、')}</div></div>` : ''}
          ${p.subjectRole ? `<div class="meta">申请主体：${esc(p.subjectRole)}</div>` : ''}
          ${(p.keywords || []).length ? `<div class="meta">也能这样搜：${p.keywords.map(esc).join('、')}</div>` : ''}
          <div class="row wrap"><button class="btn sm primary" data-d="src">${p.example ? '看示例说明' : '看原文'}</button>${p.rule?.base ? `<button class="btn sm" data-d="calc">${p.times?.open === false ? '回顾试算' : '试算'}</button>` : ''}${canOp && p.times?.open !== false ? '<button class="btn sm" data-d="draft">起草申报通知</button>' : ''}</div></div>`, width: 520 });
        dr.el.querySelectorAll('[data-d]').forEach((b) => (b.onclick = () => { const a = b.dataset.d; dr.close(); if (a === 'src') openSource(id); if (a === 'calc') calcModal(id); if (a === 'draft') ctx.nav.open('document', 'new', { from: 'policy', templateId: 'T03', inputs: { policy: id } }); }));
        return dr;
      }
      function calcModal(id, amountYuan) {
        const list = ITEMS.filter((p) => p.rule?.base);
        const cur = id || list[0]?.id;
        if (!list.some((p) => p.id === cur)) return;
        const m = ui.modal({ title: '额度试算', ok: false, body: `<div class="stack app-policy"><div class="field"><label>事项</label><select class="select" id="cp" data-op="policy.cm-item">${list.map((p) => `<option value="${p.id}" ${p.id === cur ? 'selected' : ''}>${esc(p.title)}${p.example ? ' · ' + esc(T.demoBadge) : ''}</option>`).join('')}</select></div>
          <div class="field"><label id="cl"></label><input class="input num" type="number" min="0" id="ca" data-op="policy.cm-amount"></div><div class="meta" id="crule"></div>
          <div class="pol-cm"><div class="big num" id="cres" data-op="policy.cm-result">—</div><div class="meta" id="ctext"></div></div></div>` });
        const box = m.el; const sel = box.querySelector('#cp'), inp = box.querySelector('#ca');
        const sync = async () => { const p = byId(sel.value); const f = F(p.rule.base); box.querySelector('#cl').textContent = `${f[0]}（${f[1]}）`; box.querySelector('#crule').textContent = p.rule.text; const v = +inp.value; if (!v) { box.querySelector('#cres').textContent = '—'; box.querySelector('#ctext').textContent = ''; return; } const r = await P.calc({ itemId: p.id, amount: v * f[2] }); box.querySelector('#cres').textContent = r.result ? fmt(r.result.amount) : '—'; box.querySelector('#ctext').textContent = r.result ? `${r.result.text}${r.result.capped ? '（已按封顶）' : ''} · ${r.note}` : ''; m.last = r; };
        sel.onchange = sync; let tm; inp.oninput = () => { clearTimeout(tm); tm = setTimeout(sync, 150); };
        if (amountYuan) inp.value = toUnit(byId(cur).rule.base, amountYuan); sync();
        return m;
      }

      /* ---------- 业务动作 ---------- */
      function normalizeMatch(response) {
        const results = response.results.map((result) => ({
          ...result,
          ended: result.ended ?? ((result.open ?? byId(result.id)?.times?.open) === false),
        }));
        const applicable = results.filter((x) => x.level !== 'no');
        const eligible = applicable.filter((x) => !x.ended);
        const ok = eligible.filter((x) => x.level === 'ok');
        return {
          ...response,
          results,
          total: response.total ?? ITEMS.length,
          summary: { ...response.summary, ended: response.summary.ended ?? applicable.length - eligible.length },
          defaultItemIds: response.defaultItemIds ?? (ok.length ? ok : eligible.slice(0, 2)).map((x) => x.id),
        };
      }
      async function runMatch() {
        S.busy = true; S.match = null; S.step = 1; S.showAll = false; S.calc = {}; S.notice = ''; S.filter = null; body();
        try {
          let b;
          if (S.mode === 'ent') b = { entId: S.entId, overrides: S.overrides };
          else { const m = S.manual; b = { profile: Object.assign({ subjectType: m.object === '其他组织' ? '其他组织' : m.object, tags: [...m.tags], license: [...m.license], regInZone: true }, m.yearsInZone !== '' ? { yearsInZone: +m.yearsInZone } : {}, m.amounts, S.overrides) }; }
          S.match = normalizeMatch(await P.match(b));
          S.picked = new Set(S.match.defaultItemIds);
        } catch (e) { ui.toast(e.message || '匹配失败', { type: 'err' }); S.step = 0; }
        S.busy = false; if (S.tab === 'flow') body(); return S.match;
      }
      async function applyFill(field, unitVal) {
        if (field === 'license') { S.overrides.license = [...new Set([...(S.overrides.license || []), unitVal])]; }
        else S.overrides[field] = +unitVal * F(field)[2];
        await runMatch(); ui.toast('已补充并重新核对');
      }
      async function copyNotice() { try { await navigator.clipboard.writeText(S.notice); } catch (e) { /* file:// 下可能无权限 */ } ui.toast('告知单已复制'); }
      function toDocument() {
        const e = ent(); const ids = chosen().map((x) => x.id);
        ctx.nav.open('document', 'new', { from: 'policy', templateId: 'T10', inputs: { ent: e ? e.id : '', policy: ids[0] || '', issue: `咨询${ids.length ? byId(ids[0]).title : '政策'}申报` }, notice: S.notice });
      }
      async function logIssue() {
        const e = ent(); if (!e) return;
        try { await E.createIssue({ entId: e.id, title: `政策咨询：${chosen().map((x) => x.title).slice(0, 2).join('、') || '兑现事项'}`, from: '政策咨询', next: '跟进申报批次通知' }); ctx.bus.emit('inbox:changed'); ui.toast('已记入企业诉求', { action: { label: '查看', fn: () => ctx.nav.open('enterprise', 'issues', { entId: e.id }) } }); }
        catch (err) { ui.toast(err.message || '没有权限', { type: 'err' }); }
      }
      function resolveEnt(slot, text) {
        if (slot && typeof slot === 'object' && slot.id) return slot.id;
        const s = String(slot || text || '');
        const hit = ENTS.find((e) => (e.name && s.includes(e.name)) || (e.short && s.includes(e.short)));
        if (hit) return hit.id;
        const partial = ENTS.filter((e) => s && (e.short?.includes(s) || (e.short?.length >= 3 && s.includes(e.short.slice(0, 3)))));
        return partial.length === 1 ? partial[0].id : null;
      }
      function resolvePolicy(slot, text) {
        if (slot && typeof slot === 'object' && slot.id) return slot.id;
        const s = String(slot || text || '');
        let best = null, sc = 0; ITEMS.forEach((p) => { let n = 0; if (s.includes(p.title)) n += 10; (p.keywords || []).forEach((k) => { if (s.includes(k)) n += 3; }); if (p.sub && s.includes(p.sub)) n += 3; [...p.title].forEach((ch) => { if (s.includes(ch)) n += 0.2; }); if (n > sc) { sc = n; best = p; } });
        return sc >= 2 ? best.id : null;
      }
      const ready = async () => { for (let i = 0; i < 60 && !loaded; i++) await new Promise((r) => setTimeout(r, 50)); };

      /* ---------- 事件 ---------- */
      el.addEventListener('click', async (ev) => {
        const t = ev.target.closest('[data-tab],[data-step],[data-mode],[data-ent],[data-act],[data-filter],[data-toggle],[data-src],[data-detail],[data-doc],[data-obj],[data-mobj],[data-mtag],[data-mlic],[data-sample],[data-empty-action]');
        if (!t) return; const d = t.dataset;
        if (d.tab) { S.tab = d.tab; render(); return; }
        if (d.step != null && !t.disabled) { S.step = +d.step; body(); return; }
        if (d.mode) { S.mode = d.mode; body(); return; }
        if (d.ent) { S.entId = d.ent; S.overrides = {}; S.match = null; body(); return; }
        if (d.filter) { S.filter = S.filter === d.filter ? null : d.filter; body(); return; }
        if (d.toggle) { S.open.has(d.toggle) ? S.open.delete(d.toggle) : S.open.add(d.toggle); body(); return; }
        if (d.src) return openSource(d.src);
        if (d.detail) return openDetail(d.detail);
        if (d.doc) { const r = await ctx.kb.search(DOCS.find((x) => x.id === d.doc).title, { space: 'policy', limit: 1 }).catch(() => ({ hits: [] })); if (r.hits && r.hits[0]) ctx.kb.open(r.hits[0].id); else ui.toast('知识库里还没有这份文件'); return; }
        if (d.obj != null && t.closest('.seg')) { S.obj = d.obj; body(); return; }
        if (d.mobj) { S.manual.object = d.mobj; body(); return; }
        if (d.mtag) { const a = S.manual.tags; a.includes(d.mtag) ? a.splice(a.indexOf(d.mtag), 1) : a.push(d.mtag); body(); return; }
        if (d.mlic) { const a = S.manual.license; a.includes(d.mlic) ? a.splice(a.indexOf(d.mlic), 1) : a.push(d.mlic); body(); return; }
        if (d.sample) { const inp = t.parentElement.querySelector('[data-fill]'); if (inp) inp.value = toUnit(d.sample, C.sampleFill[d.sample] || 10 * F(d.sample)[2]); return; }
        if (d.emptyAction != null) { if (loadErr) { loaded = false; body(); load(); } else { S.q = ''; S.obj = ''; S.win = ''; body(); } return; }
        const a = d.act;
        if (a === 'ask') return ctx.nav.chat(ent() ? `${ent().short}能申请哪些支持？` : '实体书店房租补贴的条件是什么？');
        if (a === 'clear') { S.entId = null; S.match = null; body(); setTimeout(() => { const q = el.querySelector('#pq'); q && q.focus(); }, 0); return; }
        if (a === 'run') return runMatch();
        if (a === 'refill') { const inp = t.parentElement.querySelector('[data-fill]'); if (!inp.value) { ui.toast('先填一个数', { type: 'warn' }); return; } return applyFill(inp.dataset.fill, inp.value); }
        if (a === 'showAll') { S.showAll = true; body(); return; }
        if (a === 'toCalc') { S.step = 2; body(); return; }
        if (a === 'toNotice') return showNotice();
        if (a === 'copy') return copyNotice();
        if (a === 'download') return ui.download(`政策告知单-${who()}.txt`, S.notice);
        if (a === 'toDoc') return toDocument();
        if (a === 'issue') return logIssue();
        if (a === 'skill') return ctx.nav.open('skills', 'build', { from: 'policy', prompt: `做一个“${ent() ? ent().industry.split(' · ').pop() : S.manual.tags[0] || '企业'}政策预判”技能：按企业画像核对兑现事项，给出可核对/待确认/不满足和告知单` });
      });
      el.addEventListener('change', async (ev) => {
        const t = ev.target; const d = t.dataset;
        if (d.pick) { t.checked ? S.picked.add(d.pick) : S.picked.delete(d.pick); delete S.calc[d.pick]; body(); return; }
        if (d.lic) { if (t.checked) applyFill('license', d.lic); return; }
        if (d.camt) { if (S.calc[d.camt]?.edited) await recalc(d.camt); return; }
        if (d.mnum) { S.manual[d.mnum] = t.value; return; }
        if (d.mamt) { if (t.value === '') delete S.manual.amounts[d.mamt]; else S.manual.amounts[d.mamt] = +t.value * F(d.mamt)[2]; return; }
      });
      el.addEventListener('input', (ev) => { if (ev.target.dataset.camt) setCalcAmount(ev.target); });
      el.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' && ev.target.dataset.fill) { const b = ev.target.parentElement.querySelector('[data-act=refill]'); b && b.click(); } });

      load();

      /* ---------- 对外：go + actions（操作员按 data-op 驱动可见界面） ---------- */
      const gotoTab = (k) => { if (S.tab !== k) { S.tab = k; render(); } };
      const actions = {
        async match({ ent: es, text } = {}, run) {
          await ready(); const id = resolveEnt(es, text);
          if (!id) { run && run.fail('没认出是哪家企业，请说出企业名称'); return; }
          if (!canOp) { run && run.fail(T.viewOnly); return; }
          gotoTab('flow'); S.step = 0; S.mode = 'ent'; S.entId = null; S.match = null; S.overrides = {}; body();
          const e = ENTS.find((x) => x.id === id);
          if (run) { await run.step(1); await run.fill('[data-op="policy.ent"]', e.short); await run.wait(`[data-op="policy.opt-${id}"]`); await run.click(`[data-op="policy.opt-${id}"]`); await run.step(2); await run.click('[data-op="policy.go"]'); await run.wait(() => S.match && el.querySelector('[data-op="policy.kpi-ok"]')); await run.step(3); await run.highlight('[data-op="policy.kpi-ok"]'); }
          else { S.entId = id; await runMatch(); }
          if (!S.match) return;
          const sm = S.match.summary; const firstCheck = S.match.results.find((x) => x.level === 'check');
          run && run.done(`${e.short}：核对 ${S.match.total} 项事项，${sm.ok} 项可进一步核对${sm.check ? `，${sm.check} 项待确认` : ''}${sm.no ? `，${sm.no} 项不满足` : ''}。默认选中 ${S.match.defaultItemIds.length} 项，本批已结束 ${sm.ended} 项。`, [...(firstCheck ? [{ label: '补填缺的信息', say: '补填数据采购额 30 万' }] : []), { label: '生成告知单', say: `给${e.short}生成政策告知单` }, { label: '起草答复函', say: '把告知单转成公文答复' }]);
          return S.match;
        },
        async fill({ amount, field, value, text } = {}, run) {
          await ready(); if (!S.match) { run && run.fail('先做一次匹配'); return; }
          gotoTab('flow'); if (S.step !== 1) { S.step = 1; body(); }
          let inp = field ? el.querySelector(`[data-fill="${field}"]`) : null;
          if (!inp) { const all = [...el.querySelectorAll('[data-fill]')]; inp = all.find((i) => (text || '').includes(F(i.dataset.fill)[0].slice(0, 2))) || all[0]; }
          if (!inp) {
            const fk = field || Object.keys(C.fields).find((k) => (text || '').includes(F(k)[0].replace(/\s/g, '').slice(0, 4)) || (text || '').includes(F(k)[0].slice(0, 2) + '采购'));
            const vv = value != null ? value : amount != null && fk ? amount / F(fk)[2] : (/(\d+(?:\.\d+)?)\s*万?/.exec(text || '') || [])[1];
            if (!fk || vv == null) { run && run.fail('这次结果里没有需要补数的待确认项'); return; }
            if (run) await run.step(1); await applyFill(fk, vv); if (run) { await run.step(2); await run.highlight('[data-op="policy.kpi-ok"]'); }
            const sm2 = S.match.summary; run && run.done(`已把 ${F(fk)[0]} ${vv}${F(fk)[1]} 记入画像并重新核对：${sm2.ok} 项可核对，${sm2.check} 项待确认`, [{ label: '试算额度', say: '试算一下能拿多少' }]); return;
          }
          const f = inp.dataset.fill; let v = value != null ? value : amount != null ? amount / F(f)[2] : (/(\d+(?:\.\d+)?)\s*万?/.exec(text || '') || [])[1];
          if (v == null) v = toUnit(f, C.sampleFill[f]);
          if (run) { await run.step(1); await run.fill(`[data-op="policy.fill-${f}"]`, String(v)); await run.step(2); await run.click(`[data-op="policy.refill-${f}"]`); await run.wait(() => S.match && !S.busy && el.querySelector('[data-op="policy.kpi-ok"]')); }
          else await applyFill(f, v);
          const sm = S.match.summary; run && run.done(`已补 ${F(f)[0]} ${v}${F(f)[1]}，重新核对：${sm.ok} 项可核对，${sm.check} 项待确认`, [{ label: '试算额度', say: '试算一下能拿多少' }]);
        },
        async calc({ amount, policy, text } = {}, run) {
          await ready();
          if (amount == null) { const mm = /(\d+(?:\.\d+)?)\s*万/.exec(text || ''); if (mm) amount = +mm[1] * 1e4; }
          if (S.match && !policy && !amount) { gotoTab('flow'); if (run) { await run.click('[data-op="policy.next"]'); await run.wait('[data-op="policy.total"]'); await run.highlight('[data-op="policy.total"]'); run.done('已按事项分别列出试算参考和支持标准', [{ label: '生成告知单', say: '生成一次性告知单' }]); } else { S.step = 2; body(); } return; }
          const id = resolvePolicy(policy, text) || (ITEMS.find((p) => p.rule && p.rule.base) || {}).id;
          let amt = amount; if (amt == null) { const m = /(\d+(?:\.\d+)?)\s*万/.exec(text || ''); if (m) amt = +m[1] * 1e4; }
          const m = calcModal(id); if (!m) { run && run.fail('该事项需按原文人工核对金额'); return; }
          if (run) { await run.step(1); await run.select('[data-op="policy.cm-item"]', id); await run.step(2); if (amt) await run.fill('[data-op="policy.cm-amount"]', String(toUnit(byId(id).rule.base, amt))); await run.wait(() => m.last || !amt, 4000); await run.step(3); await run.highlight('[data-op="policy.cm-result"]'); const r = m.last && m.last.result; run.done(r ? `${byId(id).title}：${r.text}。试算参考金额 ${fmt(r.amount)}。 ${m.last.note}` : '请输入金额', [{ label: '看原文', say: `${byId(id).title}的条件是什么` }]); }
          return m;
        },
        async notice({ ent: es, text } = {}, run) {
          await ready(); const id = resolveEnt(es, text) || S.entId;
          if (!S.match || (id && id !== S.entId)) { if (!id) { run && run.fail('要给哪家企业生成？'); return; } await actions.match({ ent: { id } }, run ? Object.assign(Object.create(run), { done() {} }) : null); }
          if (!chosen().length) { run && run.fail('请先勾选要告知的事项'); return; }
          gotoTab('flow');
          if (run) { await run.step(1); if (S.step < 2) { await run.click('[data-op="policy.next"]'); await run.wait('[data-op="policy.to-notice"]'); } await run.step(2); if (S.step === 2) await run.click('[data-op="policy.to-notice"]'); await run.wait('[data-op="policy.notice-text"]'); await run.step(3); await run.highlight('[data-op="policy.copy"]', '确认无误后复制给企业'); run.done(`告知单已生成（${chosen().length} 项），确认后点“复制告知单”`, [{ label: '转为公文答复', say: '把告知单转成公文答复' }, { label: '记入企业诉求', say: '把这次咨询记入企业诉求' }]); }
          else await showNotice();
          return S.notice;
        },
        async detail({ policy, text } = {}, run) {
          await ready(); const id = resolvePolicy(policy, text); if (!id) { run && run.fail('没找到对应的事项，可以换个说法'); return; }
          gotoTab('items'); if (run) { await run.step(1); await run.fill('[data-op="policy.items-q"]', byId(id).title.slice(0, 4)); await new Promise((r) => setTimeout(r, 300)); await run.wait(`[data-op="policy.item-${id}"]`); await run.step(2); await run.click(`[data-op="policy.item-${id}"]`); const p = byId(id); run.done(`${p.title}${p.example ? ' · ' + T.demoBadge : ''}：${(p.conditions || []).map((c) => c.label).join('；')}。标准：${p.rule.text}`, p.example ? [] : [{ label: '看原文', say: '看原文' }]); }
          else openDetail(id);
        },
        async items({ q, object, text } = {}, run) {
          await ready(); gotoTab('items'); const obj = object || C.objects.find((o) => (text || '').includes(o)) || '';
          if (run) { await run.step(1); if (obj) await run.click(`[data-op="policy.obj-${obj}"]`); if (q) await run.fill('[data-op="policy.items-q"]', q); run.done(`事项库：${el.querySelectorAll('[data-detail]').length} 项`); }
          else { S.obj = obj; S.q = q || ''; body(); }
        },
        async toDocument(a, run) { if (!chosen().length) { run && run.fail('请先勾选要告知的事项'); return; } if (S.step !== 3) await showNotice(); if (S.step !== 3) return; if (run) { gotoTab('flow'); await run.click('[data-op="policy.to-doc"]'); run.done('已带上企业和政策依据，打开公文协作（答复意见）'); } else toDocument(); },
        async logIssue(a, run) { if (run) { gotoTab('flow'); if (S.step !== 3) await showNotice(); if (S.step !== 3) return; await run.click('[data-op="policy.issue"]'); run.done('已记入企业诉求'); } else logIssue(); },
        async intake({ file } = {}, run) {
          await ready(); gotoTab('docs');
          let n = 0; try { const r = await ctx.kb.import([file], { space: 'policy', from: '政策匹配' }); n = (r.docs || []).length; } catch (e) { /* 知识库不可用时只提示 */ }
          ui.toast(n ? `「${file.name}」已存入知识库 · 政策文件` : `已收到「${file.name}」`);
          run && run.done(`这是一份政策文件，已存入知识库“政策文件”。可以直接问：“这份文件里企业能申请什么？”`, [{ label: '在知识库里问', say: `${file.name.replace(/\.\w+$/, '')}里企业能申请什么支持？` }, { label: '查看事项库', say: '打开政策事项库' }]);
        },
      };
      return {
        go(route, params = {}) {
          ready().then(() => {
            if (route === 'items' || route === 'docs') { S.tab = route; if (params.q != null) S.q = params.q; if (params.object != null) S.obj = params.object; render(); return; }
            if (route === 'detail') { S.tab = 'items'; render(); openDetail(params.itemId || params.id); return; }
            S.tab = 'flow';
            if (params.entId && params.entId !== S.entId) { S.entId = params.entId; S.mode = 'ent'; S.overrides = {}; S.match = null; }
            if (route === 'calc' && params.itemId) { render(); calcModal(params.itemId, params.amount); return; }
            render();
            if ((route === 'match' || route === 'notice' || params.run) && S.entId && canOp) runMatch().then(() => { if (route === 'notice') return showNotice(); });
          });
        },
        getCalcAmounts() {
          return Object.fromEntries(Object.entries(S.calc).filter(([, entry]) => entry.edited).map(([id, entry]) => [id, entry.amount]));
        },
        async restoreCalcAmounts(amounts) {
          for (const { id } of chosen()) {
            if (!Object.hasOwn(amounts, id) || !byId(id)?.rule?.base) continue;
            S.calc[id] = { amount: amounts[id], result: null, edited: true };
            await recalc(id);
          }
        },
        actions,
        unmount() {},
      };
    },
  });
})();

/* 企业管理（app id: enterprise）· v4 综合版
 * 合并：v2 四步向导（找企业→一企一档→记走访→跟诉求）+ 原值→新值→原话依据 + 语音输入；v3 顶部三张提醒卡 + 台账筛选；v1 30 秒速览 + CSV 导出
 * 人把关点：台账写入（AI 只给建议，逐条/批量确认后才写）。外部协作者：后端打码，前端隐藏写操作。 */
(function () {
  const DEF = { name: '企业管理', summary: '走访前看懂企业，走访后更新台账', steps: ['找企业', '一企一档', '记走访', '跟诉求'], tabs: [['flow', '办理'], ['list', '台账'], ['board', '诉求看板']], profileTabs: [['base', '概况'], ['biz', '经营与资质'], ['visit', '走访与诉求'], ['history', '变更历史']], visitTypes: ['上门走访'], issueStatuses: ['待分派', '办理中', '待补材料', '已办结'], visitSamples: { _default: '' }, importSample: [], importMap: [], staleDays: 90, text: {} };
  const C = Object.assign({}, DEF, (window.JK_APPCFG || {}).enterprise || {});
  const T = Object.assign({ findQ: '找哪家企业？', findSub: '', visitQ: '这次走访聊了什么？', visitSub: '', partner: '外部协作者视图', noWrite: 'AI 不直接改台账' }, C.text);

  JK.registerApp({
    manifest: {
      id: 'enterprise', name: C.name, short: '企业', icon: 'building', hue: 'teal', version: '4.0.0', owner: 'AI 工作组',
      summary: C.summary, routes: ['flow', 'detail', 'visit', 'issues', 'list', 'board'],
      perms: { view: '查企业、看档案', operate: '记走访、确认写入、跟诉求', approve: '—' },
      tools: [
        { name: 'enterprise.search', desc: '按名称/标签查企业', params: { q: 'string' } },
        { name: 'enterprise.get', desc: '一企一档 + 30 秒速览', params: { id: 'string' } },
        { name: 'enterprise.propose_update', desc: '从走访记录提取台账更新建议（不直接写）', params: { id: 'string', notes: 'string' } },
        { name: 'enterprise.alerts', desc: '资质到期 / 久未走访 / 诉求临期', params: {} },
      ],
      accepts: [{ kind: '企业资料', ext: ['xlsx', 'xls', 'csv', 'pdf', 'doc', 'docx', 'txt', 'jpg', 'png'], match: /企业|台账|走访|名单|营业执照|公司|有限/ }],
      intents: [
        { id: 'enterprise.find', action: 'find', examples: ['查一下星河智驾', '打开书香里文化的一企一档', '星河智驾走访前摘要'], keywords: ['查一下', '一企一档', '档案', '摘要', '企业情况'], slots: { ent: 'enterprise' }, plan: ['打开企业管理', '找到企业', '打开一企一档', '生成 30 秒速览'] },
        { id: 'enterprise.visit', action: 'visit', examples: ['给书香里加一条走访记录', '记一次走访', '整理书香里的走访'], keywords: ['走访', '记录走访', '拜访'], slots: { ent: 'enterprise' }, plan: ['打开一企一档', '填写走访记录', 'AI 提取更新建议', '等你确认写入'] },
        { id: 'enterprise.filter', action: 'filter', examples: ['打开企业台账筛选高新企业', '台账里只看人工智能企业', '列出所有人工智能企业'], keywords: ['台账', '筛选', '列出', '只看'], plan: ['打开台账', '按条件筛选', '报出数量'] },
        { id: 'enterprise.alerts', action: 'alerts', examples: ['资质快到期的企业有哪些', '哪些企业很久没走访了', '超过 90 天没走访的重点企业', '哪些企业好久没去了', '有哪些企业很久没去看了'], keywords: ['到期', '没走访', '久未', '提醒', '预警', '好久没去', '很久没去', '没去过', '多久没去', '没去看', '好久没走访'], plan: ['打开企业管理', '查看提醒', '列出企业'] },
        { id: 'enterprise.issues', action: 'issues', examples: ['看看企业诉求办理进度', '打开诉求看板'], keywords: ['诉求', '看板', '办理进度'], plan: ['打开诉求看板', '汇总各状态'] },
        { id: 'enterprise.export', action: 'export', examples: ['导出企业台账', '把有提醒的企业导出 Excel'], keywords: ['导出', 'Excel', 'CSV'], plan: ['打开台账', '筛选', '导出 CSV'] },
      ],
      starters: ['查一下星河智驾', '资质快到期的企业有哪些？', '给书香里加一条走访记录'],
      demo: [
        { title: '一企一档', say: '查一下星河智驾' },
        { title: '记走访', say: '给书香里加一条走访记录' },
        { title: '台账筛选', say: '打开企业台账筛选高新企业' },
      ],
    },

    mount(el, ctx) {
      const { ui, api, perms } = ctx; const E = api.enterprise; const esc = ui.esc, icon = ui.icon, tag = ui.tag;
      const canOp = perms.can('operate') && !perms.isPartner;
      const S = { tab: 'flow', step: 0, entId: null, prof: null, ptab: 'base', alert: '', q: '', visit: null, notes: '', vtype: C.visitTypes[0], decided: {}, issueId: null, lq: '', ltag: '', lind: '', lalert: false, lsort: 'lastVisit', sel: new Set(), brief: null };
      let ENTS = [], ALERTS = [], ISSUES = [], FACETS = { industries: [], tags: [], servicers: [] }, loaded = false, loadErr = null;
      const $ = (s) => el.querySelector(s);
      const entOf = (id) => ENTS.find((e) => e.id === id) || {};
      const iniHue = (e) => ui.hue((e.industry || '').split(' · ')[0]);
      const ini = (e, lg) => `<span class="ini ${lg ? 'lg' : ''} h-${iniHue(e)}">${esc((e.short || '?')[0])}</span>`;

      async function load() {
        try {
          const [l, a, i] = await Promise.all([E.list({ sort: 'lastVisit' }), E.alerts(), E.issues()]);
          ENTS = l.items; FACETS = l.facets || FACETS; ALERTS = a.items; ISSUES = i.items; loaded = true; loadErr = null;
        } catch (e) { loadErr = e; }
        render();
      }
      async function refreshLists() { const [l, a, i] = await Promise.all([E.list({ sort: 'lastVisit' }), E.alerts(), E.issues()]); ENTS = l.items; ALERTS = a.items; ISSUES = i.items; }
      async function openProfile(id) { S.entId = id; S.prof = null; S.brief = null; S.step = 1; S.ptab = 'base'; S.visit = null; S.decided = {}; body(); try { S.prof = await E.get(id); } catch (e) { ui.toast(e.message, { type: 'err' }); S.step = 0; } body(); briefPolicies(); }
      async function briefPolicies() { try { if (!perms.can('view', 'policy') || !api.policy) return; const r = await api.policy.match({ entId: S.entId }); S.brief = r.summary; const b = $('#ebpol'); if (b) b.innerHTML = polLine(); } catch (e) { /* 政策匹配不可用时不显示 */ } }
      const polLine = () => (S.brief ? `<b class="num">${S.brief.ok}</b> 项可核对${S.brief.check ? ` · ${S.brief.check} 项待确认` : ''} <button class="link" data-act="toPolicy">去看 →</button>` : '<span class="meta">核对中…</span>');

      /* ---------- 框架 ---------- */
      function render() {
        el.innerHTML = `<div class="ap"><div class="ap-h">${ui.appIcon('enterprise', 'lg')}<div class="grow"><h2>${esc(C.name)}</h2><div class="ap-sum">${esc(C.summary)}</div></div><button class="btn ghost sm" data-act="ask" data-op="enterprise.ask">${icon('sparkles')}问 AI</button></div>
          <div class="tabs ap-tabs">${C.tabs.map(([k, l]) => `<button class="tab ${S.tab === k ? 'on' : ''}" data-tab="${k}" data-op="enterprise.tab-${k}">${esc(l)}${k === 'board' && ISSUES.length ? `<span class="count muted">${ISSUES.filter((i) => i.status !== '已办结').length}</span>` : ''}</button>`).join('')}</div>
          ${perms.isPartner ? `<div class="callout h-gray" style="margin-bottom:var(--s4)">${icon('eye-off')}<div>${esc(T.partner)}</div></div>` : ''}<div class="ap-body" id="eb"></div></div>`;
        body();
      }
      function body() {
        const eb = $('#eb'); if (!eb) return;
        if (loadErr) { eb.innerHTML = ui.empty({ icon: 'alert', title: '数据没加载出来', desc: loadErr.message || '', action: '重试' }); return; }
        if (!loaded) { eb.innerHTML = '<div class="skel-list"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>'; return; }
        if (S.tab === 'list') return renderList(eb);
        if (S.tab === 'board') return renderBoard(eb);
        eb.innerHTML = stepsBar() + '<div class="wiz-body ent-step" id="es"></div><div class="wiz-foot" id="ef"></div>';
        [step0, step1, step2, step3][S.step]();
      }
      function stepsBar() { const max = S.entId ? 3 : 0; return `<div class="wiz-steps">${C.steps.map((s, i) => `${i ? `<i class="wiz-line ${i <= S.step ? 'done' : ''}"></i>` : ''}<div class="wiz-step ${i === S.step ? 'on' : i < S.step ? 'done' : ''}" ${i !== S.step && i <= max && (i < 2 || canOp) ? `data-step="${i}"` : ''} data-op="enterprise.step-${i}"><span class="n">${i < S.step ? '✓' : i + 1}</span>${esc(s)}</div>`).join('')}</div>`; }
      const foot = (l, r) => { $('#ef').innerHTML = `${l || ''}<span class="sp"></span>${r || ''}`; };
      const back = () => (S.step > 0 ? `<button class="btn ghost" data-step="${S.step - 1}" data-op="enterprise.back">上一步</button>` : '');

      /* ---------- 第 1 步：找企业 ---------- */
      function step0() {
        const kinds = ['资质到期', '久未走访', '诉求临期'];
        const cnt = (k) => new Set(ALERTS.filter((a) => a.kind === k).map((a) => a.entId)).size;
        const q = S.q.trim();
        let list = ENTS;
        if (S.alert) { const ids = new Set(ALERTS.filter((a) => a.kind === S.alert).map((a) => a.entId)); list = list.filter((e) => ids.has(e.id)); }
        if (q) list = list.filter((e) => (e.name + e.short + e.creditCode + e.industry + (e.formerNames || []).join('') + e.tags.join('')).includes(q));
        const shown = list.slice(0, 8);
        $('#es').innerHTML = `<div class="q">${esc(T.findQ)}</div><div class="q-sub">${esc(T.findSub)}</div>
          <div class="kpis x-stats" style="--n:3">${kinds.map((k) => `<button class="kpi-c h-${ui.hue(k, 'alertKind')} ${S.alert === k ? 'on' : ''}" data-alert="${k}" data-op="enterprise.alert-${k}"><div class="v num">${cnt(k)}</div><div class="l">${esc(k)}</div></button>`).join('')}</div>
          <div class="search" style="margin:var(--s5) 0 var(--s3)">${icon('search')}<input class="input" id="eq" data-op="enterprise.q" placeholder="名称 / 信用代码 / 曾用名 / 标签" value="${esc(S.q)}" autocomplete="off"></div>
          ${shown.length ? `<div class="card flat"><div class="list lined">${shown.map((e) => { const al = ALERTS.filter((a) => a.entId === e.id); return `<div class="li" data-ent="${e.id}" data-op="enterprise.ent-${e.id}">${ini(e)}<div class="grow"><div class="ttl clip">${esc(e.short)}</div><div class="meta clip">${esc(e.industry)} · ${esc(e.servicer)}</div></div>${al[0] ? tag(al[0].kind, 'alertKind') : ''}<span class="meta num" style="width:84px;text-align:right">${e.lastVisitDays ? e.lastVisitDays + ' 天前走访' : '近期已走访'}</span></div>`; }).join('')}</div></div>
          ${list.length > shown.length ? `<button class="btn ghost" data-tab="list" style="margin-top:var(--s2)">在台账里看全部 ${list.length} 家</button>` : ''}` : ui.empty({ icon: 'search', title: '没找到这家企业', desc: canOp ? '可以新建一份企业档案' : '换个关键词试试', action: canOp ? '新建企业' : '' })}`;
        const inp = $('#eq'); let tm; inp.oninput = () => { clearTimeout(tm); tm = setTimeout(() => { S.q = inp.value; step0(); const n = $('#eq'); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 180); };
        foot(canOp ? `<button class="btn ghost" data-act="newEnt" data-op="enterprise.new">${icon('plus')}新建企业</button>` : '', '');
      }

      /* ---------- 第 2 步：一企一档 ---------- */
      function step1() {
        const r = S.prof; if (!r) { $('#es').innerHTML = '<div class="skel-list"><div class="skel"></div><div class="skel" style="height:120px"></div></div>'; foot(back(), ''); return; }
        const e = r.item; const openIssues = r.issues.filter((i) => i.status !== '已办结'); const lastV = r.visits[0];
        const q0 = (e.qualifications || [])[0];
        $('#es').innerHTML = `<div class="ent-head" data-op="enterprise.profile"><div class="row gap3 ent-hd">${ini(e, true)}<div class="grow"><div class="t-lg" style="font-weight:500">${esc(e.short)}</div><div class="meta clip">${esc(e.name)} · ${esc(e.creditCode)}</div></div><div class="row wrap ent-hd-tags">${e.tags.slice(0, 3).map((t) => tag(t, 'entTag')).join('')}</div></div></div>
          <div class="card ent-brief" data-op="enterprise.brief"><div class="card-h"><span class="t-3">${icon('sparkles')}</span><span class="ttl">30 秒速览</span><span class="sp"></span><span class="meta">走访前看这里</span></div>
            <div class="ent-kv4">
              <div><div class="meta">做什么</div><div>${esc(e.products || e.industry)}</div></div>
              <div><div class="meta">资质</div><div>${q0 ? `${esc(q0.name)} <span class="meta">${esc(q0.validTo)} 到期</span>` : '<span class="meta">未登记</span>'}</div></div>
              <div><div class="meta">最近走访</div><div>${lastV ? `${esc(lastV.date)} · ${esc(lastV.staff)}` : '<span class="meta">暂无</span>'}</div></div>
              <div><div class="meta">在办诉求</div><div><b class="num">${openIssues.length}</b> 件${openIssues[0] ? ` <span class="meta clip">${esc(openIssues[0].title)}</span>` : ''}</div></div>
              <div class="span2"><div class="meta">可关注政策</div><div id="ebpol">${polLine()}</div></div>
            </div></div>
          <div class="seg" style="margin:var(--s4) 0 var(--s3)">${C.profileTabs.map(([k, l]) => `<button class="${S.ptab === k ? 'on' : ''}" data-ptab="${k}" data-op="enterprise.ptab-${k}">${esc(l)}</button>`).join('')}</div>
          <div class="card" id="eptab">${profileTab(r)}</div>`;
        foot(back(), `<button class="btn" data-act="toPolicy" data-op="enterprise.to-policy">能申请哪些政策</button>${canOp ? `<button class="btn primary" data-act="toVisit" data-op="enterprise.to-visit">${icon('edit')}记一次走访</button>` : ''}`);
      }
      const kv = (k, v, verify) => `<div class="ent-kv"><span class="meta">${esc(k)}</span><span>${v}</span>${verify ? tag(verify, 'verify', { cls: 'plain' }) : '<span></span>'}</div>`;
      function profileTab(r) {
        const e = r.item; const fs = e.fieldStatus || {};
        if (S.ptab === 'base') return kv('主体类型', esc(e.subjectType)) + kv('成立日期', esc(e.established)) + kv('入区经营', `<span class="num">${e.yearsInZone}</span> 年`) + kv('规模 / 人数', `${esc(e.scale)} · <span class="num">${e.employees}</span> 人`, fs.employees) + kv('注册地址', esc(e.regAddr)) + ((e.formerNames || []).length ? kv('曾用名', esc(e.formerNames.join('、'))) : '') +
          kv('联系人', (e.contacts || []).map((c) => `${esc(c.name)}<span class="meta">（${esc(c.title)}）</span> <span class="num ${e.masked ? 'mask' : ''}">${esc(c.phone)}</span>`).join('<br>')) + kv('服务专员', esc(e.servicer));
        if (S.ptab === 'biz') { const rv = e.revenue || {}; const am = e.amounts || {};
          return kv('营业收入', e.masked ? '<span class="mask">受限字段</span>' : `<b class="num">${esc(rv.value)}</b> ${esc(rv.unit)} <span class="meta">${esc(rv.period)} · ${esc(rv.source)}</span>`, e.masked ? '' : rv.verify) +
            (am.rent != null ? kv('年房租', `<span class="num">${ui.fmtMoney(am.rent)}</span>`, fs.amounts) : '') + (am.area != null ? kv('经营面积', `<span class="num">${am.area}</span> ㎡`, fs.amounts) : '') +
            Object.entries(am).filter(([k]) => !['rent', 'area'].includes(k)).map(([k, v]) => kv({ dataPurchase: '数据采购额', computePurchase: '算力采购额', renovation: '改造投入', digitalInvest: '数字化投入', sceneInvest: '场景投入', datasetInvest: '数据集投入', firstSale: '首台套合同额' }[k] || k, `<span class="num">${ui.fmtMoney(v)}</span>`, fs.amounts)).join('') +
            (e.qualifications || []).map((q) => kv('资质', `${esc(q.name)} <span class="meta">有效期至 ${esc(q.validTo)}</span>`, q.verify)).join('') + (e.license || []).filter((l) => !(e.qualifications || []).some((q) => q.name === l)).map((l) => kv('许可', esc(l))).join(''); }
        if (S.ptab === 'visit') return `<div class="sec" style="margin-top:0">走访</div>${r.visits.length ? `<div class="tl">${r.visits.slice(0, 4).map((v) => `<div class="tl-i"><div class="t">${esc(v.date)} · ${esc(v.type)} · ${esc(v.staff)}</div><div class="m clamp2">${esc(v.notes)}</div></div>`).join('')}</div>` : '<div class="meta">暂无走访</div>'}
          <div class="sec">诉求</div>${r.issues.length ? `<div class="list">${r.issues.map((i) => `<div class="li" data-issue="${i.id}"><div class="grow"><div class="ttl clip">${esc(i.title)}</div><div class="meta">${esc(i.owner)} · ${esc(i.due)} 到期</div></div>${tag(i.status, 'issueStatus')}</div>`).join('')}</div>` : '<div class="meta">暂无诉求</div>'}
          ${r.files && r.files.length ? `<div class="sec">原始资料</div>${r.files.map((f) => `<div class="li" data-kbfile="${esc(f.id)}"><span class="t-3">${icon('file')}</span><div class="grow clip">${esc(f.name)}</div></div>`).join('')}` : ''}`;
        const h = r.history || [];
        return h.length ? `<div class="tl">${h.map((x) => `<div class="tl-i"><div class="t">${esc(x.field)}：<span class="t-3">${esc(x.old)}</span> → <b>${esc(x.new)}</b></div><div class="m">${esc(x.at)} · ${esc(x.by)} · ${esc(x.source)}</div></div>`).join('')}</div>` : `<div class="meta">还没有变更。走访后确认写入的内容会记在这里。</div>`;
      }

      /* ---------- 第 3 步：记走访 ---------- */
      function step2() {
        const e = S.prof && S.prof.item; if (!e) { S.step = 0; return body(); }
        const v = S.visit;
        if (!v) {
          $('#es').innerHTML = `<div class="q">${esc(T.visitQ)}</div><div class="q-sub">${esc(T.visitSub)}</div>
            <div class="row gap3" style="margin-bottom:var(--s3)"><span class="ini h-${iniHue(e)}">${esc(e.short[0])}</span><b>${esc(e.short)}</b><span class="sp"></span><select class="select" style="width:130px" id="evt" data-op="enterprise.vtype">${C.visitTypes.map((t) => `<option ${S.vtype === t ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></div>
            <textarea class="textarea ent-notes" id="en" data-op="enterprise.notes" placeholder="例如：房租涨到 48 万；计划扩租 400㎡；新任行政主管周娜（电话 139…）">${esc(S.notes)}</textarea>
            <div class="row" style="margin-top:var(--s2)"><button class="btn sm ghost" data-act="sample" data-op="enterprise.sample">${icon('file')}填入示例</button><button class="btn sm ghost" data-act="voice" data-op="enterprise.voice">${icon('mic')}语音输入（演示）</button><span class="sp"></span><span class="meta">${esc(T.noWrite)}</span></div>`;
          $('#en').oninput = (ev) => (S.notes = ev.target.value); $('#evt').onchange = (ev) => (S.vtype = ev.target.value);
          foot(back(), `<button class="btn primary" data-act="organize" data-op="enterprise.organize">${icon('sparkles')}整理成更新建议</button>`);
          return;
        }
        const pend = v.proposals.filter((p) => !S.decided[p.id]);
        $('#es').innerHTML = `<div class="q">${v.proposals.length ? `${v.proposals.length} 条台账更新建议` : '没有需要更新的台账字段'}</div><div class="q-sub">${esc(T.noWrite)}</div>
          <div class="stack rows">${v.proposals.map(propRow).join('')}</div>
          ${v.issues.length ? `<div class="sec">提到的诉求 ${v.issues.length} 件</div><div class="stack rows">${v.issues.map((t, i) => `<div class="card tight row gap3"><span class="t-3">${icon('flag')}</span><div class="grow clamp2">${esc(t)}</div>${v.logged && v.logged[i] ? tag('已登记', 'status') : `<button class="btn sm" data-logissue="${i}" data-op="enterprise.log-${i}">登记诉求</button>`}</div>`).join('')}</div>` : ''}
          ${!pend.length && v.proposals.length ? `<div class="callout h-green" style="margin-top:var(--s4)">${icon('check')}<div class="grow">台账已更新，变更已留痕</div><button class="btn sm" data-act="viewHistory">看变更历史</button></div>` : ''}`;
        foot(`<button class="btn ghost" data-act="revisit" data-op="enterprise.revisit">重新填写</button>`, pend.length ? `<button class="btn primary" data-act="acceptAll" data-op="enterprise.accept-all">全部确认写入 ${pend.length} 条</button>` : `<button class="btn primary" data-act="toIssues" data-op="enterprise.to-issues">跟进诉求</button>`);
      }
      function propRow(p) {
        const d = S.decided[p.id];
        return `<div class="card tight ent-prop ${d ? 'done' : ''}" data-prop="${p.id}"><div class="row gap3"><div class="grow"><div class="meta">${esc(p.label)}</div><div class="ent-chg">${/新增/.test(p.label||'') ? `<span class="t-3">原有 ${esc(p.old)}，再加</span>` : `<span class="old">${esc(p.old)}</span><span class="t-3">${icon('arrow-right')}</span>`}<b class="new">${esc(d && d.value ? d.value : p.new)}</b></div><div class="meta clamp2">原话：“${esc(p.source)}”</div></div>
          ${d ? tag(d.kind === 'accept' ? '已写入' : '已忽略', 'proposal') : `<div class="row"><button class="btn sm ghost" data-ignore="${p.id}" data-op="enterprise.ignore-${p.id}">忽略</button><button class="btn sm ghost" data-editp="${p.id}">改一下</button><button class="btn sm soft" data-accept="${p.id}" data-op="enterprise.accept-${p.id}">确认写入</button></div>`}</div></div>`;
      }

      /* ---------- 第 4 步：跟诉求 ---------- */
      function step3() {
        const list = ISSUES.filter((i) => !S.entId || i.entId === S.entId); const all = list.length ? list : ISSUES;
        if (!S.issueId || !all.some((i) => i.id === S.issueId)) S.issueId = (all.find((i) => i.status !== '已办结') || all[0] || {}).id;
        const it = all.find((i) => i.id === S.issueId);
        $('#es').innerHTML = `<div class="q">${list.length ? `${esc(entOf(S.entId).short || '')} 的诉求` : '全部诉求'}</div><div class="q-sub">选一件，改状态、写一句进展</div>
          <div class="ent-iss"><div class="list ent-iss-l">${all.map((i) => `<div class="li ${i.id === S.issueId ? 'on' : ''}" data-issue="${i.id}" data-op="enterprise.issue-${i.id}"><div class="grow"><div class="ttl clamp2">${esc(i.title)}</div><div class="meta">${esc(i.entName || entOf(i.entId).short || '')} · ${esc(i.due)}</div></div>${tag(i.status, 'issueStatus')}</div>`).join('') || '<div class="meta">暂无诉求</div>'}</div>
          <div class="card">${it ? issueForm(it) : ui.empty({ icon: 'flag', title: '暂无诉求' })}</div></div>`;
        foot(back(), it && canOp ? `<button class="btn primary" data-act="saveIssue" data-op="enterprise.save-issue">保存进展</button>` : '');
      }
      function issueForm(it) {
        return `<div class="t-lg" style="font-weight:500">${esc(it.title)}</div><div class="meta" style="margin-bottom:var(--s3)">${esc(it.from || '')}登记 · ${esc(it.created)} · 期限 ${esc(it.due)}</div>
          <div class="tl">${(it.steps || []).map((s) => `<div class="tl-i"><div class="t">${esc(s[1])}</div><div class="m">${esc(s[0])}</div></div>`).join('')}</div>
          ${canOp ? `<div class="grid g2" style="margin-top:var(--s2)"><div class="field"><label>状态</label><select class="select" id="ist" data-op="enterprise.issue-status">${C.issueStatuses.map((s) => `<option ${s === it.status ? 'selected' : ''}>${s}</option>`).join('')}</select></div><div class="field"><label>责任人</label><input class="input" id="iow" value="${esc(it.owner)}"></div></div>
          <div class="field" style="margin-top:var(--s3)"><label>本次进展</label><input class="input" id="inote" data-op="enterprise.issue-note" placeholder="例如：已电话告知企业，等待批次通知"></div><div class="meta" style="margin-top:var(--s2)">下一步：${esc(it.next || '—')}</div>` : `<div class="meta">下一步：${esc(it.next || '—')}</div>`}`;
      }

      /* ---------- 台账 ---------- */
      async function renderList(eb) {
        eb.innerHTML = `<div class="row gap3 wrap" style="margin-bottom:var(--s3)"><div class="search grow">${icon('search')}<input class="input" id="lq" data-op="enterprise.list-q" placeholder="搜企业" value="${esc(S.lq)}"></div>
          <select class="select" style="width:140px" id="ltag" data-op="enterprise.list-tag"><option value="">全部标签</option>${FACETS.tags.map((t) => `<option ${S.ltag === t ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select>
          <select class="select" style="width:130px" id="lind" data-op="enterprise.list-ind"><option value="">全部行业</option>${FACETS.industries.map((t) => `<option ${S.lind === t ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select>
          <label class="check"><input type="checkbox" id="lal" data-op="enterprise.list-alert" ${S.lalert ? 'checked' : ''}>只看有提醒</label></div><div id="ltb"><div class="skel-list"><div class="skel"></div></div></div>`;
        const go = () => renderTable();
        let tm; $('#lq').oninput = (ev) => { clearTimeout(tm); tm = setTimeout(() => { S.lq = ev.target.value; go(); }, 200); };
        $('#ltag').onchange = (ev) => { S.ltag = ev.target.value; go(); }; $('#lind').onchange = (ev) => { S.lind = ev.target.value; go(); }; $('#lal').onchange = (ev) => { S.lalert = ev.target.checked; go(); };
        go();
      }
      async function renderTable() {
        const box = $('#ltb'); if (!box) return;
        let r; try { r = await E.list({ q: S.lq.trim(), tag: S.ltag, industry: S.lind, alert: S.lalert ? 1 : '', sort: S.lsort }); } catch (e) { box.innerHTML = ui.empty({ icon: 'alert', title: '加载失败', desc: e.message }); return; }
        S.listIds = r.items.map((e) => e.id); S.tableKey = [S.lq.trim(), S.ltag, S.lind, S.lalert, S.lsort].join('|'); const alertIds = new Set(ALERTS.map((a) => a.entId));
        box.innerHTML = `<div class="row" style="margin-bottom:var(--s2)"><span class="meta" data-op="enterprise.list-count">${r.total} 家${S.sel.size ? ` · 已选 ${S.sel.size}` : ''}</span><span class="sp"></span>
            <select class="select sm" style="width:120px;height:28px" id="lsort"><option value="lastVisit" ${S.lsort === 'lastVisit' ? 'selected' : ''}>最久未走访</option><option value="revenue" ${S.lsort === 'revenue' ? 'selected' : ''}>营收</option><option value="name" ${S.lsort === 'name' ? 'selected' : ''}>名称</option></select>
            ${canOp ? `<button class="btn sm ghost" data-act="import" data-op="enterprise.import">${icon('upload')}导入</button>` : ''}<button class="btn sm" data-act="export" data-op="enterprise.export">${icon('download')}导出 CSV</button></div>
          ${r.items.length ? `<div class="card flat ent-tbl scroll"><table class="tbl"><thead><tr><th style="width:32px"><input type="checkbox" class="pol-ck" data-selall></th><th>企业</th><th>行业</th><th class="r">人数</th><th class="r">营收(万元)</th><th>服务专员</th><th class="r">最近走访</th></tr></thead><tbody>
            ${r.items.map((e) => `<tr class="${S.sel.has(e.id) ? 'sel' : ''}"><td><input type="checkbox" data-sel="${e.id}" ${S.sel.has(e.id) ? 'checked' : ''}></td><td><a class="link" data-ent="${e.id}">${esc(e.short)}</a>${alertIds.has(e.id) ? ` <span class="sdot h-amber" title="有提醒"></span>` : ''}</td><td class="t-2">${esc(e.industry.split(' · ')[0])}</td><td class="r num">${e.employees}</td><td class="r num ${e.masked ? 'mask' : ''}">${esc(e.revenue.value)}</td><td class="t-2">${esc(e.servicer)}</td><td class="r num ${e.lastVisitDays > C.staleDays ? 'ent-stale' : 't-2'}">${e.lastVisitDays ? e.lastVisitDays + ' 天' : '—'}</td></tr>`).join('')}</tbody></table></div>` : ui.empty({ icon: 'filter', title: '没有符合条件的企业', action: '清空筛选' })}`;
        $('#lsort') && ($('#lsort').onchange = (ev) => { S.lsort = ev.target.value; renderTable(); });
      }

      /* ---------- 诉求看板 ---------- */
      function renderBoard(eb) {
        eb.innerHTML = `<div class="ent-board">${C.issueStatuses.map((st) => { const l = ISSUES.filter((i) => i.status === st); return `<div class="ent-col"><div class="ent-colh"><span class="x-ring h-${ui.hue(st, 'issueStatus')}"></span>${esc(st)}<span class="t-3 num">${l.length}</span></div>${l.map((i) => `<div class="card tight hoverable ent-bcard" data-bissue="${i.id}" data-op="enterprise.bissue-${i.id}"><div class="clamp2" style="font-weight:500">${esc(i.title)}</div><div class="meta" style="margin-top:4px">${esc(i.entName)} · ${esc(i.owner)}</div><div class="meta ${i.status !== '已办结' && i.due < '2026-11-22' ? 'ent-stale' : ''}">${esc(i.due)} 到期</div></div>`).join('') || '<div class="meta" style="padding:var(--s3) 0">—</div>'}</div>`; }).join('')}</div>`;
      }
      function issueDrawer(id) {
        const it = ISSUES.find((i) => i.id === id); if (!it) return;
        const dr = ui.drawer({ title: it.entName || '诉求', body: `<div class="app-enterprise">${issueForm(it)}${canOp ? '<div class="row" style="margin-top:var(--s4)"><span class="sp"></span><button class="btn primary" data-dsave>保存进展</button></div>' : ''}</div>`, width: 480 });
        const b = dr.el.querySelector('[data-dsave]'); if (b) b.onclick = async () => { await saveIssue(it.id, dr.el); dr.close(); renderBoard($('#eb')); };
      }
      async function saveIssue(id, scope) {
        const root = scope || el; const st = root.querySelector('#ist').value, note = root.querySelector('#inote').value.trim(), owner = root.querySelector('#iow').value.trim();
        try { await E.patchIssue(id, { status: st, note, owner }); await refreshLists(); ctx.bus.emit('inbox:changed'); ui.toast('进展已保存，时间线已更新'); } catch (e) { ui.toast(e.message || '保存失败', { type: 'err' }); }
      }

      /* ---------- 动作 ---------- */
      async function organize() {
        if (!S.notes.trim()) { ui.toast('先写几句走访情况，或点“填入示例”', { type: 'warn' }); return; }
        const b = $('[data-op="enterprise.organize"]'); if (b) { b.disabled = true; b.innerHTML = '整理中…'; }
        try { const r = await E.visit(S.entId, { notes: S.notes, type: S.vtype }); S.visit = { ...r, logged: {} }; S.decided = {}; ctx.bus.emit('inbox:changed'); } catch (e) { ui.toast(e.message || '整理失败', { type: 'err' }); }
        body();
      }
      async function decide(pid, kind, value) {
        try { await E.decide(pid, { decision: kind, value }); S.decided[pid] = { kind, value }; } catch (e) { ui.toast(e.message || '写入失败', { type: 'err' }); return; }
        const pend = S.visit.proposals.filter((p) => !S.decided[p.id]); if (!pend.length) { S.prof = await E.get(S.entId); await refreshLists(); ctx.bus.emit('inbox:changed'); }
        body();
      }
      async function acceptAll() { for (const p of S.visit.proposals.filter((x) => !S.decided[x.id])) await decide(p.id, 'accept'); ui.toast('已写入台账，变更已留痕'); }
      async function logIssue(i) { const t = S.visit.issues[i]; try { await E.createIssue({ entId: S.entId, title: t.slice(0, 40), from: '走访' }); S.visit.logged[i] = true; await refreshLists(); ui.toast('诉求已登记'); } catch (e) { ui.toast(e.message, { type: 'err' }); } body(); }
      async function exportCsv() { const ids = S.sel.size ? [...S.sel] : S.listIds || []; const r = await E.exportCsv({ ids: ids.join(',') }); ui.download(r.filename, r.csv, 'text/csv;charset=utf-8'); ui.toast(`已导出 ${ids.length} 家`); return ids.length; }
      function newEntModal() {
        ui.modal({ title: '新建企业档案', okText: '创建', body: `<div class="stack app-enterprise"><div class="field"><label>企业名称</label><input class="input" id="nn" placeholder="北京××科技有限公司"></div><div class="grid g2"><div class="field"><label>统一社会信用代码</label><input class="input" id="nc"></div><div class="field"><label>行业</label><input class="input" id="ni" placeholder="人工智能 · 大模型"></div></div><div class="grid g2"><div class="field"><label>联系人</label><input class="input" id="nct"></div><div class="field"><label>电话</label><input class="input" id="np"></div></div></div>`,
          ok: async (d) => { const name = d.querySelector('#nn').value.trim(); if (!name) { ui.toast('请填写企业名称', { type: 'warn' }); return false; } const r = await E.create({ name, creditCode: d.querySelector('#nc').value.trim(), industry: d.querySelector('#ni').value.trim(), contact: d.querySelector('#nct').value.trim(), phone: d.querySelector('#np').value.trim() }); await refreshLists(); ui.toast('已新建档案'); S.tab = 'flow'; render(); openProfile(r.item.id); } });
      }
      function importModal(rows) {
        rows = rows || C.importSample;
        return ui.modal({ title: '导入企业（Excel）', okText: `导入 ${rows.length} 家`, body: `<div class="stack app-enterprise"><div class="meta">已识别表头并自动对应字段，确认后导入</div>
          <div class="row wrap">${C.importMap.map(([a, b]) => `<span class="tag" data-hue="gray">${esc(a)} → ${esc(b)}</span>`).join('')}</div>
          <div class="card flat"><table class="tbl"><thead><tr><th>企业名称</th><th>行业</th><th class="r">人数</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${esc(r.name)}</td><td class="t-2">${esc(r.industry || '')}</td><td class="r num">${esc(r.employees || '')}</td></tr>`).join('')}</tbody></table></div></div>`,
          ok: async () => { const r = await E.import({ rows }); await refreshLists(); ui.toast(`已导入 ${r.added} 家`); body(); } });
      }
      async function voiceInput() { const txt = C.visitSamples[S.entId] || C.visitSamples._default; const ta = $('#en'); if (!ta) return; ta.value = ''; ui.toast('正在听写（演示）…'); for (let i = 0; i < txt.length; i += 3) { ta.value = txt.slice(0, i + 3); await new Promise((r) => setTimeout(r, 12)); } S.notes = ta.value; }
      function resolveEnt(slot, text) {
        if (slot && typeof slot === 'object' && slot.id) return slot.id;
        const s = String(slot || text || '');
        const hit = ENTS.find((e) => s.includes(e.short) || s.includes(e.name) || (e.short.length >= 3 && s.includes(e.short.slice(0, 3)))) || ENTS.find((e) => s && e.short.includes(s));
        return hit ? hit.id : null;
      }
      const ready = async () => { for (let i = 0; i < 60 && !loaded; i++) await new Promise((r) => setTimeout(r, 50)); };

      /* ---------- 事件 ---------- */
      el.addEventListener('click', async (ev) => {
        const t = ev.target.closest('[data-tab],[data-step],[data-ent],[data-alert],[data-ptab],[data-act],[data-accept],[data-ignore],[data-editp],[data-logissue],[data-issue],[data-bissue],[data-kbfile],[data-empty-action]'); if (!t) return; const d = t.dataset;
        if (d.tab) { S.tab = d.tab; render(); return; }
        if (d.step != null) { S.step = +d.step; body(); return; }
        if (d.ent) { if (S.tab !== 'flow') { S.tab = 'flow'; render(); } return openProfile(d.ent); }
        if (d.alert) { S.alert = S.alert === d.alert ? '' : d.alert; step0(); return; }
        if (d.ptab) { S.ptab = d.ptab; step1(); return; }
        if (d.accept) return decide(d.accept, 'accept');
        if (d.ignore) return decide(d.ignore, 'reject');
        if (d.editp) { const p = S.visit.proposals.find((x) => x.id === d.editp); ui.modal({ title: `改一下：${p.label}`, okText: '确认写入', body: `<div class="field"><label>新值</label><input class="input" id="pv" value="${esc(p.new)}"></div>`, ok: (m) => decide(p.id, 'accept', m.querySelector('#pv').value) }); return; }
        if (d.logissue != null) return logIssue(+d.logissue);
        if (d.issue) { if (S.step === 3) { S.issueId = d.issue; step3(); } else { S.issueId = d.issue; S.step = 3; body(); } return; }
        if (d.bissue) return issueDrawer(d.bissue);
        if (d.kbfile) return ctx.kb.open(d.kbfile);
        if (d.emptyAction != null) { if (loadErr) { loaded = false; body(); return load(); } if (S.tab === 'list') { S.lq = ''; S.ltag = ''; S.lind = ''; S.lalert = false; return renderList($('#eb')); } return newEntModal(); }
        const a = d.act;
        if (a === 'ask') return ctx.nav.chat(S.entId ? `${entOf(S.entId).short}最近有什么情况？` : '哪些企业很久没走访了？');
        if (a === 'newEnt') return newEntModal();
        if (a === 'toPolicy') return ctx.nav.open('policy', 'match', { entId: S.entId, run: true });
        if (a === 'toVisit') { S.step = 2; S.visit = null; body(); return; }
        if (a === 'sample') { S.notes = C.visitSamples[S.entId] || C.visitSamples._default; step2(); return; }
        if (a === 'voice') return voiceInput();
        if (a === 'organize') return organize();
        if (a === 'acceptAll') return acceptAll();
        if (a === 'revisit') { S.visit = null; body(); return; }
        if (a === 'viewHistory') { S.step = 1; S.ptab = 'history'; body(); return; }
        if (a === 'toIssues') { S.step = 3; body(); return; }
        if (a === 'saveIssue') { await saveIssue(S.issueId); body(); return; }
        if (a === 'export') return exportCsv();
        if (a === 'import') return importModal();
      });
      el.addEventListener('change', (ev) => { const t = ev.target; if (t.dataset.sel) { t.checked ? S.sel.add(t.dataset.sel) : S.sel.delete(t.dataset.sel); renderTable(); } if (t.dataset.selall != null) { (S.listIds || []).forEach((id) => (t.checked ? S.sel.add(id) : S.sel.delete(id))); renderTable(); } });

      load();

      const gotoTab = (k) => { if (S.tab !== k) { S.tab = k; render(); } };
      async function opOpen(id, run) {
        gotoTab('flow'); if (S.step !== 0) { S.step = 0; S.q = ''; body(); }
        const e = entOf(id);
        if (run) { await run.fill('[data-op="enterprise.q"]', e.short); await run.wait(`[data-op="enterprise.ent-${id}"]`); await run.click(`[data-op="enterprise.ent-${id}"]`); await run.wait(() => S.prof && S.prof.item.id === id && el.querySelector('[data-op="enterprise.brief"]')); }
        else await openProfile(id);
      }
      const actions = {
        async find({ ent, text } = {}, run) {
          await ready(); const id = resolveEnt(ent, text); if (!id) { run && run.fail('没认出是哪家企业，请说出企业名称'); return; }
          if (run) await run.step(1); await opOpen(id, run);
          if (run) { await run.step(3); await run.highlight('[data-op="enterprise.brief"]'); const e = S.prof.item; const oi = S.prof.issues.filter((i) => i.status !== '已办结'); run.done(`${e.short}：${e.industry}，${e.employees} 人；最近走访 ${e.lastVisit}；在办诉求 ${oi.length} 件`, [{ label: '能申请哪些政策', say: `${e.short}能申请哪些支持？` }, ...(canOp ? [{ label: '记一次走访', say: `给${e.short}加一条走访记录` }] : [])]); }
          return S.prof;
        },
        async visit({ ent, text, notes } = {}, run) {
          await ready(); const id = resolveEnt(ent, text) || S.entId; if (!id) { run && run.fail('给哪家企业记走访？'); return; }
          if (!canOp) { run && run.fail('你的角色没有企业管理的操作权限，不能修改台账'); return; }
          if (!S.prof || S.prof.item.id !== id || S.step === 0) { await opOpen(id, run); }
          if (run) { await run.step(1); await run.click('[data-op="enterprise.to-visit"]'); await run.wait('[data-op="enterprise.notes"]'); if (notes) await run.fill('[data-op="enterprise.notes"]', notes); else await run.click('[data-op="enterprise.sample"]'); await run.step(2); await run.click('[data-op="enterprise.organize"]'); await run.wait(() => S.visit && el.querySelector('[data-op="enterprise.revisit"]'), 8000); await run.step(3);
            const n = S.visit.proposals.length; if (!n) { run.done('没有提取到需要更新的台账字段'); return; }
            await run.highlight('[data-op="enterprise.accept-all"]', '确认后才写入台账');
            const c = await run.ask(`整理出 ${n} 条台账更新建议${S.visit.issues.length ? `、${S.visit.issues.length} 件诉求` : ''}，确认写入台账吗？`, ['确认写入', '我自己逐条看']);
            if (c === '确认写入') { await run.click('[data-op="enterprise.accept-all"]'); await run.wait(() => !S.visit.proposals.some((p) => !S.decided[p.id])); run.done(`已写入 ${n} 条，变更已留痕`, S.visit.issues.length ? [{ label: '登记诉求', say: '把走访里提到的诉求登记一下' }] : []); }
            else run.done('好的，建议都在右侧，逐条点“确认写入 / 忽略”即可');
          } else { S.step = 2; S.notes = notes || C.visitSamples[id] || C.visitSamples._default; await organize(); }
        },
        async filter({ tag: tg, text } = {}, run) {
          await ready(); const s = String(tg || text || ''); const want = FACETS.tags.find((t) => s.includes(t) || (t.length > 2 && s.includes(t.slice(0, 2)))) || '';
          const ind = !want ? FACETS.industries.find((t) => s.includes(t)) || '' : '';
          gotoTab('list');
          if (run) { await run.step(1); if (want) await run.select('[data-op="enterprise.list-tag"]', want); else if (ind) await run.select('[data-op="enterprise.list-ind"]', ind); await run.wait(() => S.tableKey === [S.lq.trim(), S.ltag, S.lind, S.lalert, S.lsort].join('|') && el.querySelector('[data-op="enterprise.list-count"]')); await run.step(2); await run.highlight('[data-op="enterprise.list-count"]'); run.done(`${want || ind || '全部'}企业共 ${(S.listIds || []).length} 家`, [{ label: '导出 CSV', say: '导出企业台账' }]); }
          else { S.ltag = want; S.lind = ind; renderList($('#eb')); }
        },
        async alerts({ text } = {}, run) {
          await ready(); gotoTab('flow'); S.step = 0; S.q = ''; body();
          const k = /没走访|久未|走访|没去/.test(text || '') ? '久未走访' : /诉求/.test(text || '') ? '诉求临期' : '资质到期';
          if (run) { await run.step(1); await run.click(`[data-op="enterprise.alert-${k}"]`); await run.step(2); const l = ALERTS.filter((a) => a.kind === k); run.done(`${k} ${new Set(l.map((a) => a.entId)).size} 家：${l.slice(0, 4).map((a) => `${a.name}（${a.text}）`).join('；')}`, [{ label: '导出这些企业', say: '把有提醒的企业导出 Excel' }]); }
          else { S.alert = k; step0(); }
        },
        async issues(a, run) { await ready(); gotoTab('board'); if (run) { await run.step(1); const c = {}; ISSUES.forEach((i) => (c[i.status] = (c[i.status] || 0) + 1)); run.done(`诉求共 ${ISSUES.length} 件：${C.issueStatuses.map((s) => `${s} ${c[s] || 0}`).join('，')}`); } },
        async export({ text } = {}, run) {
          await ready(); gotoTab('list'); if (/提醒/.test(text || '')) { S.lalert = true; renderList($('#eb')); }
          if (run) { await run.step(1); await run.wait(() => S.tableKey === [S.lq.trim(), S.ltag, S.lind, S.lalert, S.lsort].join('|') && el.querySelector('[data-op="enterprise.export"]')); await run.step(2); await run.click('[data-op="enterprise.export"]'); run.done(`已导出 ${(S.listIds || []).length} 家企业（CSV，Excel 可直接打开）`); } else { await new Promise((r) => setTimeout(r, 300)); return exportCsv(); }
        },
        async intake({ file } = {}, run) {
          await ready();
          if (/xlsx?|csv/i.test(file.ext || '')) { gotoTab('list'); const m = importModal(); run && run.done(`这是一份企业名单（${file.name}），已识别表头，确认后导入台账`); return m; }
          const id = resolveEnt(null, (file.name || '') + ' ' + (file.text || '').slice(0, 400));
          let kbIn = false; if (!perms.isPartner && ctx.kb && ctx.kb.import) { try { const r = await ctx.kb.import([file], { space: 'enterprise', from: '企业管理' }); kbIn = !!(r && (r.docs || []).length); } catch (e) { /* 知识库不可用时只打开档案 */ } }
          const isVisit = file.text && /走访|随记|拜访|调研|上门/.test((file.name || '') + String(file.text).slice(0, 300));
          if (id && canOp && isVisit && this && this.visit) { run && run.say && run.say(`识别为「${entOf(id).short}」的走访记录，按你的原文整理${kbIn ? '（原件已存入知识库“企业档案”）' : ''}`); return this.visit({ ent: entOf(id).short, notes: String(file.text).slice(0, 1200) }, run); }
          if (id) { await opOpen(id, run); S.ptab = 'visit'; step1(); run && run.done(`已识别为「${entOf(id).short}」的资料，已打开一企一档${kbIn ? '，原件存入知识库“企业档案”' : ''}`, canOp ? [{ label: '记一次走访', say: `给${entOf(id).short}加一条走访记录` }] : []); }
          else { gotoTab('flow'); run && run.done(`没认出是哪家企业的资料，可以在台账里新建档案`, canOp ? [{ label: '新建企业', say: '新建一家企业档案' }] : []); }
        },
      };
      return {
        go(route, params = {}) {
          ready().then(() => {
            if (route === 'list' || route === 'board') { S.tab = route; if (params.tag) S.ltag = params.tag; render(); return; }
            S.tab = 'flow'; render();
            if (route === 'issues') { if (params.entId) S.entId = params.entId; S.step = 3; body(); return; }
            if (params.entId) openProfile(params.entId).then(() => { if (route === 'visit' && canOp) { S.step = 2; S.visit = null; if (params.notes) S.notes = params.notes; body(); } });
          });
        },
        actions,
        unmount() {},
      };
    },
  });
})();

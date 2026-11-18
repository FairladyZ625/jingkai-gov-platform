/* 应用独立测试台（apps worker 自用，不属于外壳）。用真实的 shell.core.js（JK.ui）+ api 适配层 + mock 后端，
 * 只补一个最小 ctx 和操作员 run：index.html?app=policy&theme=light&user=u-hejun&route=match&params={"entId":"E001"}&fast=1 */
(function () {
  const qs = new URLSearchParams(location.search);
  const APP = qs.get('app') || 'policy';
  document.documentElement.dataset.theme = qs.get('theme') || 'light';
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  /* 临时：CONTRACT_REQUESTS #6 合入 tags.js 前，测试台先注入应用要用的分组 */
  window.JK_TAGS = window.JK_TAGS || {};
  Object.entries({ policyLevel: { '可进一步核对': 'green', '待确认': 'amber', '不满足': 'gray' }, policyWindow: { '申报中': 'green', '本批已结束': 'gray', '窗口待通知': 'amber' }, policyObj: { '企业': 'teal', '个人': 'cyan', '其他组织': 'violet' }, verify: { '已核实': 'green', '企业自报': 'amber', '预测': 'violet', '待核': 'gray', '统计报表': 'green' }, alertKind: { '资质到期': 'red', '久未走访': 'amber', '诉求临期': 'orange' }, issueStatus: { '待分派': 'gray', '办理中': 'blue', '待补材料': 'amber', '已办结': 'green' }, proposal: { '待确认': 'amber', '已写入': 'green', '已忽略': 'gray' }, meetStatus: { '新录音': 'blue', '整理中': 'blue', '已整理': 'green', '仅局方': 'violet' }, meetType: { '企业座谈会': 'teal', '局务会': 'violet', '专题推进会': 'indigo' }, todoStatus: { '待认领': 'amber', '待确认': 'amber', '已派发': 'green', '已完成': 'green' }, checkLevel: { '必须改': 'red', '建议改': 'amber', '提示': 'blue', '通过': 'green' }, docStatus: { '草稿': 'gray', '审签中': 'blue', '已定稿': 'green', '已退回': 'red' }, docGroup: { '发布政策与安排': 'indigo', '面向企业组织事项': 'teal', '公开结果与回应': 'orange' } }).forEach(([k, v]) => { if (!window.JK_TAGS[k]) window.JK_TAGS[k] = v; });
  /* ---- 操作员 run（简化版：光标 + 高亮 + 日志） ---- */
  const log = (window.__oplog = []);
  function mkRun(planLen) {
    let cur, ring; const fast = qs.has('fast');
    const move = async (sel) => { const el = typeof sel === 'string' ? document.querySelector(sel) : sel; if (!el) throw new Error('操作员找不到元素 ' + sel); el.scrollIntoView({ block: 'center' }); await sleep(fast ? 20 : 120); const r = el.getBoundingClientRect(); if (!cur) { cur = document.createElement('div'); cur.className = 'op-cursor'; cur.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M4 2l16 10-7 1.5L9 21z" fill="var(--accent)" stroke="#fff" stroke-width="1.5"/></svg><span class="lbl">AI</span>'; document.body.appendChild(cur); ring = document.createElement('div'); ring.className = 'op-ring'; document.body.appendChild(ring); } cur.style.left = r.left + r.width / 2 + 'px'; cur.style.top = r.top + r.height / 2 + 'px'; Object.assign(ring.style, { left: r.left - 4 + 'px', top: r.top - 4 + 'px', width: r.width + 8 + 'px', height: r.height + 8 + 'px' }); await sleep(fast ? 30 : 450); return el; };
    const clear = () => setTimeout(() => { if (cur) { cur.remove(); ring.remove(); cur = ring = null; } }, fast ? 0 : 600);
    const run = {
      stopped: false,
      async step(i) { log.push(['step', i]); },
      async click(sel) { const el = await move(sel); log.push(['click', sel]); el.click(); await sleep(fast ? 30 : 200); },
      async fill(sel, text) { const el = await move(sel); log.push(['fill', sel, text]); el.focus(); el.value = ''; for (const ch of String(text)) { el.value += ch; await sleep(fast ? 0 : 25); } el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); },
      async select(sel, v) { const el = await move(sel); el.value = v; el.dispatchEvent(new Event('change', { bubbles: true })); log.push(['select', sel, v]); },
      async highlight(sel, note) { await move(sel); log.push(['highlight', sel, note]); },
      async scroll(sel) { await move(sel); },
      async wait(f, timeout = 8000) { const t0 = Date.now(); for (;;) { const ok = typeof f === 'string' ? document.querySelector(f) : f(); if (ok) return ok; if (Date.now() - t0 > timeout) throw new Error('等待超时 ' + f); await sleep(80); } },
      sleep: (ms) => sleep(fast ? Math.min(ms, 60) : ms),
      async ask(q, opts) { log.push(['ask', q, opts]); return opts[0]; },
      say(t) { log.push(['say', t]); }, done(s, next) { log.push(['done', s, next]); clear(); }, fail(m) { log.push(['fail', m]); clear(); },
    };
    return run;
  }
  window.__harness = { mkRun };
  window.addEventListener('load', async () => {
    const J = window.JK; const A = window.JKAPI;
    if (qs.get('reset') !== '0') A.reset();
    const uid = qs.get('user') || 'u-wangmin'; A.state().me = uid; A.state().session = { userId: uid, at: Date.now() };
    const def = J.registry[APP]; if (!def) { document.body.innerHTML = '应用未注册：' + APP; return; }
    const user = A.state().users.find((u) => u.id === uid); const role = A.state().roles.find((r) => r.id === user.role);
    const can = (action, appId) => A.ext.can(appId || APP, action);
    const MASK = { phone: (v) => String(v).slice(0, 3) + '****' + String(v).slice(-4), revenue: () => '***' };
    const H = window.JKHttp;
    const kbFallback = { async search(q, o = {}) { const r = await H.post('/api/v1/kb/search', { q, space: o.space, limit: o.limit }); return { hits: (r.hits || []).map((h) => ({ id: h.id || h.fileId, title: h.title || h.name, space: h.space || h.lib, snippet: h.snippet, score: h.score, source: h.source || {} })) }; }, async ask(q) { const r = await kbFallback.search(q); return { answer: r.hits[0] ? r.hits[0].snippet + ' [1]' : '没有找到', citations: r.hits.slice(0, 3).map((h, i) => ({ n: i + 1, ...h })), confidence: 'mid' }; }, async open(id) { J.toast('打开知识库原文：' + id); window.__kbOpened = id; }, async spaces() { return []; }, async import(files) { window.__kbImported = files; return { docs: files }; } };
    const navLog = (window.__navLog = []);
    const el = document.getElementById('panel'); el.className = 'app-' + APP + ' panel scroll'; if (qs.get('pw')) { el.style.flex = 'none'; el.style.width = qs.get('pw') + 'px'; el.style.marginLeft = (qs.get('pl') || 0) + 'px'; el.style.borderLeft = '1px solid var(--border)'; el.style.borderRight = '1px solid var(--border)'; }
    let handle;
    const ui = { tag: J.tag, hue: J.hue, icon: J.icon, appIcon: J.appIcon, toast: J.toast, modal: J.modal, drawer: J.drawer, confirm: J.confirm, empty: J.empty, steps: J.steps, esc: J.esc, md: J.md, download: (n, c, m) => { navLog.push(['download', n]); J.download(n, c, m); }, fmtMoney: J.fmtMoney, fmtDate: J.fmtDate, menu: J.menu };
    const ctx = {
      api: Object.assign({}, window.JKApi, { get: H.get, post: H.post, put: H.put, patch: H.patch, del: H.del }),
      user: { ...user, roleName: role.name }, perms: { can, mask: (f, v) => (role.mask && MASK[f] ? MASK[f](v) : v), isPartner: !!role.mask },
      theme: { get: () => document.documentElement.dataset.theme, on() {} }, ui,
      nav: { open: (a, r, p) => { navLog.push(['open', a, r, p]); J.toast(`打开 ${a} · ${r || ''}`); }, go: (r, p) => handle.go(r, p), back() {}, chat: (t) => { navLog.push(['chat', t]); J.toast('发到对话：' + t); } },
      kb: J.services.kb || kbFallback, operator: { isRunning: () => false },
      chat: { post: (c) => navLog.push(['card', c]), say: (t) => navLog.push(['say', t]) }, bus: { on: J.bus.on, emit: (e, d) => { navLog.push(['bus', e]); J.bus.emit(e, d); } },
      params: JSON.parse(qs.get('params') || '{}'), audit: (a, d) => navLog.push(['audit', a, d]),
    };
    window.__ctx = ctx;
    document.getElementById('hdr').innerHTML = `<b>测试台</b> · ${J.esc(APP)} · ${J.esc(user.name)}（${J.esc(role.name)}）<span class="sp"></span><button class="btn sm" id="tg">切换主题</button>`;
    document.getElementById('tg').onclick = () => { const t = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = t; };
    handle = def.mount(el, ctx); window.__app = handle;
    if (qs.get('route')) handle.go(qs.get('route'), ctx.params);
    window.__ready = true;
  });
})();

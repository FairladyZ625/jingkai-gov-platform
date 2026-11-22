/* =====================================================================
 * AI 操作员引擎：理解一句话 → 任务清单（逐条打勾）→ 在右侧应用里用可见光标替你操作 → 人工决策点暂停。
 * 意图来源：各应用 manifest.intents + config/operator-intents.js（平台级）。
 * 实体词典（企业/会议/政策/公文）通过接口适配层加载，不读模拟数据。
 * ===================================================================== */
(function () {
  const { $, $$, h, esc, icon, sleep } = JK;
  class Stop extends Error { constructor() { super('STOP'); this.stop = true; } }
  const Op = { running: null, speed: 1, demo: false, dict: { enterprise: [], meeting: [], policy: [], doc: [] }, hooks: {} };

  /* ---------- 光标 ---------- */
  let cur, ring;
  function ensureCursor() {
    if (cur && cur.isConnected) return;
    cur = h(`<div class="op-cursor" style="left:${innerWidth / 2}px;top:${innerHeight / 2}px"><svg viewBox="0 0 24 24" width="22" height="22"><path d="M4 2l16 9.5-7 1.6-3.6 6.9z" fill="var(--accent)" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg><span class="lbl">AI 正在操作</span></div>`);
    ring = h('<div class="op-ring" style="opacity:0"></div>');
    document.body.append(ring, cur);
  }
  function hideCursor() { if (cur) cur.remove(); if (ring) ring.remove(); cur = ring = null; }
  function ringOn(el) { if (!ring || !el) return; const r = el.getBoundingClientRect(); Object.assign(ring.style, { left: r.left - 3 + 'px', top: r.top - 3 + 'px', width: r.width + 6 + 'px', height: r.height + 6 + 'px', opacity: 1 }); }
  async function moveTo(el) {
    ensureCursor(); el.scrollIntoView({ block: 'nearest', inline: 'nearest' }); await sleep(60);
    const r = el.getBoundingClientRect(); cur.style.left = Math.round(r.left + Math.min(r.width / 2, 40)) + 'px'; cur.style.top = Math.round(r.top + r.height / 2) + 'px';
    ringOn(el); await sleep(560 / Op.speed);
  }

  /* ---------- 词典 ---------- */
  Op.loadDict = async function (canView) {
    // 每次身份刷新都替换词典；旧请求只持有旧对象，不可能填回新身份。
    const H = window.JKHttp, d = Op.dict = {enterprise: [], meeting: [], policy: [], doc: []};
    const grab = async (path, map) => { try { const r = await H.get(path); return (r.items || []).map(map).filter(Boolean); } catch (e) { return []; } };
    await Promise.all([
      ['enterprise','enterprise','companies', e => ({ id: e.id, name: e.name, short: e.short || e.name, names: [e.name, e.short, ...(e.alias || e.formerNames || [])].filter(Boolean) })],
      ['meeting','meeting','meetings', m => ({ id: m.id, title: m.title, names: [m.title, m.short].filter(Boolean) })],
      ['policy','policy','items', p => ({ id: p.id, title: p.title, names: [p.title, p.short].filter(Boolean) })],
      ['doc','document','documents', x => ({ id: x.id, title: x.title, names: [x.title].filter(Boolean) })],
    ].map(async ([key, app, resource, map]) => {
      if (canView?.(app, 'view')) d[key] = await grab(`/api/apps/${app}/${resource}`, map);
    }));
  };
  function findIn(list, text) {
    let best = null, bl = 0;
    list.forEach((it) => (it.names || []).forEach((n) => { if (n && n.length >= 2 && text.includes(n) && n.length > bl) { best = it; bl = n.length; } }));
    if (!best) list.forEach((it) => (it.names || []).forEach((n) => { if (!n || n.length < 4) return; const k = n.replace(/(北京|有限|责任|股份|科技|公司|文化|传媒)/g, ''); if (k.length >= 2 && text.includes(k.slice(0, 4)) && k.length > bl) { best = it; bl = k.length; } }));
    return best;
  }
  /* 错别字 / 近音：同长度窗口里同位字 ≥ 一半且首字相同 → 候选（如 星和智架 → 星河智驾） */
  Op.fuzzyEnt = function (text) {
    let best = null;
    Op.dict.enterprise.forEach((e) => [e.short, e.name].forEach((n) => {
      if (!n || n.length < 3 || n.length > 8) return;
      for (let i = 0; i + n.length <= text.length; i++) {
        const w = text.slice(i, i + n.length); if (w[0] !== n[0]) continue;
        let same = 0; for (let k = 0; k < n.length; k++) if (w[k] === n[k]) same++;
        const sc = same / n.length; if (sc >= 0.5 && sc < 1 && (!best || sc > best.sc)) best = { ent: e, span: w, sc };
      }
    }));
    return best;
  };
  function extractSlots(text) {
    const s = {}; const d = Op.dict;
    const e = findIn(d.enterprise, text); if (e) s.ent = { id: e.id, name: e.name, short: e.short };
    const m = findIn(d.meeting, text); if (m) s.meeting = { id: m.id, title: m.title };
    const p = findIn(d.policy, text); if (p) s.policy = { id: p.id, title: p.title };
    const x = findIn(d.doc, text); if (x) s.doc = { id: x.id, title: x.title };
    const am = /(\d+(?:\.\d+)?)\s*(万|千)?\s*元?/.exec(text.replace(/,/g, '')); if (am && /\d/.test(am[1]) && /(万|元|千)/.test(am[0])) s.amount = Math.round(parseFloat(am[1]) * (am[2] === '万' ? 10000 : am[2] === '千' ? 1000 : 1));
    if (/今天/.test(text)) s.date = 'today'; else if (/昨天/.test(text)) s.date = 'yesterday';
    return s;
  }

  /* ---------- 意图 ---------- */
  const bigr = (t) => { t = t.replace(/[\s，。？！、,.?!“”"'：:（）()]/g, ''); const o = new Set(); for (let i = 0; i < t.length - 1; i++) o.add(t.slice(i, i + 2)); return o; };
  const dice = (a, b) => { if (!a.size || !b.size) return 0; let n = 0; a.forEach((x) => { if (b.has(x)) n++; }); return (2 * n) / (a.size + b.size); };
  function allIntents() {
    const out = [];
    (window.JK_PLATFORM_INTENTS || []).forEach((it) => out.push({ ...it, app: it.app || null, platform: true }));
    Object.values(JK.registry).forEach((def) => (def.manifest.intents || []).forEach((it) => out.push({ ...it, app: def.manifest.id })));
    return out;
  }
  Op.allIntents = allIntents;
  Op.understand = function (text) {
    const slots = extractSlots(text); const tb = bigr(text); const res = [];
    allIntents().forEach((it) => {
      if (it.app && !JK.registry[it.app] && !it.platform) return;
      let kw = 0; (it.keywords || []).forEach((k) => { if (text.includes(k)) kw += k.length >= 3 ? 1.4 : 1; });
      if (it.pattern && new RegExp(it.pattern).test(text)) kw += 3;
      let sim = 0; (it.examples || []).forEach((ex) => { sim = Math.max(sim, dice(tb, bigr(ex))); });
      let sb = 0; Object.keys(it.slots || {}).forEach((k) => { if (slots[k]) sb += 0.8; });
      if (it.needs && it.needs.some((k) => !slots[k])) sb -= 1.5;
      const score = kw + sim * 4 + sb + (it.boost || 0);
      if (score > 0.6) res.push({ intent: it, score, slots });
    });
    res.sort((a, b) => b.score - a.score);
    return { best: res[0] || null, alts: res.slice(1, 3), slots };
  };

  /* ---------- 运行（任务清单 + run API） ---------- */
  let latestRequest = 0;
  Op.start = async function ({ intent, slots, text, file, plan, appId, title, isCurrent = () => true, onDone }) {
    if (!isCurrent()) return;
    const request = ++latestRequest;
    if (Op.running) { Op.running.stop(true); await sleep(50); }
    if (!isCurrent() || request !== latestRequest) return;
    const steps = plan || intent.plan || ['理解需求', '执行', '完成'];
    const card = Op.hooks.postPlan({ title: title || intent.title || steps[0], appId: appId || intent.app, steps });
    const run = makeRun(card, steps, appId || intent.app, isCurrent, onDone);
    const hooks = { ...Op.hooks };
    // 平台意图同样可以在 await 之后打开面板，导航要核对这个 run 的归属。
    for (const name of ['openApp', 'openBuiltin', 'switchUser', 'reset']) {
      hooks[name] = (...args) => { run.check(); return Op.hooks[name](...args); };
    }
    Op.running = run; document.body.classList.add('op-on');
    try {
      await run.step(0);
      if (run.appId && run.appId !== 'shell') await hooks.openApp(run.appId, intent.route, { ...(intent.params || {}), via: 'operator' });
      run.check();
      const ctl = run.appId && Op.hooks.appCtl(run.appId);
      const actName = intent.action;
      if (intent.run) await intent.run({ ...slots, text, file }, run, hooks);
      else if (ctl && ctl.actions && typeof ctl.actions[actName] === 'function') await ctl.actions[actName]({ ...slots, text, file }, run);
      else if (ctl && ctl.go) { await run.step(steps.length - 1); ctl.go(intent.route || 'home', { ...slots, text }); run.done(`已打开「${(JK.registry[run.appId] || {}).manifest.name}」`); }
      if (!run.finished) run.done();
    } catch (e) {
      if (e?.stop || run.stopped || !isCurrent()) { run.markStopped(); }
      else { console.warn(e); run.fail((e && e.message) || '执行出错'); }
    } finally {
      if (Op.running === run) { Op.running = null; hideCursor(); document.body.classList.remove('op-on'); }
    }
  };

  function makeRun(card, steps, appId, isCurrent, onDone) {
    let cur = -1; const root = () => (appId && Op.hooks.appEl(appId)) || document;
    const r = {
      appId, stopped: false, finished: false,
      check() { if (r.stopped || !isCurrent()) throw new Stop(); },
      stop(silent) { r.stopped = true; r.silent = !!silent; if (r._askRes) r._askRes(null); },
      async step(i) { r.check(); for (let k = 0; k < steps.length; k++) card.set(k, k < i ? 'done' : k === i ? 'run' : 'todo'); cur = i; await r.sleep(220); },
      async find(sel, timeout = 5000) {
        const t0 = Date.now();
        for (;;) { r.check(); const el = typeof sel === 'string' ? (root().querySelector(sel) || document.querySelector(sel)) : sel; if (el && el.getClientRects().length) return el; if (Date.now() - t0 > timeout) throw new Error('界面上没找到：' + sel); await sleep(80); }
      },
      async highlight(sel, note) { const el = await r.find(sel); await moveTo(el); if (note) card.note(note); return el; },
      async scroll(sel) { const el = await r.find(sel); el.scrollIntoView({ block: 'center', behavior: 'smooth' }); await sleep(300 / Op.speed); },
      async fill(sel, text) {
        const el = await r.find(sel); await moveTo(el); el.focus(); r.check();
        const v = String(text == null ? '' : text); const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value'); const set = (x) => (setter && setter.set ? setter.set.call(el, x) : (el.value = x));
        set(''); const stepN = Math.max(1, Math.ceil(v.length / 24));
        for (let i = stepN; i <= v.length + stepN - 1; i += stepN) { r.check(); set(v.slice(0, Math.min(i, v.length))); el.dispatchEvent(new Event('input', { bubbles: true })); await sleep(28 / Op.speed); }
        el.dispatchEvent(new Event('change', { bubbles: true })); await sleep(120 / Op.speed); return el;
      },
      async click(sel) {
        const el = await r.find(sel); await moveTo(el); r.check();
        const rc = el.getBoundingClientRect(); const rp = h(`<div class="op-click" style="left:${rc.left + Math.min(rc.width / 2, 40)}px;top:${rc.top + rc.height / 2}px"></div>`); document.body.appendChild(rp); setTimeout(() => rp.remove(), 600);
        el.click(); await sleep(260 / Op.speed); return el;
      },
      async select(sel, value) { const el = await r.find(sel); await moveTo(el); r.check(); el.value = value; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); await sleep(200 / Op.speed); return el; },
      async wait(cond, timeout = 8000) { const t0 = Date.now(); for (;;) { r.check(); let ok = false; try { ok = typeof cond === 'string' ? !!(root().querySelector(cond) || document.querySelector(cond)) : await cond(); } catch (e) {} if (ok) return ok; if (Date.now() - t0 > timeout) throw new Error('等待超时'); await sleep(100); } },
      sleep: (ms) => sleep(ms / Op.speed).then(() => r.check()),
      say(text) { card.note(text); },
      async ask(q, options = ['确认', '取消']) {
        r.check(); if (cur >= 0) card.set(cur, 'wait');
        const p = new Promise((res) => { r._askRes = res; card.ask(q, options, (o) => res(o)); });
        const cancelPick = Op.demo && window.JKDemo?.scheduleChoice(() => card.pick(options[0]));
        const ans = await p; if (cancelPick) cancelPick(); r._askRes = null; r.check(); if (cur >= 0) card.set(cur, 'run'); return ans;
      },
      done(summary, next, extra) { if (r.finished) return; r.check(); onDone?.(); r.finished = true; for (let k = 0; k < steps.length; k++) card.set(k, 'done'); card.finish('done'); const sens = appId === 'enterprise' ? { model: 'Qwen3-32B（本地）', routeNote: '涉及企业台账，已自动走本地模型，数据不出局' } : {}; if (summary || next) Op.hooks.postAI({ text: summary || '已完成。', next: next || [], ...sens, ...(extra || {}) }); JK.bus.emit('op:done', { appId }); },
      fail(msg) { if (r.finished) return; if (r.stopped || !isCurrent()) return r.markStopped(); r.finished = true; if (cur >= 0) card.set(cur, 'fail'); card.finish('fail'); Op.hooks.postAI({ text: `没能完成：${msg}。你可以在右侧自己接着操作。` }); JK.bus.emit('op:done', { appId, fail: true }); },
      markStopped() { if (r.finished) return; r.finished = true; card.finish('stopped'); if (!r.silent && isCurrent()) Op.hooks.postAI({ text: '已停下，右侧保持当前进度，你可以自己接着操作。' }); JK.bus.emit('op:done', { appId, stopped: true }); },
    };
    card.onStop = () => r.stop();
    return r;
  }

  /* ---------- 文件识别与投递 ---------- */
  Op.classify = function (file) {
    const name = file.name || ''; const ext = (file.ext || (name.split('.').pop() || '')).toLowerCase(); const text = (file.text || '').slice(0, 4000);
    const cands = [];
    Object.values(JK.registry).forEach((def) => (def.manifest.accepts || []).forEach((a) => {
      let s = 0; if ((a.ext || []).includes(ext)) s += 2;
      const re = a.match instanceof RegExp ? a.match : a.match ? new RegExp(a.match) : null;
      if (re && re.test(name)) s += 3; if (re && text && re.test(text)) s += 1.5;
      if (a.kind && file.kind && a.kind === file.kind) s += 4;
      if (s >= 2) cands.push({ app: def.manifest.id, accept: a, score: s + (a.weight || 0) });
    }));
    cands.sort((x, y) => y.score - x.score);
    return cands;
  };

  window.JKOp = Op;
})();

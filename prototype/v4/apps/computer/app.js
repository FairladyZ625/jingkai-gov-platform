/* =====================================================================
 * 电脑操作 computer —— AI 替你操作其它网站和系统（登录、填表、下载、查进度）
 * 规则（服务端也强制）：提交 / 签章 / 付款 / 验证码 / 入库 前必须停下来等人确认；
 *                    敏感字段打码；每一步写审计并留截图；随时可“暂停 / 我来接手 / 停止”。
 * 界面只调 ctx.api.computer（api/computer.js）；被操作系统的画面由 sites.js 画出（模拟）。
 * ===================================================================== */
(function () {
  const STATUS = { running: '执行中', paused: '已暂停', manual: '你在操作', waiting: '需人工确认', done: '已完成', draft: '已暂存', stopped: '已停止', failed: '失败' };
  const HUE = { running: 'blue', paused: 'gray', manual: 'violet', waiting: 'amber', done: 'green', draft: 'gray', stopped: 'gray', failed: 'red' };

  JK.registerApp({
    manifest: {
      id: 'computer', name: '电脑操作', short: '电脑', icon: 'computer', hue: 'amber', version: '1.0.0', owner: 'AI 工作组',
      summary: 'AI 替你操作网页和业务系统', routes: ['home', 'setup', 'run', 'replay', 'runs', 'systems'],
      perms: { view: '查看操作记录', operate: '发起电脑操作任务', approve: '—', admin: '管理系统授权' },
      tools: [{ name: 'computer.start', desc: '让 AI 去某个系统完成任务（提交前停下）', params: { task: 'apply|stats|notice|status', ent: 'string' } }],
      intents: [
        { id: 'computer.apply', examples: ['帮我把纸鹿二号智驾的申报表填了', '去政策兑现平台帮折页五号大模型填申报'], keywords: ['申报表', '填申报', '帮我填', '代填', '兑现平台'], slots: { ent: 'enterprise' }, action: 'apply', plan: ['登录申报平台', '找到申报事项', '用台账填好申报表', '停在提交前等你确认', '提交并取回执'] },
        { id: 'computer.stats', examples: ['帮书香里把统计月报填了', '去直报平台填 10 月月报'], keywords: ['月报', '直报', '统计填报', '统计报表'], slots: { ent: 'enterprise' }, action: 'stats', plan: ['登录直报平台', '按台账填数', '平台数据审核', '停在上报前等你确认'] },
        { id: 'computer.notice', examples: ['去官网把最新的申报通知下载下来存到知识库', '下载最新通知入库'], keywords: ['下载通知', '最新通知', '官网通知', '通知入库', '存到知识库'], action: 'notice', plan: ['打开官网通知公告', '找到最新申报通知', '下载原文', '存进知识库'] },
        { id: 'computer.status', examples: ['查一下纸鹿二号智驾的申报进度', '书香里的补贴办到哪一步了'], keywords: ['申报进度', '办到哪', '审核进度', '办理进度'], slots: { ent: 'enterprise' }, action: 'status', plan: ['登录申报平台', '打开我的申报', '读取办理状态'] },
        { id: 'computer.run', examples: ['帮我去系统里操作一下', '打开电脑操作'], keywords: ['电脑操作', '帮我登录', '去系统', '去网站'], action: 'run', plan: ['识别要去的系统', '打开系统', '按步骤操作', '关键步骤等你确认'] },
      ],
      starters: ['帮我把纸鹿二号智驾的申报表填了', '去官网把最新的申报通知下载下来存到知识库'],
      demo: [
        { title: 'AI 代填申报表（停在提交前）', say: '帮我把纸鹿二号智驾的申报表填了' },
        { title: '下载官网通知并入库', say: '去官网把最新的申报通知下载下来存到知识库' },
      ],
    },

    mount(el, ctx) {
      const { esc, tag, icon, toast } = ctx.ui;
      const API = (ctx.api && ctx.api.computer) || (window.JKApi && window.JKApi.computer);
      const KBAPI = (ctx.api && ctx.api.kb) || (window.JKApi && window.JKApi.kb);
      const SITES = window.JKCuSites;
      const sleepRaw = (ms) => new Promise((r) => setTimeout(r, ms));
      const st = { view: 'home', tab: 'tasks', tasks: [], systems: [], runs: [], ents: [], setup: null, text: '', replay: null, shotSel: 0 };
      let P = null; // 正在播放的任务
      let alive = true;
      const fast = () => !!(window.JK_DEMO_FAST || (ctx.operator && ctx.operator.fast && ctx.operator.fast()));
      const sleep = (ms) => sleepRaw(fast() ? Math.min(ms, 80) : ms);
      const canOp = () => ctx.perms.can('operate', 'computer');

      async function load() {
        if (!ctx.perms.can('view', 'computer')) return;
        const [t, r] = await Promise.all([API.tasks(), API.runs()]);
        st.tasks = t.items; st.systems = t.systems; st.runs = r.items;
        if (!st.ents.length) { try { const e = await ctx.api.get('/api/apps/enterprise/companies'); st.ents = (e.items || []).map((x) => ({ id: x.id, short: x.short, name: x.name })); } catch (e) { st.ents = []; } }
      }
      const tagS = (s) => `<span class="tag dot" data-hue="${HUE[s] || 'gray'}">${STATUS[s] || s}</span>`;
      const head = (right) => `<div class="app-head cu-head">${ctx.ui.appIcon('computer', 'lg')}<div class="grow"><h2 class="h2">电脑操作</h2><div class="t-3 t-sm">AI 替你操作网页和业务系统，关键一步你说了算</div></div>${right || ''}</div>`;
      const back = (label) => `<button class="btn ghost sm cu-back" data-back>${icon('chevron-right')}${label || '电脑操作'}</button>`;

      function render() {
        if (!alive) return;
        if (st.view === 'run' && P) return renderRun();
        if (st.view === 'replay' && st.replay) return renderReplay();
        if (st.view === 'setup' && st.setup) return renderSetup();
        if (!ctx.perms.can('view', 'computer')) { el.innerHTML = `<div class="cu-wrap">${head()}${ctx.ui.empty({ icon: 'lock', title: '没有电脑操作权限', desc: '请联系管理员开通' })}</div>`; return; }
        const n = st.runs.length;
        el.innerHTML = `<div class="cu-wrap">${head()}
          <div class="tabs cu-tabs">${[['tasks', '新任务'], ['runs', '操作记录', n], ['systems', '系统授权']].map(([v, l, c]) => `<button class="tab ${st.tab === v ? 'on' : ''}" data-tab="${v}" data-op="computer.tab.${v}">${l}${c ? `<span class="count muted">${c}</span>` : ''}</button>`).join('')}</div>
          ${st.tab === 'runs' ? viewRuns() : st.tab === 'systems' ? viewSystems() : viewTasks()}</div>`;
        bindHome();
      }
      function viewTasks() {
        return `<div class="cu-ask"><div class="row gap2"><div class="search grow">${icon('sparkles')}<input class="input" data-op="computer.ask" data-ask placeholder="告诉 AI 要去哪个系统做什么，例如：帮纸鹿二号智驾填申报表" value="${esc(st.text)}"></div><button class="btn primary" data-go data-op="computer.go">开始</button></div></div>
          <div class="sect">常用任务</div><div class="grid g2 cu-tasks">${st.tasks.map((t) => `<div class="card hoverable cu-task" data-task="${t.id}" data-op="computer.task.${t.id}"><div class="row gap3"><span class="app-ico h-amber">${icon(t.icon)}</span><div class="grow"><div class="cu-name">${esc(t.title)}</div><div class="t-3 t-xs clip">${esc((st.systems.find((s) => s.id === t.system) || {}).name || '')}</div></div>${icon('chevron-right')}</div>
            <div class="t-2 t-sm">${esc(t.desc)}</div><div class="row cu-stop">${icon('hand')}<span>${esc(t.stop)}</span></div></div>`).join('')}</div>`;
      }
      function viewRuns() {
        if (!st.runs.length) return ctx.ui.empty({ icon: 'history', title: '还没有操作记录', desc: '每次 AI 操作都会留下步骤截图和日志' });
        return `<div class="card flat"><div class="list lined">${st.runs.map((r) => `<div class="li" data-replay="${r.id}"><span class="app-ico sm h-amber">${icon('computer')}</span><div class="grow"><div class="ttl clip">${esc(r.title)}</div><div class="meta">${esc(r.created)} · ${esc(r.by)} · ${r.shotCount} 张截图${r.from ? ' · 来自技能「' + esc(r.from) + '」' : ''}</div></div>${tagS(r.status)}${icon('chevron-right')}</div>`).join('')}</div></div>`;
      }
      function viewSystems() {
        return `<div class="col gap3"><div class="callout h-amber">${icon('shield')}<div class="grow"><b>提交、签章、付款、验证码</b> 必须由你确认，AI 不会自己点。这条规则不能关闭。</div></div>
          <div class="card flat"><div class="list lined">${st.systems.map((s) => `<div class="li cu-sys"><span class="app-ico sm h-gray">${icon('globe')}</span><div class="grow"><div class="ttl">${esc(s.name)}</div><div class="meta mono clip">${esc(s.url)}</div></div><div class="cu-acc t-3 t-xs">${icon('key')}${esc(s.account)}</div>${tag(s.kind, null, { hue: 'gray', cls: 'plain' })}<span class="switch ${s.allowed ? 'on' : ''}" data-sys="${s.id}" title="${s.allowed ? '允许 AI 使用' : '已停止'}" role="switch"></span></div>`).join('')}</div></div>
          <div class="t-3 t-xs">账号密码存放在保管箱，AI 只能调用、看不到明文。</div></div>`;
      }
      function bindHome() {
        el.querySelectorAll('[data-tab]').forEach((b) => (b.onclick = () => { st.tab = b.dataset.tab; render(); }));
        el.querySelectorAll('[data-task]').forEach((b) => (b.onclick = () => openSetup(b.dataset.task)));
        el.querySelectorAll('[data-replay]').forEach((b) => (b.onclick = () => openReplay(b.dataset.replay)));
        el.querySelectorAll('[data-sys]').forEach((b) => (b.onclick = async () => { const s = st.systems.find((x) => x.id === b.dataset.sys); try { const r = await API.setSystem(s.id, !s.allowed); s.allowed = r.item.allowed; toast(s.allowed ? `已允许 AI 使用「${s.name}」` : `已停止 AI 使用「${s.name}」`); render(); } catch (e) { toast(e.message, { type: 'err' }); } }));
        const ask = el.querySelector('[data-ask]'); if (ask) { ask.oninput = () => (st.text = ask.value); ask.onkeydown = (e) => { if (e.key === 'Enter') el.querySelector('[data-go]').click(); }; }
        const go = el.querySelector('[data-go]'); if (go) go.onclick = async () => { const t = (st.text || '').trim(); if (!t) return toast('说说要去哪个系统做什么', { type: 'warn' }); const m = await API.match(t); if (!m.task) return toast('没听懂要做哪件事，可以直接点下面的任务', { type: 'warn' }); openSetup(m.task.id, { ent: m.entId }); };
      }

      /* ---------- 准备：选企业，看 AI 会做哪几步 ---------- */
      function abandon() { if (P && ['running', 'paused', 'manual', 'waiting'].includes(P.status)) { P.stopped = true; P.paused = false; P.manual = false; if (P.resolveWait) P.resolveWait('__stop'); } }
      let NAV = 0; // 导航序号：异步 go() 返回时若已被别的导航取代则不再覆盖
      function openSetup(taskId, o) { NAV++; abandon(); const t = st.tasks.find((x) => x.id === taskId); st.setup = { task: t, ent: (o && o.ent) || '', month: '2026 年 10 月' }; st.view = 'setup'; render(); }
      const PREVIEW = { apply: [['登录统一身份认证', 'lock'], ['输入短信验证码', 'hand'], ['找到申报事项'], ['填写企业信息'], ['填写申报内容、上传材料'], ['停在“提交”前', 'hand'], ['提交并取回执']], stats: [['登录统一身份认证', 'lock'], ['输入短信验证码', 'hand'], ['打开本月报表'], ['按台账填数'], ['平台数据审核'], ['停在“上报”前', 'hand']], notice: [['打开官网通知公告'], ['找到最新申报通知'], ['读通知要点'], ['下载原文'], ['存进知识库', 'hand']], status: [['登录统一身份认证', 'lock'], ['输入短信验证码', 'hand'], ['打开“我的申报”'], ['读取办理状态']] };
      function renderSetup() {
        const s = st.setup, t = s.task;
        el.innerHTML = `<div class="cu-wrap">${back()}<div class="row gap3 cu-sh"><span class="app-ico lg h-amber">${icon(t.icon)}</span><div class="grow"><h2 class="h2">${esc(t.title)}</h2><div class="t-3 t-sm">${esc((st.systems.find((x) => x.id === t.system) || {}).name)}</div></div></div>
          <div class="grid cu-setup"><div class="card col gap4">
            ${t.needsEnt ? `<div class="field"><label>为哪家企业办</label><select class="select" data-ent data-op="computer.ent"><option value="">选择企业…</option>${st.ents.map((e) => `<option value="${e.id}" ${s.ent === e.id ? 'selected' : ''}>${esc(e.short)}　${esc(e.name)}</option>`).join('')}</select><div class="hint">AI 会用这家企业在台账里的数据来填</div></div>` : ''}
            ${t.id === 'stats' ? `<div class="field"><label>填报月份</label><input class="input" data-month value="${esc(s.month)}"></div>` : ''}
            ${!t.needsEnt && t.id !== 'stats' ? `<div class="t-2 t-sm">不需要登录，AI 会找到最新一条申报通知</div>` : ''}
            <div class="row"><span class="sp"></span><button class="btn primary" data-start data-op="computer.start">${icon('play')}开始操作</button></div></div>
            <div class="card cu-plan"><div class="cu-sec-h">AI 会这样做</div><div class="cu-prev">${PREVIEW[t.id].map(([l, ic], i) => `<div class="cu-prev-i ${ic === 'hand' ? 'human' : ''}"><span class="cu-n">${i + 1}</span><span class="grow">${esc(l)}</span>${ic === 'hand' ? `<span class="t-xs cu-you">${icon('hand')}你来确认</span>` : ''}</div>`).join('')}</div></div></div></div>`;
        el.querySelector('[data-back]').onclick = () => { st.view = 'home'; render(); };
        const se = el.querySelector('[data-ent]'); if (se) se.onchange = () => (s.ent = se.value);
        const mo = el.querySelector('[data-month]'); if (mo) mo.oninput = () => (s.month = mo.value);
        el.querySelector('[data-start]').onclick = () => start(t.id, { ent: s.ent, month: s.month });
      }

      /* ---------- 播放：AI 一步步操作 ---------- */
      async function start(task, params, run) {
        const body = Object.assign({ task }, params || {});
        if (body.ent === '') delete body.ent;
        let r; try { r = (await API.start(body)).item; } catch (e) { toast(e.message, { type: 'err' }); if (run) run.fail(e.message); return null; }
        P = { run: r, step: 0, page: null, vals: {}, checks: {}, ups: {}, corp: false, otpSent: false, verify: false, downloaded: false, shots: r.shots || [], status: r.status || 'running', op: null, stopped: false, paused: false, manual: false, chatRun: run || null, waitMsg: '', resolveWait: null, note: '', gen: ++GEN };
        const me = P; st.view = 'run'; render();
        try { await play(); } catch (e) { if (e !== 'STOP') { me.status = 'failed'; try { await API.report(r.id, { status: 'stopped' }); } catch (_) {} } else if (me.status !== 'stopped' && me.status !== 'draft' && me.status !== 'done') { me.status = 'stopped'; try { await API.report(r.id, { status: 'stopped' }); } catch (_) {} } }
        if (P === me && st.view === 'run') renderRun(); load().catch(() => {});
        return me;
      }
      const stepsOf = () => P.run.steps;
      let GEN = 0;
      async function hold() { if (P && P.gen !== GEN) throw 'STOP'; while (P.paused || P.manual) { await sleepRaw(150); if (P.stopped) throw 'STOP'; } if (P.stopped || !alive) throw 'STOP'; if (P.chatRun && P.chatRun.stopped) { P.stopped = true; throw 'STOP'; } }
      async function playServer() {
        const labels = { otp: '验证码核验', sign: '签章', pay: '付款', submit: '提交', import: '入库' };
        while (P && !P.stopped) {
          const item = (await API.run(P.run.id)).item;
          P.run = item;
          P.shots = item.shots || [];
          P.step = item.step || 0;
          P.status = item.status;
          if (item.status === 'waiting' && item.pending) {
            const kind = item.pending.kind;
            const label = labels[kind] || kind;
            const opts = ['确认并继续', '停止'];
            P.waitKind = kind === 'otp' ? 'otp' : 'gate';
            P.waitMsg = 'AI 已停在「' + label + '」前，请确认后再继续。';
            P.waitOpts = opts;
            hideCursor();
            if (st.view === 'run') renderRun();
            let ans;
            if (P.chatRun) ans = await P.chatRun.ask(P.waitMsg, opts);
            else ans = await new Promise((res) => (P.resolveWait = res));
            P.resolveWait = null;
            P.waitMsg = '';
            if (P.stopped) { try { await API.confirm(item.id, { decision: 'decline' }); } catch (_) {} throw 'STOP'; }
            const ok = ans === opts[0];
            const res = await API.confirm(item.id, ok ? { decision: 'approve', kind } : { decision: 'decline' });
            P.run = res.item;
            P.status = res.item.status;
            if (!ok) { P.status = res.item.status || 'stopped'; throw 'STOP'; }
          } else if (['done', 'stopped', 'failed'].includes(item.status)) {
            if (item.task === 'notice' && item.result && (item.result.docs || []).length) P.imported = true;
            if (st.view === 'run') renderRun();
            return;
          } else {
            if (st.view === 'run') renderRun();
            await sleep(400);
          }
        }
      }
      async function play() {
        if (!(P.run.steps && P.run.steps.length)) return playServer();
        const steps = stepsOf();
        for (let i = P.step; i < steps.length; i++) {
          P.step = i; const s = steps[i];
          if (s.page !== P.page) { P.page = s.page; P.url = s.url || P.url; drawPage(); await sleep(450); }
          drawChrome();
          for (const op of s.ops) { await hold(); P.op = op; await doOp(op, s); if (P.status === 'draft') { drawChrome(); return; } }
          await capture(i); await API.report(P.run.id, { step: i + 1, log: s.title + ' ✓', shot: P.shots[i], shotIdx: i });
          await sleep(200);
        }
        P.step = steps.length; P.status = 'done'; P.op = null; hideCursor();
        await API.report(P.run.id, { status: 'done', log: '任务完成' });
        drawChrome();
      }
      const vp = () => el.querySelector('[data-vp]');
      const vEl = (sel) => vp() && vp().querySelector(`[data-vc="${sel}"]`);
      function drawPage() { const box = vp(); if (!box) return; box.innerHTML = SITES.render(P.page, P.run, P); const u = el.querySelector('[data-url]'); if (u) u.textContent = P.url || ''; box.scrollTop = 0; }
      async function cursorTo(target) {
        const box = vp(); if (!box || !target) return; const cur = el.querySelector('[data-cur]'); const frame = el.querySelector('[data-frame]');
        const tr = target.getBoundingClientRect(), br = box.getBoundingClientRect();
        if (tr.top < br.top + 20 || tr.bottom > br.bottom - 20) { box.scrollTop += tr.top - br.top - box.clientHeight / 3; await sleep(200); }
        const t2 = target.getBoundingClientRect(), fr = frame.getBoundingClientRect();
        cur.style.opacity = 1; cur.style.left = (t2.left - fr.left + Math.min(28, t2.width / 2)) + 'px'; cur.style.top = (t2.top - fr.top + t2.height / 2) + 'px';
        box.querySelectorAll('.vs-focus').forEach((x) => x.classList.remove('vs-focus')); target.classList.add('vs-focus');
        await sleep(560);
      }
      function hideCursor() { const c = el.querySelector('[data-cur]'); if (c) c.style.opacity = 0; }
      function ripple() { const c = el.querySelector('[data-cur]'); if (!c) return; const r = document.createElement('span'); r.className = 'cu-rip'; c.appendChild(r); setTimeout(() => r.remove(), 500); }
      function bubble(text) { P.note = text; const b = el.querySelector('[data-bubble]'); if (b) { b.textContent = text; b.classList.toggle('on', !!text); } }
      async function doOp(op, s) {
        drawChrome(); bubble(op.note || '');
        if (op.op === 'type') {
          const x = vEl(op.sel); await cursorTo(x); ripple(); const val = String(op.value || ''); const show = op.mask === 'pwd' ? '••••••••' : val;
          if (x) { x.value = ''; const stepN = fast() ? Math.max(1, Math.ceil(show.length / 3)) : 1; for (let i = 0; i < show.length; i += stepN) { await hold(); x.value = show.slice(0, i + stepN); await sleepRaw(fast() ? 8 : 28); } x.value = show; }
          P.vals[op.sel] = show; await logOp(`填写 ${op.note || op.sel}：${op.mask === 'pwd' ? '（保管箱密码，已隐藏）' : show}`);
        } else if (op.op === 'click') {
          const x = vEl(op.sel); await cursorTo(x); ripple(); await sleep(180);
          if (op.sel === 'tab-corp') { P.corp = true; drawPage(); }
          if (op.sel === 'getotp') { P.otpSent = true; drawPage(); }
          if (op.sel === 'verify') { P.verify = true; drawPage(); }
          await logOp('点击 ' + (op.note || (x ? x.textContent.trim().slice(0, 16) : op.sel)));
        } else if (op.op === 'upload') { const x = vEl(op.sel); await cursorTo(x); ripple(); P.ups[op.sel] = op.value; drawPage(); await logOp('上传 ' + op.value); }
        else if (op.op === 'check') { const x = vEl(op.sel); await cursorTo(x); ripple(); P.checks[op.sel] = true; drawPage(); await logOp(op.note || '勾选'); }
        else if (op.op === 'read') { hideCursor(); await sleep(900); await logOp(op.note || '读取页面'); }
        else if (op.op === 'hl') { const x = vEl(op.sel); await cursorTo(x); await sleep(500); await logOp(op.note); }
        else if (op.op === 'download') { const x = vEl(op.sel); await cursorTo(x); ripple(); P.downloaded = true; drawPage(); await logOp('下载 ' + op.value); }
        else if (op.op === 'otp') {
          const x = vEl(op.sel); await cursorTo(x);
          const ok = await human('otp', op.note + '。验证码只能你来输入。', ['我已输入验证码，继续', '取消任务']);
          if (!ok) return stopTask('你取消了登录');
          if (x) x.value = '••••••'; P.vals.otp = '••••••'; await logOp('验证码已由你输入', ctx.user.name);
        } else if (op.op === 'gate') {
          const x = vEl(op.sel); await cursorTo(x);
          const ok = await human('gate', `AI 已填好，停在「${op.kind}」前。请核对${P.chatRun ? "右侧" : "下方"}页面，确认后才会${op.kind}。`, [`确认${op.kind}`, `先暂存，不${op.kind}`]);
          if (!ok) { const sv = vEl('save'); await cursorTo(sv); ripple(); await API.confirm(P.run.id, { decision: 'decline', kind: op.kind }); P.status = 'draft'; await capture(P.step); await API.report(P.run.id, { status: 'draft', shot: P.shots[P.step], shotIdx: P.step }); hideCursor(); return; }
          ripple(); const r = await API.confirm(P.run.id, { decision: 'approve', kind: op.kind }); P.run.result = r.item.result; await sleep(300);
        } else if (op.op === 'kb') {
          const ok = await human('import', `把《${(P.run.notice || {}).title || '通知'}》存进知识库「政策库」？`, ['存入知识库', '不用了']);
          if (!ok) { await logOp('你选择不入库', ctx.user.name); return; }
          try { const n = P.run.notice || {}; const txt = [n.title, n.org ? '发布单位：' + n.org : '', n.date ? '发布日期：' + n.date : '', n.window ? `申报时间：${n.window.start} 至 ${n.window.end}` : '', (n.basis || []).map((x) => `依据：${x.title}${x.no ? '（' + x.no + '）' : ''}`).join('\n'), n.excerpt || ''].filter(Boolean).join('\n');
            const r = await KBAPI.import({ space: 'policy', from: '电脑操作', items: [{ name: n.title + '.html', text: txt, url: n.url, from: '官网下载', meta: { title: n.title, org: n.org, date: n.date, space: 'policy', kind: '申报通知' } }] });
            const added = r && r.docs && r.docs.length; ctx.bus && ctx.bus.emit('kb:changed');
            await logOp(added ? '已存入知识库「政策库」' : '知识库里已有这份通知，没有重复入库'); toast(added ? '已存入知识库' : '知识库里已有，未重复入库'); P.imported = true; P.kbDoc = added ? r.docs[0].id : null; }
          catch (e) { await logOp('入库失败：' + (e.message || e)); toast(e.message || '入库失败', { type: 'err' }); }
        }
      }
      async function logOp(text, who) { P.lastLog = text; await API.report(P.run.id, { log: text, who }); const lg = el.querySelector('[data-lastlog]'); if (lg) lg.textContent = text; }
      /* 人工确认点：由对话（操作员 run.ask）或面板里的按钮回答 */
      async function human(kind, msg, opts) {
        P.status = 'waiting'; P.waitKind = kind; P.waitMsg = msg; P.waitOpts = opts; hideCursor(); await API.report(P.run.id, { status: 'waiting' }); drawChrome();
        let ans;
        if (P.chatRun) ans = await P.chatRun.ask(msg, opts);
        else ans = await new Promise((res) => (P.resolveWait = res));
        P.resolveWait = null; if (P.stopped) throw 'STOP'; P.status = 'running'; P.waitMsg = ''; await API.report(P.run.id, { status: 'running' }); drawChrome();
        return ans === opts[0];
      }
      async function stopTask(why) { P.stopped = true; P.status = 'stopped'; hideCursor(); await API.report(P.run.id, { status: 'stopped', log: why || '已停止', who: ctx.user.name }); drawChrome(); throw 'STOP'; }
      async function capture(i) {
        const box = vp(); if (!box) return; const c = box.cloneNode(true);
        c.querySelectorAll('input').forEach((x, k) => { const live = box.querySelectorAll('input')[k]; let val = live ? live.value : ''; if (x.dataset.mask === 'pwd' || x.dataset.mask === 'otp') val = val ? '••••••' : ''; x.setAttribute('value', val); });
        c.querySelectorAll('.vs-focus').forEach((x) => x.classList.remove('vs-focus'));
        P.shots[i] = c.innerHTML; drawStrip();
      }

      /* ---------- 播放界面 ---------- */
      function renderRun() {
        const r = P.run;
        el.innerHTML = `<div class="cu-wrap cu-runw">${back()}<div class="cu-rh"><div class="cu-rh-t"><div class="h3 clip">${esc(r.title)}</div><div class="t-3 t-xs clip">${esc(r.system.name)}${r.from ? ' · 来自技能「' + esc(r.from) + '」' : ''}</div></div><div class="cu-bar"><span data-st></span><span data-ctl class="row gap2"></span></div></div>
          <div data-wait></div>
          <div data-theme="light" class="cu-browser" data-frame><div class="cu-chrome"><span class="cu-dots"><i></i><i></i><i></i></span><span class="cu-url">${icon('lock')}<span data-url class="clip">${esc(P.url || r.system.url)}</span></span><span class="cu-live" data-live></span></div>
            <div class="cu-vp scroll" data-vp></div><div class="cu-shield" data-shield></div><div class="cu-cur" data-cur><svg viewBox="0 0 24 24" width="22" height="22"><path d="M4 2l16 10-7 1.5L9 21z" fill="var(--t-amber-fg)" stroke="var(--surface)" stroke-width="1.5"/></svg><span>AI</span></div><div class="cu-bubble" data-bubble></div></div>
          <div class="row cu-now"><span class="t-3 t-xs">刚才：</span><span class="t-2 t-sm clip grow" data-lastlog>${esc(P.lastLog || '准备中')}</span></div>
          <div class="cu-strip" data-strip></div></div>`;
        el.querySelector('[data-back]').onclick = () => { st.view = 'home'; st.tab = 'runs'; load().then(render); };
        if (P.page) drawPage(); drawChrome(); drawStrip(); if (P.note) bubble(P.note);
      }
      function drawChrome() {
        if (!P || st.view !== 'run') return; const box = el.querySelector('[data-st]'); if (!box) return;
        const steps = stepsOf(); const s = P.status; const total = steps.length; const cur = Math.min(P.step + (s === 'done' ? 0 : 1), total);
        box.className = "cu-st"; box.innerHTML = `${tagS(s)}<span class="t-3 t-xs cu-stepn clip">${s === 'done' ? '全部完成' : `第 ${cur}/${total} 步 · ${esc((steps[P.step] || {}).title || '')}`}</span>`;
        const live = el.querySelector('[data-live]'); if (live) live.innerHTML = s === 'running' ? '<i></i>AI 操作中' : s === 'manual' ? '<i class="m"></i>你在操作' : '';
        const ctl = el.querySelector('[data-ctl]');
        const active = ['running', 'paused', 'manual', 'waiting'].includes(s);
        ctl.innerHTML = active ? `${s === 'manual' ? `<button class="btn sm soft" data-ctl-a="back" data-op="computer.handback">${icon('play')}交还 AI</button>` : `<button class="btn sm" data-ctl-a="${s === 'paused' ? 'resume' : 'pause'}" data-op="computer.pause" ${s === 'waiting' ? 'disabled' : ''}>${icon(s === 'paused' ? 'play' : 'pause')}${s === 'paused' ? '继续' : '暂停'}</button><button class="btn sm" data-ctl-a="take" data-op="computer.takeover" ${s === 'waiting' ? 'disabled' : ''}>${icon('hand')}我来接手</button>`}<button class="btn sm ghost danger" data-ctl-a="stop" data-op="computer.stop">${icon('stop')}停止</button>`
          : `<button class="btn sm" data-ctl-a="again">${icon('refresh')}再来一次</button>${s === 'done' && P.run.task === 'apply' ? `<button class="btn sm soft" data-ctl-a="status">${icon('search')}查进度</button>` : ''}`;
        ctl.querySelectorAll('[data-ctl-a]').forEach((b) => (b.onclick = () => control(b.dataset.ctlA)));
        el.querySelector('[data-frame]').classList.toggle('manual', s === 'manual');
        el.querySelector('[data-shield]').style.display = s === 'manual' || !active ? 'none' : '';
        const w = el.querySelector('[data-wait]');
        if (s === 'waiting') {
          const lockIc = P.waitKind === 'gate' ? 'shield' : P.waitKind === 'otp' ? 'key' : 'book';
          w.innerHTML = `<div class="callout h-amber cu-wait" data-op="computer.wait">${icon(lockIc)}<div class="grow"><b>${P.waitKind === 'gate' ? '需要你确认' : P.waitKind === 'otp' ? '需要你输入验证码' : '要存进知识库吗'}</b><div class="t-sm">${esc(P.waitMsg)}</div>${P.waitKind === 'gate' ? summaryHtml() : ''}</div>
            ${P.chatRun ? '<span class="t-xs t-2">在左侧对话里确认</span>' : `<div class="col gap2"><button class="btn sm primary" data-w="0" data-op="computer.confirm">${esc(P.waitOpts[0])}</button><button class="btn sm" data-w="1">${esc(P.waitOpts[1])}</button></div>`}</div>`;
          w.querySelectorAll('[data-w]').forEach((b) => (b.onclick = () => P.resolveWait && P.resolveWait(P.waitOpts[+b.dataset.w])));
        } else if (s === 'done') {
          const r = P.run; const res = r.result;
          w.innerHTML = `<div class="callout h-green cu-wait">${icon('check')}<div class="grow"><b>${r.task === 'apply' ? '已提交，受理编号 ' + esc(res && res.no) : r.task === 'stats' ? '月报已上报' : r.task === 'notice' ? (P.imported ? '通知已存进知识库' : '通知已下载') : '进度已读取'}</b><div class="t-sm t-2">${r.task === 'status' ? (r.apps || []).map((a) => esc(a.title.slice(0, 14) + '：' + a.status)).join('；') : '步骤截图与日志已留档，可在“操作记录”查看'}</div></div>${P.kbDoc ? `<button class="btn sm" data-kbopen data-op="computer.kbopen">在知识库打开</button>` : ''}</div>`;
          const kb = w.querySelector('[data-kbopen]'); if (kb) kb.onclick = () => ctx.kb && ctx.kb.open(P.kbDoc);
        } else if (s === 'draft') w.innerHTML = `<div class="callout h-gray cu-wait">${icon('info')}<div class="grow"><b>已暂存，没有提交</b><div class="t-sm t-2">稍后可以在系统里继续，或让 AI 再来一次</div></div></div>`;
        else if (s === 'stopped') w.innerHTML = `<div class="callout h-gray cu-wait">${icon('stop')}<div class="grow"><b>已停止</b><div class="t-sm t-2">之前的步骤截图已留档</div></div></div>`;
        else if (s === 'manual') w.innerHTML = `<div class="callout h-violet cu-wait">${icon('hand')}<div class="grow"><b>你在操作</b><div class="t-sm t-2">可以直接在下面的页面里改。改好后点“交还 AI”，它从当前步骤接着做</div></div></div>`;
        else w.innerHTML = '';
      }
      function summaryHtml() {
        const pick = ['name', 'phone', 'proj', 'amount', 'revm', 'emp', 'period', 'wage']; const f = (P.run.fields || []).filter((x) => pick.includes(x[0])).slice(0, 5);
        return `<div class="cu-sum">${f.map(([k, l]) => `<div><span>${esc(l.replace(/（.*）/, ''))}</span><b>${esc(P.vals[k] || '—')}${P.vals[k] && /（元）/.test(l) ? ' 元' : P.vals[k] && /万元/.test(l) ? ' 万元' : ''}</b></div>`).join('')}${P.run.task === 'apply' ? `<div><span>材料</span><b>${Object.keys(P.ups).length} 份已上传</b></div>` : ''}</div>`;
      }
      function drawStrip() {
        const box = el.querySelector('[data-strip]'); if (!box || !P) return; const steps = stepsOf();
        box.innerHTML = steps.map((s, i) => `<div class="cu-th ${i === P.step && !['done'].includes(P.status) ? 'cur' : ''} ${P.shots[i] ? 'has' : ''}" data-shot="${i}" title="${esc(s.title)}"><div data-theme="light" class="cu-th-img">${P.shots[i] ? `<div class="cu-th-in">${P.shots[i]}</div>` : ''}</div><div class="cu-th-l">${P.shots[i] ? icon('check') : `<span class="cu-n">${i + 1}</span>`}<span class="clip">${esc(s.title)}</span>${s.human ? icon('hand') : ''}</div></div>`).join('');
        box.querySelectorAll('[data-shot]').forEach((b) => (b.onclick = () => { const i = +b.dataset.shot; if (P.shots[i]) shotModal(P.run.steps[i].title, P.shots[i]); }));
      }
      function shotModal(title, html) { ctx.ui.modal({ title: '截图 · ' + title, width: 900, body: `<div data-theme="light" class="cu-shotbig"><div class="cu-shot-in">${html}</div></div>` }); }
      async function control(a) {
        if (!P) return; const id = P.run.id;
        if (a === 'pause') { P.paused = true; P.status = 'paused'; await API.report(id, { status: 'paused', log: '你暂停了任务', who: ctx.user.name }); }
        if (a === 'resume') { P.paused = false; P.status = 'running'; await API.report(id, { status: 'running', log: '继续执行' }); }
        if (a === 'take') { P.manual = true; P.status = 'manual'; hideCursor(); await API.report(id, { status: 'manual', log: '你接手了操作', who: ctx.user.name }); }
        if (a === 'back') {
          let n = 0; vp().querySelectorAll('input[data-vc]').forEach((x) => { const k = x.dataset.vc; if ((P.vals[k] || '') !== x.value && x.dataset.mask !== 'pwd') { P.vals[k] = x.value; n++; } });
          P.manual = false; P.status = 'running'; await API.report(id, { status: 'running', log: n ? `你修改了 ${n} 处，交还 AI 继续` : '交还 AI 继续', who: ctx.user.name });
        }
        if (a === 'stop') { if (!(await ctx.ui.confirm('停止这次操作？已做的步骤会保留截图。', { danger: true, okText: '停止' }))) return; P.stopped = true; P.paused = false; P.manual = false; if (P.resolveWait) P.resolveWait('__stop'); P.status = 'stopped'; await API.report(id, { status: 'stopped', log: '你停止了任务', who: ctx.user.name }); }
        if (a === 'again') return start(P.run.task, { ent: P.run.ent && P.run.ent.id, from: P.run.from });
        if (a === 'status') return start('status', { ent: P.run.ent && P.run.ent.id });
        drawChrome();
      }

      /* ---------- 回放（操作记录） ---------- */
      async function openReplay(id) { const r = (await API.run(id)).item; st.replay = r; st.shotSel = Math.max(0, (r.shots || []).map((x, i) => (x ? i : -1)).filter((i) => i >= 0).pop() || 0); st.view = 'replay'; render(); }
      function renderReplay() {
        const r = st.replay; const shots = r.shots || [];
        el.innerHTML = `<div class="cu-wrap">${back('操作记录')}<div class="cu-rh"><div class="cu-rh-t"><div class="row gap2"><div class="h3 clip grow">${esc(r.title)}</div>${tagS(r.status)}</div><div class="t-3 t-xs clip">${esc(r.system.name)} · ${esc(r.created)} · ${esc(r.by)}</div></div></div>
          <div data-theme="light" class="cu-browser"><div class="cu-chrome"><span class="cu-dots"><i></i><i></i><i></i></span><span class="cu-url">${icon('history')}<span class="clip">回放 · 第 ${st.shotSel + 1} 步 · ${esc((r.steps[st.shotSel] || {}).title || '')}</span></span></div><div class="cu-vp scroll">${shots[st.shotSel] || ctx.ui.empty({ icon: 'info', title: '这一步没有截图' })}</div></div>
          <div class="cu-strip">${r.steps.map((s, i) => `<div class="cu-th ${i === st.shotSel ? 'cur' : ''} ${shots[i] ? 'has' : ''}" data-sel="${i}"><div data-theme="light" class="cu-th-img">${shots[i] ? `<div class="cu-th-in">${shots[i]}</div>` : ''}</div><div class="cu-th-l">${shots[i] ? icon('check') : `<span class="cu-n">${i + 1}</span>`}<span class="clip">${esc(s.title)}</span></div></div>`).join('')}</div>
          <div class="card cu-log"><div class="cu-sec-h">操作日志</div><div class="tl">${r.log.slice().reverse().slice(0, 14).map((l) => `<div class="tl-i"><div class="row"><span class="t">${esc(l.text)}</span></div><div class="m">${esc(l.at)} · ${esc(l.who)}</div></div>`).join('')}</div></div></div>`;
        el.querySelector('[data-back]').onclick = () => { st.view = 'home'; st.tab = 'runs'; render(); };
        el.querySelectorAll('[data-sel]').forEach((b) => (b.onclick = () => { st.shotSel = +b.dataset.sel; render(); }));
      }

      /* ---------- 操作员动作（对话里一句话发起） ---------- */
      const entOf = (slot, text) => { if (slot && typeof slot === 'object') return slot.id; const t = String(slot || '') + ' ' + String(text || ''); const e = st.ents.find((x) => t.includes(x.short) || t.includes(x.name)); return e ? e.id : ''; };
      async function viaChat(task, slots, run) {
        slots = slots || {}; if (!st.tasks.length || !st.ents.length) await load();
        if (!canOp()) { run.fail('当前账号没有“电脑操作”权限'); return; }
        const eid = entOf(slots.ent, slots.text);
        const t = st.tasks.find((x) => x.id === task);
        if (t.needsEnt && !eid) { run.fail('要先说是哪家企业，例如“帮我把纸鹿二号智驾的申报表填了”'); return; }
        openSetup(task, { ent: eid }); await run.step(0);
        if (t.needsEnt) await run.select('[data-op="computer.ent"]', eid);
        await run.click('[data-op="computer.start"]');
        const steps = { apply: [0, 0, 1, 2, 2, 3, 4], stats: [0, 0, 1, 1, 2, 3, 3], notice: [0, 1, 1, 2, 3], status: [0, 0, 1, 2] }[task];
        // start() 已被点击触发；这里挂上对话 run，用于人工确认与停止
        await run.wait(() => P && P.run && P.run.task === task && st.view === 'run', 6000);
        const me = P; me.chatRun = run;
        let last = -1; while (['running', 'paused', 'manual', 'waiting'].includes(me.status)) { const k = steps[Math.min(me.step, steps.length - 1)]; if (k !== last) { last = k; await run.step(k); } await sleepRaw(120); if (run.stopped) { me.stopped = true; break; } }
        if (run.stopped) run.check();
        const r = me.run;
        if (me.status === 'done') run.done(task === 'apply' ? `已为${r.ent.short}提交申报，受理编号 ${r.result && r.result.no}。截图和日志已留档` : task === 'stats' ? `${r.ent.short}的月报已上报` : task === 'notice' ? `已把《${(r.notice || {}).title.slice(0, 30)}…》${me.imported ? '存进知识库' : '下载好'}` : `${r.ent.short}共有 ${(r.apps || []).length} 条申报：${(r.apps || []).map((a) => a.title.slice(0, 10) + '·' + a.status).join('；')}`,
          task === 'apply' ? [{ label: '查办理进度', say: `查一下${r.ent.short}的申报进度` }] : task === 'notice' ? [{ label: '问问这份通知', say: '最新这份申报通知的申报时间和条件是什么？' }] : []);
        else if (me.status === 'draft') run.done('已暂存在系统里，没有提交。需要时说“再填一次”');
        else run.done('已停止，做过的步骤保留了截图');
      }
      const actions = {
        apply: (s, run) => viaChat('apply', s, run), stats: (s, run) => viaChat('stats', s, run), notice: (s, run) => viaChat('notice', s, run), status: (s, run) => viaChat('status', s, run),
        async run(s, run) { const m = await API.match((s && s.text) || ''); if (!m.task) { st.view = 'home'; st.tab = 'tasks'; render(); run.done('电脑操作已打开，选一个任务，或者告诉我要去哪个系统做什么'); return; } return viaChat(m.task.id, Object.assign({}, s, { ent: (s && s.ent) || m.entId }), run); },
      };

      /* ---------- 启动 ---------- */
      (async () => { const nav = NAV; await load(); if (nav !== NAV) return; const p = ctx.params || {}; if (p.task && (p.route === 'run' || p.autostart || p.ent)) { openSetup(p.task, { ent: p.ent }); if (p.ent || p.task === 'notice') start(p.task, { ent: p.ent, from: p.from }); } else render(); })();
      if (ctx.bus) ctx.bus.on('data:reset', () => { P = null; st.view = 'home'; load().then(render); });
      return {
        async go(route, params) { params = params || {}; const nav = ++NAV; await load(); if (nav !== NAV) return; if (P && ['running', 'paused', 'manual', 'waiting'].includes(P.status) && !params.task && !['runs', 'systems', 'replay'].includes(route)) { st.view = 'run'; return renderRun(); } if ((route === 'run' || route === 'setup') && params.task) { openSetup(params.task, { ent: params.ent }); if (route === 'run' && (params.ent || params.task === 'notice')) start(params.task, { ent: params.ent, from: params.from }); return; } if (route === 'replay' && params.id) return openReplay(params.id); st.view = 'home'; st.tab = route === 'runs' ? 'runs' : route === 'systems' ? 'systems' : 'tasks'; render(); },
        actions,
        unmount() { alive = false; if (P) P.stopped = true; },
      };
    },
  });
  JK.provide && JK.provide('computer', {
    tasks: () => window.JKApi.computer.tasks().then((r) => r.items),
    start: (task, params) => window.JKApi.computer.start(Object.assign({ task }, params || {})),
  });
})();

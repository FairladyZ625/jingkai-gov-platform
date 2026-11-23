/* 会议记录（app id: meeting）· v4 综合版
 * 合并：v2 四步向导（选录音→自动整理→核对转写→纪要与待办）+ 长任务进度可离开；v3 波形/回放条 + [听不清] 高亮就地改 + 待办缺负责人提示；
 *       v1 发言人改名、纪要模板、热词、派发到“我的待办”、导出 Word、关联企业诉求。
 * 人把关点：派发待办（负责人未确认的不派发）。外部协作者：无此应用权限。 */
(function () {
  const DEF = { name: '会议记录', summary: '录音变纪要，待办直接派发', steps: ['选录音', '自动整理', '核对转写', '纪要与待办'], tabs: [['flow', '办理'], ['all', '全部会议'], ['todos', '待办总览']], sources: [['upload', '上传录音', 'upload'], ['live', '现场录音', 'mic'], ['nas', '会议档案', 'folder']], audioExt: ['mp3', 'm4a', 'wav'], sampleUpload: { title: '新会议', type: '企业座谈会', participants: [], file: '录音.m4a', size: '10 MB', duration: '10:00' }, todoToDoc: [], text: {} };
  const C = Object.assign({}, DEF, (window.JK_APPCFG || {}).meeting || {});
  const T = Object.assign({ pickQ: '整理哪场会？', pickSub: '', runQ: '正在整理', runSub: '', checkQ: '核对转写', checkSub: '', outQ: '纪要与待办', outSub: '', noAccess: '没有权限', local: '本地转写' }, C.text);
  const sec = (t) => { const p = String(t || '0').split(':').map(Number); return p.reduce((a, b) => a * 60 + (b || 0), 0); };
  const mixedMeeting = () => window.JKHttp.mode() === 'http' && window.JKHttp.mode('meeting') === 'mock';
  const httpMeeting = () => window.JKHttp.mode('meeting') === 'http';
  const demoSample = { sampleId: 'park-service-v1', title: '【合成演示】园区服务清单核对', type: '专题推进会', source: 'demo' };
  const demoPrompt = '把园区服务清单的合成录音整理成纪要';
  const hms = (s) => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60; return (h ? h + ':' + String(m).padStart(2, '0') : String(m).padStart(2, '0')) + ':' + String(x).padStart(2, '0'); };
  // 标签显示到秒；引用与跳转仍保留原始毫秒定位。
  const atLabel = (stamp) => hms(Math.floor(sec(stamp)));
  const dateLabel = (value) => String(value || '—').replace(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?/, (_, y, m, d, t) => y + '年' + (+m) + '月' + (+d) + '日 ' + t);
  const sourceLabel = (source) => ({ demo: '合成演示录音', upload: '上传录音', live: '现场录音', nas: '会议档案' })[source] || source || '—';
  const sectionLabel = (minutes) => minutes.body.every(({ h }) => /^发言(?:摘录|片段)/.test(h)) ? '发言片段' : '议题';
  const short = (n) => String(n || '').replace(/（.*?）/g, '');

  JK.registerApp({
    manifest: {
      id: 'meeting', name: C.name, short: '会议', icon: 'meeting', hue: 'violet', version: '4.0.0', owner: 'AI 工作组',
      summary: C.summary, routes: ['flow', 'detail', 'transcript', 'minutes', 'all', 'todos', 'record'],
      perms: { view: '看会议、纪要', operate: '上传录音、改纪要、派发待办', approve: '—' },
      tools: [
        { name: 'meeting.list', desc: '会议列表与状态', params: {} },
        { name: 'meeting.transcribe', desc: '转写 + 分发言人 + 生成纪要（长任务）', params: { id: 'string', type: 'string' } },
        { name: 'meeting.summarize', desc: '读取纪要与待办', params: { id: 'string' } },
        { name: 'meeting.commit_todos', desc: '派发待办到“我的待办”（需确认）', params: { id: 'string', ids: 'string[]' } },
      ],
      accepts: [{ kind: '会议录音', ext: C.audioExt, match: /会|录音|座谈|纪要/ }],
      intents: [
        { id: 'meeting.summarize', action: 'summarize', examples: [demoPrompt, '整理一下文化企业座谈会的纪要', '看看座谈会纪要', '上次座谈会说了什么'], keywords: ['纪要', '会上说了', '座谈会'], slots: { meeting: 'meeting' }, plan: ['打开会议记录', '找到会议', '打开纪要与待办'] },
        { id: 'meeting.transcribe', requires: 'operate', action: 'transcribe', examples: ['整理局务会录音', '把 AI 原生企业推进会的录音转成纪要', '转写最新的会议录音'], keywords: ['转写', '录音', '整理录音'], slots: { meeting: 'meeting' }, plan: ['选中录音', '选纪要模板', '本地转写与分发言人', '生成纪要与待办'] },
        { id: 'meeting.todos', action: 'todos', examples: ['会上定了哪些待办', '把座谈会的待办派发下去', '还有哪些待办没认领'], keywords: ['待办', '派发', '认领'], slots: { meeting: 'meeting' }, plan: ['打开纪要与待办', '核对负责人', '等你确认派发'] },
        { id: 'meeting.record', requires: 'operate', action: 'record', examples: ['开始现场录音', '帮我录一下这个会'], keywords: ['现场录音', '开始录音', '录一下'], plan: ['打开现场录音', '开始录制'] },
        { id: 'meeting.export', action: 'export', examples: ['把座谈会纪要导出 Word', '导出纪要'], keywords: ['导出', 'Word'], slots: { meeting: 'meeting' }, plan: ['打开纪要', '导出 Word'] },
      ],
      starters: ['整理一下文化企业座谈会的纪要', '整理局务会录音', '还有哪些待办没认领？'],
      demo: [
        { title: '录音变纪要', say: '整理局务会录音' },
        { title: '看纪要派待办', say: '把座谈会的待办派发下去' },
      ],
    },

    mount(el, ctx) {
      const { ui, api, perms } = ctx; const M = api.meeting; const esc = ui.esc, icon = ui.icon, tag = ui.tag;
      const canView = perms.can('view') && !perms.isPartner, canOp = canView && perms.can('operate');
      const S = { tab: 'flow', step: 0, src: 'nas', id: null, cur: null, minutes: null, job: null, sel: new Set(), pos: 0, playing: false, tq: '', tf: '待认领', aq: '', rec: null, setup: null };
      let LIST = [], TEMPLATES = [], HOT = [], ALLTODOS = null, loaded = false, loadErr = null, timer = null, recTimer = null;
      const $ = (s) => el.querySelector(s);
      const mOf = (id) => LIST.find((m) => m.id === id) || {};
      const statusLabel = (m) => (m.status === 'done' ? '已整理' : m.status === 'running' ? '整理中' : '新录音');

      async function load() {
        if (!canView) { loaded = true; return render(); }
        try { const r = await M.list(); LIST = r.items; TEMPLATES = r.templates || []; HOT = r.hotwords || []; loaded = true; loadErr = null; } catch (e) { loadErr = e; }
        render();
      }
      async function refresh() { const r = await M.list(); LIST = r.items; ALLTODOS = null; }
      async function openMeeting(id, step) {
        S.id = id; S.cur = null; S.minutes = null; S.setup = null; S.sel = new Set(); S.pos = 0; stopPlay();
        S.step = step == null ? 3 : step; body();
        try {
          const { item, minutes } = await M.get(id);
          if (S.id !== id) return;
          if (!mOf(id).id) LIST.push({ ...item, todoCount: (item.todos || []).length });
          if (item.status === 'running' && item.jobId) {
            S.step = 1; S.job = null; body(); poll(id, item.jobId); return;
          }
          if (item.status !== 'done' || !minutes) {
            S.step = 0; S.setup = { id, type: item.type || (TEMPLATES[0] || {}).name, hot: new Set(HOT) };
          } else {
            S.cur = item; S.minutes = minutes;
            S.sel = new Set((item.todos || []).filter((t) => t.status !== '已派发' && t.owner !== '待确认').map((t) => t.id));
          }
        } catch (e) {
          if (S.id !== id) return;
          ui.toast(e.message, { type: 'err' }); S.step = 0;
        }
        body();
      }

      /* ---------- 框架 ---------- */
      function render() {
        el.innerHTML = `<div class="ap"><div class="ap-h">${ui.appIcon('meeting', 'lg')}<div class="grow"><h2>${esc(C.name)}</h2><div class="ap-sum">${esc(C.summary)}</div></div>${canView ? `<span class="tag mt-local" data-hue="green">${icon('lock')}${esc(T.local)}</span><button class="btn ghost sm" data-act="ask" data-op="meeting.ask">${icon('sparkles')}问 AI</button>` : ''}</div>
          ${canView ? `<div class="tabs ap-tabs">${C.tabs.map(([k, l]) => `<button class="tab ${S.tab === k ? 'on' : ''}" data-tab="${k}" data-op="meeting.tab-${k}">${esc(l)}${k === 'todos' && pendingN() ? `<span class="count muted">${pendingN()}</span>` : ''}</button>`).join('')}</div>` : ''}
          <div class="ap-body" id="mb"></div></div>`;
        body();
      }
      const pendingN = () => (ALLTODOS ? ALLTODOS.filter((t) => t.status === '待认领').length : 0);
      function body() {
        const b = $('#mb'); if (!b) return;
        if (!canView) { b.innerHTML = ui.empty({ icon: 'lock', title: T.noAccess, desc: '如需使用，请联系管理员在“授权”里开通' }); return; }
        if (loadErr) { b.innerHTML = ui.empty({ icon: 'alert', title: '会议列表没加载出来', desc: loadErr.message || '', action: '重试' }); return; }
        if (!loaded) { b.innerHTML = '<div class="skel-list"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>'; return; }
        if (S.tab === 'all') return renderAll(b);
        if (S.tab === 'todos') return renderTodos(b);
        b.innerHTML = stepsBar() + '<div class="wiz-body" id="ms"></div><div class="wiz-foot" id="mf"></div>';
        [step0, step1, step2, step3][S.step]();
      }
      function stepsBar() {
        const m = mOf(S.id); const max = m.status === 'done' ? 3 : m.status === 'running' ? 1 : 0;
        return `<div class="wiz-steps">${C.steps.map((s, i) => `${i ? `<i class="wiz-line ${i <= S.step ? 'done' : ''}"></i>` : ''}<div class="wiz-step ${i === S.step ? 'on' : i < S.step ? 'done' : ''}" ${i !== S.step && i <= max && i !== 1 ? `data-step="${i}"` : ''} data-op="meeting.step-${i}"><span class="n">${i < S.step ? '✓' : i + 1}</span>${esc(s)}</div>`).join('')}</div>`;
      }
      const foot = (l, r) => { const f = $('#mf'); if (f) f.innerHTML = `${l || ''}<span class="sp"></span>${r || ''}`; };

      /* ---------- 第 1 步：选录音 ---------- */
      function meetRow(m) {
        return `<div class="card tight li" data-open="${m.id}" data-op="meeting.m-${m.id}"><span class="ini h-${ui.hue(m.type, 'meetType')}">${icon('meeting')}</span><div class="grow"><div class="t clip">${esc(m.title)}</div><div class="s">${esc(dateLabel(m.date))} · ${esc(m.duration || '—')} · ${esc(sourceLabel(m.source))}</div></div>${tag(m.type, 'meetType')}${tag(statusLabel(m), 'meetStatus')}</div>`;
      }
      function step0() {
        const ms = $('#ms');
        if (S.setup) return setupView(ms);
        const formats = httpMeeting() ? [...new Set([...C.audioExt, 'webm', 'ogg'])] : C.audioExt;
        const srcBody = S.src === 'upload' ? `<div class="mt-drop" data-act="pickFile" data-op="meeting.drop">${icon('upload', 22)}<div><b>拖入录音文件，或点这里选择</b><div class="meta">${esc(formats.join(' / '))} · 单个最大 ${httpMeeting() ? '64 MiB' : '2GB'}</div></div><input type="file" id="mfile" accept="${formats.map((x) => '.' + x).join(',')}" hidden></div>
            <div class="row" style="margin-top:var(--s2)"><button class="btn sm ghost" data-act="sampleUpload" data-op="meeting.sample">${icon('file')}用示例录音</button></div>`
          : S.src === 'live' ? liveView()
          : (LIST.length ? `<div class="stack rows">${LIST.map(meetRow).join('')}</div>` : ui.empty({ icon: 'meeting', title: '会议档案里还没有录音', desc: '上传一段录音试试' }));
        ms.innerHTML = `<div class="q">${esc(T.pickQ)}</div><div class="q-sub">${esc(T.pickSub)}</div>
          <div class="seg" style="margin-bottom:var(--s4)">${C.sources.filter((s) => canOp || s[0] === 'nas').map(([k, l, ic]) => `<button class="${S.src === k ? 'on' : ''}" data-src="${k}" data-op="meeting.src-${k}">${icon(ic)}${esc(l)}</button>`).join('')}</div>${srcBody}`;
        foot('', '');
      }
      function liveView() {
        const r = S.rec;
        return `<div class="mt-live ${r && r.on ? 'on' : ''}"><button class="mt-mic" data-act="${r && r.on ? 'recStop' : 'recStart'}" data-op="meeting.rec">${icon(r && r.on ? 'stop' : 'mic', 26)}</button>
          <div class="big num" id="rect">${hms(r ? r.t : 0)}</div><div class="h-violet mt-wave sm" id="recw">${wave(40, r && r.on)}</div><div class="meta">${r && r.on ? '录音中…点方块结束，结束后自动开始整理' : '点话筒开始。浏览器会请求麦克风权限（演示环境为模拟录音）'}</div></div>`;
      }
      const wave = (n, live, seed = 7) => Array.from({ length: n }, (_, i) => { const v = live ? 20 + Math.random() * 80 : 25 + Math.abs(Math.sin(i * 0.7 + seed) * 50 + Math.sin(i * 2.3) * 25); return `<i style="height:${Math.round(v)}%"></i>`; }).join('');
      function setupView(ms) {
        const st = S.setup; const m = mOf(st.id);
        ms.innerHTML = `<div class="q">怎么整理这份录音？</div><div class="q-sub">选好纪要模板，热词可提高人名、企业名的准确率</div>
          <div class="stack rows" style="margin-bottom:var(--s4)"><div class="card tight"><div class="row gap3"><span class="ini h-violet">${icon('meeting')}</span><div class="grow"><b>${esc(m.title)}</b><div class="meta">${esc(m.file || '')} · ${esc(m.size || '')} · ${esc(m.duration)}</div></div>${tag(statusLabel(m), 'meetStatus')}</div><div class="mt-wave" style="margin-top:var(--s3)">${wave(90, false, m.title.length)}</div>
            <div class="meta" style="margin-top:var(--s2)">参会：${esc((m.participants || []).map(short).join('、'))}</div></div></div>
          <div class="sec">纪要模板</div><div class="stack rows mt-tpls">${TEMPLATES.map((t) => `<button class="card tight mt-tpl ${st.type === t.name ? 'on sel' : ''}" data-tpl="${esc(t.name)}" data-op="meeting.tpl-${t.id}"><b>${esc(t.name)}</b><div class="meta">${esc(t.sections.join(' · '))}</div></button>`).join('')}</div>
          <div class="sec">热词 <span class="meta">（点一下取消）</span></div><div class="chips">${HOT.map((h) => `<button class="chip-btn ${st.hot.has(h) ? 'on' : ''}" data-hot="${esc(h)}">${esc(h)}</button>`).join('')}</div>`;
        foot(`<button class="btn ghost" data-act="cancelSetup">返回</button>`, canOp ? `<button class="btn primary" data-act="start" data-op="meeting.start">${icon('bolt')}开始整理</button>` : '<span class="meta">只读：没有操作权限</span>');
      }
      async function startJob(id, type) {
        const st = S.setup; S.setup = null;
        try { const r = await M.transcribe(id, { type: type || (st && st.type), hotwords: st ? [...st.hot] : HOT }); S.id = id; S.job = r.job; mOf(id).status = 'running'; ctx.audit('转写会议录音', mOf(id).title); S.step = 1; body(); poll(id, r.job.id); }
        catch (e) { S.setup = st; body(); ui.toast(e.message, { type: 'err' }); }
      }
      function poll(id, jid) {
        clearTimeout(timer);
        const tick = async () => {
          try {
            const { job } = await M.job(jid); if (S.id === id) S.job = job;
            if (S.tab === 'flow' && S.step === 1 && S.id === id) step1();
            if (job.status === 'done') {
              await refresh(); const m = mOf(id);
              ctx.bus.emit('inbox:changed', { app: 'meeting', ref: id });
              if (S.tab === 'flow' && S.step === 1 && S.id === id) { ui.toast('整理好了：转写、发言人、纪要和待办都已生成', { type: 'ok' }); openMeeting(id, 2); }
              else ui.toast(`「${m.title}」整理好了`, { type: 'ok', action: { label: '查看', fn: () => { S.tab = 'flow'; render(); openMeeting(id, 3); } } });
              return;
            }
            if (job.status === 'failed') {
              await refresh();
              if (S.tab === 'flow' && S.step === 1 && S.id === id) { S.step = 0; body(); }
              ui.toast(job.error?.message || '整理失败，请查看会议状态', { type: 'err' });
              return;
            }
            timer = setTimeout(tick, 400);
          } catch (e) { ui.toast('整理出错：' + e.message, { type: 'err', action: { label: '重试', fn: () => startJob(id) } }); }
        };
        tick();
      }

      /* ---------- 第 2 步：自动整理（长任务） ---------- */
      function step1() {
        const ms = $('#ms'); if (!ms) return; const j = S.job || { progress: 0, step: 0, steps: ['上传与校验', '语音转写', '区分发言人', '热词纠错', '生成纪要与待办'] }; const m = mOf(S.id);
        ms.innerHTML = `<div class="q">${esc(T.runQ)}</div><div class="q-sub">${esc(T.runSub)}</div>
          <div class="mt-run"><div class="row gap3"><span class="ini h-violet">${icon('meeting')}</span><div class="grow"><b>${esc(m.title || '')}</b><div class="meta">${esc(m.duration || '')} · ${esc((m.participants || []).length)} 人参会 · ${esc(m.type || '')}</div></div><span class="big num">${j.progress || 0}%</span></div>
            <div class="mt-wave live" style="margin:var(--s4) 0 var(--s3)">${wave(90, false, 3).replace(/<i /g, (x, i) => x)}</div>
            <div class="bar"><i style="width:${j.progress || 0}%"></i></div>
            <div class="mt-steps">${j.steps.map((s, i) => `<div class="mt-st ${i < j.step || j.status === 'done' ? 'done' : i === j.step ? 'on' : ''}"><span class="mt-si">${i < j.step || j.status === 'done' ? icon('check') : i === j.step ? '<span class="mt-spin"></span>' : ''}</span><span class="mt-sl">${esc(s)}</span></div>`).join('')}</div></div>`;
        foot(`<button class="btn ghost" data-act="leave" data-op="meeting.leave">先去忙别的</button>`, `<span class="meta">${icon('clock')}约 ${Math.max(1, Math.round(sec(m.duration) / 600))} 分钟（演示加速）</span>`);
      }

      /* ---------- 第 3 步：核对转写 ---------- */
      function speakers() { const s = []; (S.cur.transcript || []).forEach((l) => { if (!s.includes(l[1])) s.push(l[1]); }); return s; }
      function hiText(t) {
        let h = esc(t).replace(/\[听不清\]/g, '<mark class="mt-unk">听不清</mark>');
        HOT.forEach((w) => { if (w.length > 1) h = h.split(esc(w)).join(`<span class="mt-hw" title="热词">${esc(w)}</span>`); });
        return h;
      }
      function step2() {
        const ms = $('#ms'); const m = S.cur;
        if (!m) { ms.innerHTML = '<div class="skel-list"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>'; foot(); return; }
        const tr = m.transcript || []; const unk = tr.filter((l) => /\[听不清\]/.test(l[2])).length; const dur = sec(m.duration);
        ms.innerHTML = `<div class="q">${esc(T.checkQ)}</div><div class="q-sub">${esc(T.checkSub)}</div>
          ${unk ? `<div class="callout h-amber" style="margin-bottom:var(--s3)">${icon('alert')}<div>有 <b>${unk}</b> 处没听清，点黄色部分补上</div></div>` : ''}
          <div class="mt-player"><button class="btn icon" data-act="play" data-op="meeting.play">${icon(S.playing ? 'pause' : 'play')}</button><div class="grow"><div class="mt-seek" data-act="seekbar" data-op="meeting.seek"><div class="h-violet mt-wave xs">${wave(120, false, m.title.length)}</div><i class="mt-ph" id="mph" style="left:${dur ? (S.pos / dur) * 100 : 0}%"></i></div></div><span class="num meta" id="mpt">${hms(S.pos)} / ${esc(m.duration)}</span></div>
          <div class="row wrap gap2" style="margin:var(--s3) 0">${speakers().map((s) => `<button class="chip-btn" data-spk="${esc(s)}" data-op="meeting.spk-${esc(s)}" title="点击改名"><span class="mt-dot h-${ui.hue(s)}"></span>${esc(s)} ${icon('edit')}</button>`).join('')}<span class="sp"></span><span class="meta">${tr.length} 段 · 热词 ${HOT.filter((w) => tr.some((l) => l[2].includes(w))).length} 个命中</span></div>
          <div class="mt-tr" id="mtr">${tr.map((l, i) => `<div class="mt-line ${lineAt() === i ? 'on' : ''}" data-line="${i}"><button class="mt-t num" data-seek="${sec(l[0])}">${esc(atLabel(l[0]))}</button><span class="ini sm h-${ui.hue(l[1])}">${esc(short(l[1])[0] || '?')}</span><div class="grow"><div class="meta">${esc(l[1])}</div><div class="mt-x" ${canOp ? `data-edit="${i}"` : ''} data-op="meeting.line-${i}">${hiText(l[2])}</div></div></div>`).join('')}</div>`;
        foot(`<button class="btn ghost" data-step="0">换一场</button>`, `<button class="btn primary" data-step="3" data-op="meeting.to-minutes">看纪要与待办 ${icon('arrow-right')}</button>`);
      }
      const lineAt = () => { const tr = (S.cur && S.cur.transcript) || []; let k = -1; tr.forEach((l, i) => { if (sec(l[0]) <= S.pos) k = i; }); return k; };
      function seek(s) { S.pos = s; const dur = sec(S.cur.duration); const ph = $('#mph'); if (ph) ph.style.left = (s / dur) * 100 + '%'; const t = $('#mpt'); if (t) t.textContent = `${hms(s)} / ${S.cur.duration}`; const k = lineAt(); el.querySelectorAll('.mt-line').forEach((n) => n.classList.toggle('on', +n.dataset.line === k)); const on = el.querySelector('.mt-line.on'); if (on && S.playing) on.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
      function stopPlay() { S.playing = false; clearInterval(S._pt); }
      function togglePlay() { if (S.playing) { stopPlay(); } else { S.playing = true; S._pt = setInterval(() => { const dur = sec(S.cur.duration); if (S.pos >= dur) return stopPlay(); seek(S.pos + 8); }, 250); } const b = el.querySelector('[data-act="play"]'); if (b) b.innerHTML = icon(S.playing ? 'pause' : 'play'); }
      function editLine(i) {
        const l = S.cur.transcript[i];
        ui.modal({ title: `修改 ${l[0]} · ${l[1]}`, okText: '保存', body: `<div class="meta" style="margin-bottom:var(--s2)">把“[听不清]”换成实际内容</div><textarea class="textarea" id="lt" rows="4">${esc(l[2])}</textarea>`, ok: async (box) => { const v = box.querySelector('#lt').value.trim(); await saveLine(i, v); } });
        setTimeout(() => { const t = document.querySelector('#lt'); if (t) { const p = t.value.indexOf('[听不清]'); t.focus(); if (p >= 0) t.setSelectionRange(p, p + 5); } }, 50);
      }
      async function saveLine(i, v) { const r = await M.patch(S.id, { line: { index: i, text: v } }); S.cur = r.item; S.minutes = r.minutes; ctx.audit('修改转写', `${S.cur.title} · ${S.cur.transcript[i][0]}`); ui.toast('已修改', { type: 'ok' }); if (S.step === 2) step2(); }
      function renameSpk(from) {
        const m = S.cur; const opts = (m.participants || []).filter((p) => short(p) !== from);
        ui.modal({ title: `“${from}”改成谁？`, okText: '全部替换', body: `<div class="field"><label>新名字</label><input class="input" id="sn" value="${esc(from)}" list="spl"><datalist id="spl">${opts.map((p) => `<option value="${esc(short(p))}">${esc(p)}</option>`).join('')}</datalist></div><div class="meta">会同时替换这个人的所有发言（${m.transcript.filter((l) => l[1] === from).length} 段）</div>`,
          ok: async (box) => { const to = box.querySelector('#sn').value.trim(); if (!to || to === from) return; await doRename(from, to); } });
      }
      async function doRename(from, to) { const r = await M.patch(S.id, { renameSpeaker: { from, to } }); S.cur = r.item; S.minutes = r.minutes; ctx.audit('发言人改名', `${from} → ${to}`); ui.toast(`已把“${from}”改为“${to}”`, { type: 'ok' }); if (S.step === 2) step2(); }

      /* ---------- 第 4 步：纪要与待办 ---------- */
      function step3() {
        const ms = $('#ms'); const m = S.cur, mi = S.minutes;
        if (!m || !mi) { ms.innerHTML = '<div class="skel-list"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>'; foot(); return; }
        const td = m.todos || []; const miss = td.filter((t) => t.owner === '待确认' || t.due === '待确认').length; const sent = td.filter((t) => t.status === '已派发').length;
        ms.innerHTML = `<div class="q">${esc(T.outQ)}</div><div class="q-sub">${esc(T.outSub)}</div>
          ${m.sampleId === demoSample.sampleId ? '<div class="callout">本页使用约 11 秒的合成录音和对应的示例逐字稿，不是实际会议记录。</div>' : ''}
          ${mixedMeeting() ? '<div class="callout">本次为模拟会议，派发仅保留在演示数据中，不会写入真实收件箱。</div>' : ''}
          <div class="mt-stats" style="margin-bottom:var(--s5)"><span><b class="num">${mi.body.length}</b> ${sectionLabel(mi)}</span><span><b class="num">${td.length}</b> 待办</span><span class="${miss ? 'warn' : ''}"><b class="num">${miss}</b> 缺负责人/时限</span><span><b class="num">${sent}</b> 已派发</span></div>
          <div class="sec row">待办<span class="sp"></span>${canOp ? `<button class="link" data-act="selAll">全选可派发</button>` : ''}</div>
          ${td.length ? `<div class="stack rows mt-todos">${td.map(todoRow).join('')}</div>` : '<div class="meta">会上没有形成待办</div>'}
          <div class="sec row">纪要 ${tag(mi.template || m.type, 'meetType')}<span class="sp"></span><span class="meta">点段落可修改</span></div>
          <div class="mt-paper" data-op="meeting.minutes"><h3>${esc(mi.title)}</h3><div class="mt-meta">${esc(dateLabel(mi.meta))}</div><div class="mt-meta">参会：${esc(mi.attendees || '未登记')}</div>
            ${mi.body.map((b, i) => `<div class="mt-sec"><h4>${esc(b.h)}</h4><p ${canOp ? `data-mp="${i}"` : ''}>${esc(b.p)}</p><div class="mt-refs">${(b.refs || []).map((r) => `<button class="mt-ref num" data-ref="${esc(r)}" title="回到原话">${icon('play')}${esc(atLabel(r))}</button>`).join('')}</div></div>`).join('')}</div>`;
        const n = [...S.sel].filter((id) => { const t = td.find((x) => x.id === id); return t && t.status !== '已派发' && t.owner !== '待确认'; }).length;
        foot(`<button class="btn ghost" data-step="2">${icon('chevron-left')}转写</button><button class="btn" data-act="word" data-op="meeting.word">${icon('download')}导出 Word</button>${canOp ? `<button class="btn" data-act="link" data-op="meeting.link">${icon('building')}关联企业诉求</button>` : ''}`,
          canOp ? `<button class="btn primary" data-act="commit" data-op="meeting.commit" ${n ? '' : 'disabled'}>${icon('send')}派发选中 ${n} 条</button>` : '');
      }
      function todoRow(t) {
        const done = t.status === '已派发'; const miss = t.owner === '待确认'; const ps = (S.cur.participants || []).map(short);
        const doc = !done && canOp && (C.todoToDoc || []).find((x) => x.match.test(t.task + (t.deliverable || '')));
        return `<div class="card tight li mt-todo ${done ? 'done' : ''} ${miss ? 'miss' : ''}" data-op="meeting.todo-${t.id}">
          ${canOp && !done ? `<input type="checkbox" class="cb" data-tsel="${t.id}" ${S.sel.has(t.id) && !miss ? 'checked' : ''} ${miss ? 'disabled title="先选负责人"' : ''}>` : `<span class="t-3">${icon(done ? 'check' : 'flag')}</span>`}
          <div class="grow"><div class="t">${esc(t.task)}</div><div class="s">${t.deliverable ? `交付：${esc(t.deliverable)} · ` : ''}<button class="link" data-ref="${esc(t.ref)}">${esc(atLabel(t.ref))} 原话</button>${doc ? ` · <button class="link" data-todoc="${t.id}">${icon('doc')}起草公文</button>` : ''}</div></div>
          ${canOp && !done ? `<select class="select sm mt-own ${miss ? 'warn' : ''}" data-towner="${t.id}" data-op="meeting.owner-${t.id}">${['待确认', ...ps.filter((p) => !p.includes('企业') && p.length <= 3), ...(ps.includes(t.owner) || t.owner === '待确认' ? [] : [t.owner])].filter((v, i, a) => a.indexOf(v) === i).map((p) => `<option ${p === t.owner ? 'selected' : ''}>${esc(p)}</option>`).join('')}</select>
            <input class="input sm mt-due ${t.due === '待确认' ? 'warn' : ''}" data-tdue="${t.id}" value="${esc(t.due)}" title="完成时限">` : `<span class="meta">${esc(t.owner)} · ${esc(t.due)}</span>`}
          ${tag(miss ? '待确认' : t.status, 'todoStatus')}</div>`;
      }
      async function patchTodo(id, b) { const r = await M.patch(S.id, { todo: Object.assign({ id }, b) }); S.cur = r.item; S.minutes = r.minutes; const t = S.cur.todos.find((x) => x.id === id); if (t.owner !== '待确认' && t.status !== '已派发') S.sel.add(id); else S.sel.delete(id); ALLTODOS = null; step3(); }
      async function commit() {
        const ids = [...S.sel]; const r = await M.commitTodos(S.id, { ids }); const g = await M.get(S.id); S.cur = g.item; S.minutes = g.minutes; S.sel = new Set(); ALLTODOS = null;
        ctx.audit('派发会议待办', `${S.cur.title} · ${r.committed.length} 条`); ctx.bus.emit('inbox:changed', { app: 'meeting' });
        ui.toast(`${mixedMeeting() ? '演示中已标记 ' : '已派发 '}${r.committed.length}${mixedMeeting() ? ' 条，未写入真实收件箱' : ' 条到负责人的“我的待办”'}${r.skipped?.length ? `；${r.skipped.length} 条未派发：${[...new Set(r.skipped.map((item) => item.reason))].join('、')}` : ''}`, { type: r.committed.length ? 'ok' : 'warn' }); step3(); return r;
      }
      function editPara(i) {
        const b = S.minutes.body[i];
        ui.modal({ title: `修改：${b.h}`, okText: '保存', width: 640, body: `<textarea class="textarea" id="mp" rows="7">${esc(b.p)}</textarea>`, ok: async (box) => { const v = box.querySelector('#mp').value.trim(); const mi = JSON.parse(JSON.stringify(S.minutes)); mi.body[i].p = v; const r = await M.patch(S.id, { minutes: mi }); S.minutes = r.minutes; ctx.audit('修改纪要', `${S.cur.title} · ${b.h}`); ui.toast('纪要已保存', { type: 'ok' }); step3(); } });
      }
      function exportWord() {
        const mi = S.minutes, m = S.cur;
        const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta charset="utf-8"><title>${esc(mi.title)}</title><style>body{font-family:仿宋,FangSong,serif;font-size:16pt;line-height:1.8}h1{font-family:方正小标宋简体,宋体,serif;text-align:center;font-size:22pt}h2{font-family:黑体,sans-serif;font-size:16pt}td,th{border:1px solid #999;padding:4px 8px;font-size:12pt}</style></head><body>
          <h1>${esc(mi.title)}</h1><p>${esc(mi.meta)}</p><p>参会人员：${esc(mi.attendees)}</p>${mi.body.map((b) => `<h2>${esc(b.h)}</h2><p>${esc(b.p)}</p>`).join('')}
          <h2>待办事项</h2><table style="border-collapse:collapse"><tr><th>事项</th><th>负责人</th><th>时限</th><th>交付物</th></tr>${(m.todos || []).map((t) => `<tr><td>${esc(t.task)}</td><td>${esc(t.owner)}</td><td>${esc(t.due)}</td><td>${esc(t.deliverable || '')}</td></tr>`).join('')}</table></body></html>`;
        ui.download(`${mi.title}.doc`, html, 'application/msword'); ctx.audit('导出纪要', mi.title); ui.toast('已导出 Word', { type: 'ok' });
      }
      async function linkIssue() {
        const meeting = S.cur, minutes = S.minutes;
        let ents;
        try { ents = (await api.enterprise.list({})).items; }
        catch (e) { ui.toast(e.message, { type: 'err' }); return; }
        if (S.cur !== meeting) return;
        if (!ents.length) { ui.toast('企业台账暂无可关联企业', { type: 'err' }); return; }
        const txt = (meeting.participants || []).join(' ') + (meeting.transcript || []).map((l) => l[1] + l[2]).join(' ');
        const hit = ents.filter((e) => txt.includes(e.short));
        const topics = [...new Set(minutes.body.map((b) => b.h.replace(/^[一二三四五六七八九]、/, '')))];
        const d = ui.modal({ title: '关联企业诉求', okText: '登记到企业台账', body: `<div class="meta" style="margin-bottom:var(--s3)">会上企业提出的诉求，登记后在“企业管理 → 诉求看板”跟进</div>
          <div class="field"><label for="le">企业</label><select class="select" id="le">${[...hit, ...ents.filter((e) => !hit.includes(e))].map((e) => `<option value="${esc(e.id)}">${esc(e.short || e.name)}</option>`).join('')}</select></div>
          <div class="field"><label for="lt">诉求</label><select class="select" id="lt">${topics.map((t) => `<option>${esc(t)}</option>`).join('')}</select></div>`,
          ok: async (box) => {
            const entId = box.querySelector('#le').value, topic = box.querySelector('#lt').value;
            const confirm = box.querySelector('[data-ok]');
            confirm.disabled = true;
            try {
              const { issue } = await M.link(meeting.id, { entId, title: topic ? `${topic}（${meeting.title}）` : undefined });
              ctx.audit('关联企业诉求', issue.title);
              ui.toast('已登记到企业台账', { type: 'ok', action: { label: '去看看', fn: () => ctx.nav.open('enterprise', 'issues', { entId, issueId: issue.id }) } });
            } catch (e) {
              confirm.disabled = false;
              ui.toast(e.message || '登记企业诉求失败', { type: 'err' });
              return false;
            }
          } });
        return d;
      }
      function toDoc(id) {
        const t = S.cur.todos.find((x) => x.id === id); const rule = C.todoToDoc.find((x) => x.match.test(t.task + (t.deliverable || '')));
        ctx.nav.open('document', 'new', { templateId: rule.templateId, inputs: { [rule.input]: t.task.replace(/^起草\s*/, '') }, from: { app: 'meeting', id: S.id, title: S.cur.title } });
      }

      /* ---------- 全部会议 / 待办总览 ---------- */
      function renderAll(b) {
        const q = S.aq.trim(); const rows = LIST.filter((m) => !q || (m.title + m.type + (m.participants || []).join('')).includes(q));
        b.innerHTML = `<div class="row gap2" style="margin-bottom:var(--s3)"><div class="mt-search grow">${icon('search')}<input class="input" id="maq" placeholder="会议名称、类型、参会人" value="${esc(S.aq)}"></div>${canOp ? `<button class="btn" data-act="newUpload">${icon('upload')}上传录音</button>` : ''}</div>
          ${rows.length ? `<div class="card mt-tblw"><table class="tbl"><thead><tr><th>会议</th><th>类型</th><th>时长</th><th>待办</th><th>状态</th></tr></thead><tbody>${rows.map((m) => `<tr data-open="${m.id}" class="click"><td><b>${esc(m.title)}</b><div class="meta">${esc(dateLabel(m.date))} · ${esc(sourceLabel(m.source))}</div></td><td>${tag(m.type, 'meetType')}</td><td class="num">${esc(m.duration || '—')}</td><td class="num">${m.status === 'done' ? m.todoCount : '—'}</td><td>${tag(statusLabel(m), 'meetStatus')}</td></tr>`).join('')}</tbody></table></div>` : ui.empty({ icon: 'search', title: '没找到会议', desc: '换个关键词', action: '清空搜索' })}`;
      }
      async function loadAllTodos() { const done = LIST.filter((m) => m.status === 'done'); const rs = await Promise.all(done.map((m) => M.get(m.id))); ALLTODOS = rs.flatMap((r) => (r.item.todos || []).map((t) => Object.assign({}, t, { mid: r.item.id, mtitle: r.item.title }))); }
      async function renderTodos(b) {
        if (!ALLTODOS) { b.innerHTML = '<div class="skel-list"><div class="skel"></div><div class="skel"></div></div>'; try { await loadAllTodos(); } catch (e) { b.innerHTML = ui.empty({ icon: 'alert', title: '待办没加载出来', desc: e.message, action: '重试' }); return; } if (S.tab !== 'todos') return; const c = el.querySelector('[data-tab="todos"]'); if (c && pendingN()) c.innerHTML = `待办总览<span class="count muted">${pendingN()}</span>`; }
        const f = S.tf; const rows = ALLTODOS.filter((t) => !f || (f === '待认领' ? t.status === '待认领' : t.status === f));
        const cnt = (s) => ALLTODOS.filter((t) => t.status === s).length;
        b.innerHTML = `<div class="seg" style="margin-bottom:var(--s3)">${[['待认领', '待派发'], ['已派发', '已派发'], ['', '全部']].map(([k, l]) => `<button class="${f === k ? 'on' : ''}" data-tf="${k}" data-op="meeting.tf-${k || 'all'}">${esc(l)} <span class="num">${k ? cnt(k) : ALLTODOS.length}</span></button>`).join('')}</div>
          ${rows.length ? `<div class="stack rows">${rows.map((t) => `<div class="card tight li" data-otodo="${t.mid}"><span class="t-3">${icon(t.status === '已派发' ? 'check' : 'flag')}</span><div class="grow"><div class="t">${esc(t.task)}</div><div class="s">${esc(t.mtitle)} · ${esc(t.ref)}</div></div><span class="meta ${t.owner === '待确认' ? 'mt-warn' : ''}">${esc(t.owner)} · ${esc(t.due)}</span>${tag(t.owner === '待确认' ? '待确认' : t.status, 'todoStatus')}</div>`).join('')}</div>` : ui.empty({ icon: 'check', title: f === '待认领' ? '待办都派发了' : '没有待办', desc: '整理新的会议录音后，待办会出现在这里' })}`;
      }

      /* ---------- 上传 / 现场录音 ---------- */
      function uploadModal(file) {
        if (!file && httpMeeting()) {
          return ui.modal({ title: '整理合成示例录音', okText: '开始整理',
            body: '<p>园区服务清单核对 · 约 11 秒合成录音。已有示例会直接打开，不会另建一条会议。</p>',
            ok: async () => { await createAndRun(demoSample); } });
        }
        const s = C.sampleUpload; const name = file ? file.name : s.file;
        const title = file ? name.replace(/\.[^.]+$/, '').replace(/^\d{4}-\d{2}-\d{2}\s*/, '') : s.title;
        return ui.modal({ title: '登记这份录音', okText: '上传并整理', body: `<div class="row gap2" style="margin-bottom:var(--s3)"><span class="t-3">${icon('file')}</span><b class="clip">${esc(name)}</b><span class="meta">${esc(file && file.size ? (file.size / 1048576).toFixed(1) + ' MB' : s.size)}</span></div>
          <div class="field"><label>会议名称</label><input class="input" id="ut" value="${esc(title)}" data-op="meeting.up-title"></div>
          <div class="field"><label>会议类型（决定纪要模板）</label><select class="select" id="uy">${TEMPLATES.map((t) => `<option ${t.name === s.type ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}</select></div>
          <div class="field"><label>参会人（逗号分隔，帮助区分发言人）</label><input class="input" id="up" value="${esc(file ? '' : s.participants.join('，'))}"></div>`,
          ok: async (box) => {
            const b = { title: box.querySelector('#ut').value.trim() || title, type: box.querySelector('#uy').value, participants: box.querySelector('#up').value.split(/[,，、\s]+/).filter(Boolean), file: name, size: file && file.size ? (file.size / 1048576).toFixed(1) + ' MB' : s.size, duration: file ? undefined : s.duration, source: file || !httpMeeting() ? '网页上传' : 'demo' };
            const confirm = box.querySelector('[data-ok]');
            confirm.disabled = true;
            try { await createAndRun(b, file); }
            catch (e) { confirm.disabled = false; ui.toast(e.message, { type: 'err' }); return false; }
          } });
      }
      async function registerMeeting(input, file) {
        const { item } = await M.create(input, file);
        LIST = [Object.assign({ todoCount: 0 }, item), ...LIST.filter((row) => row.id !== item.id)];
        return item;
      }
      async function createAndRun(b, file) {
        const meeting = await registerMeeting(b, file);
        S.tab = 'flow'; render(); S.setup = null;
        if (meeting.status === 'done') await openMeeting(meeting.id, 2);
        else if (meeting.status === 'running' && meeting.jobId) { S.id = meeting.id; S.step = 1; body(); poll(meeting.id, meeting.jobId); }
        else await startJob(meeting.id, b.type);
        return meeting;
      }
      function recStart() { S.rec = { on: true, t: 0 }; step0(); recTimer = setInterval(() => { S.rec.t += 1; const t = $('#rect'); if (t) t.textContent = hms(S.rec.t); const w = $('#recw'); if (w) w.innerHTML = wave(40, true); }, 1000); }
      async function recStop() { clearInterval(recTimer); const t = S.rec.t; S.rec = null; const d = new Date(); const b = { title: `现场录音 ${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`, type: '专题推进会', participants: [ctx.user.name], file: '现场录音.m4a', size: Math.max(0.1, t * 0.03).toFixed(1) + ' MB', duration: hms(Math.max(t, 1)), source: '现场录音' }; return createAndRun(b); }

      /* ---------- 事件 ---------- */
      el.addEventListener('click', async (ev) => {
        const x = ev.target.closest('[data-tab],[data-step],[data-src],[data-open],[data-tpl],[data-hot],[data-act],[data-seek],[data-spk],[data-edit],[data-ref],[data-mp],[data-tf],[data-otodo],[data-todoc],[data-empty-action]'); if (!x || x.disabled) return; const d = x.dataset;
        if (d.tab) { S.tab = d.tab; stopPlay(); render(); return; }
        if (d.step != null && !x.classList.contains('on')) { const k = +d.step; if (k === 0) { S.setup = null; S.step = 0; stopPlay(); body(); return; } if (S.cur) { S.step = k; body(); } return; }
        if (d.src) { S.src = d.src; step0(); return; }
        if (d.open) { S.tab = 'flow'; if (!$('#ms')) render(); return openMeeting(d.open); }
        if (d.tpl) { S.setup.type = d.tpl; step0(); return; }
        if (d.hot) { S.setup.hot.has(d.hot) ? S.setup.hot.delete(d.hot) : S.setup.hot.add(d.hot); step0(); return; }
        if (d.seek != null) return seek(+d.seek);
        if (d.spk) return canOp ? renameSpk(d.spk) : null;
        if (d.edit != null) return editLine(+d.edit);
        if (d.ref) { S.step = 2; body(); seek(sec(d.ref)); const on = el.querySelector('.mt-line.on'); if (on) { on.scrollIntoView({ block: 'center' }); on.classList.add('flash'); } return; }
        if (d.mp != null) return editPara(+d.mp);
        if (d.tf != null) { S.tf = d.tf; return renderTodos($('#mb')); }
        if (d.otodo) { S.tab = 'flow'; render(); return openMeeting(d.otodo, 3); }
        if (d.todoc) return toDoc(d.todoc);
        if (d.emptyAction != null) { if (loadErr) { loaded = false; body(); return load(); } if (S.tab === 'all') { S.aq = ''; return renderAll($('#mb')); } if (S.tab === 'todos') { ALLTODOS = null; return renderTodos($('#mb')); } return; }
        const a = d.act;
        if (a === 'ask') return ctx.nav.chat(S.cur ? `「${S.cur.title}」会上定了哪些事？` : '还有哪些会议待办没认领？');
        if (a === 'pickFile') { if (ev.target.id !== 'mfile') $('#mfile').click(); return; }
        if (a === 'newUpload' && httpMeeting()) { S.tab = 'flow'; S.step = 0; S.src = 'upload'; S.setup = null; render(); $('#mfile').click(); return; }
        if (a === 'sampleUpload' || a === 'newUpload') return uploadModal(null);
        if (a === 'recStart') return recStart();
        if (a === 'recStop') return recStop();
        if (a === 'cancelSetup') { S.setup = null; step0(); return; }
        if (a === 'start') return startJob(S.setup.id);
        if (a === 'leave') { S.tab = 'all'; render(); ui.toast('整理在后台继续，好了会通知你', {}); return; }
        if (a === 'play') return togglePlay();
        if (a === 'seekbar') { const r = x.getBoundingClientRect(); return seek(((ev.clientX - r.left) / r.width) * sec(S.cur.duration)); }
        if (a === 'selAll') { S.cur.todos.forEach((t) => { if (t.status !== '已派发' && t.owner !== '待确认') S.sel.add(t.id); }); step3(); return; }
        if (a === 'commit') return commit();
        if (a === 'word') return exportWord();
        if (a === 'link') return linkIssue();
      });
      el.addEventListener('change', (ev) => {
        const t = ev.target; const d = t.dataset;
        if (t.id === 'mfile' && t.files[0]) return uploadModal(t.files[0]);
        if (d.tsel) { t.checked ? S.sel.add(d.tsel) : S.sel.delete(d.tsel); step3(); return; }
        if (d.towner) return patchTodo(d.towner, { owner: t.value });
        if (d.tdue) return patchTodo(d.tdue, { due: t.value.trim() || '待确认' });
      });
      el.addEventListener('input', (ev) => { if (ev.target.id === 'maq') { S.aq = ev.target.value; clearTimeout(S._q); S._q = setTimeout(() => { renderAll($('#mb')); const i = $('#maq'); if (i) { i.focus(); i.setSelectionRange(i.value.length, i.value.length); } }, 200); } });
      el.addEventListener('dragover', (ev) => { const z = ev.target.closest('.mt-drop'); if (z) { ev.preventDefault(); z.classList.add('over'); } });
      el.addEventListener('dragleave', (ev) => { const z = ev.target.closest('.mt-drop'); if (z) z.classList.remove('over'); });
      el.addEventListener('drop', (ev) => { const z = ev.target.closest('.mt-drop'); if (z) { ev.preventDefault(); z.classList.remove('over'); const f = ev.dataTransfer.files[0]; if (f) uploadModal(f); } });

      load();

      /* ---------- 操作员动作 ---------- */
      const ready = async () => { for (let i = 0; i < 60 && !loaded; i++) await new Promise((r) => setTimeout(r, 50)); };
      function resolveMeeting(slot, text, want) {
        if (slot && typeof slot === 'object' && slot.id) return slot.id;
        const s = String(slot || text || '');
        const keys = (m) => [m.title, m.type, ...(m.title.match(/[\u4e00-\u9fa5A-Z]{2,}/g) || [])];
        let hit = LIST.find((m) => s.includes(m.id) || s.includes(m.title));
        if (!hit) { const sc = LIST.map((m) => [m, keys(m).reduce((a, k) => a + (k && k.length >= 2 && s.includes(k) ? k.length : 0), 0) + (s.includes(m.type.slice(0, 2)) ? 2 : 0) + (want && m.status === want ? 1 : 0)]).sort((a, b) => b[1] - a[1]); if (sc.length && sc[0][1] > 1) hit = sc[0][0]; }
        if (!hit && /最新|新的|最近/.test(s)) hit = LIST.find((m) => m.status === (want || 'new')) || LIST[0];
        return hit ? hit.id : null;
      }
      const goFlow = () => { stopPlay(); if (S.tab !== 'flow') { S.tab = 'flow'; render(); } };
      const noPerm = (run) => { run && run.fail(T.noAccess); };
      async function opPick(id, run) {
        goFlow(); if (S.step !== 0 || S.setup) { S.step = 0; S.setup = null; body(); }
        if (S.src !== 'nas') await run.click('[data-op="meeting.src-nas"]');
        await run.click(`[data-op="meeting.m-${id}"]`);
      }
      async function toMinutes(id, run) {
        if (run) { await run.step(1); await opPick(id, run); await run.wait(() => S.cur && S.cur.id === id && el.querySelector('[data-op="meeting.minutes"]'), 6000); }
        else { goFlow(); await openMeeting(id, 3); }
      }
      const actions = {
        async summarize({ meeting, text } = {}, run) {
          await ready(); if (!canView) return noPerm(run);
          const wantsSample = httpMeeting() && /园区服务清单.*合成录音/.test(text || '');
          let id;
          if (wantsSample) {
            const existing = LIST.find((row) => row.sampleId === demoSample.sampleId);
            if (!existing && !canOp) return noPerm(run);
            id = (existing || await registerMeeting(demoSample)).id;
          } else id = resolveMeeting(meeting, text, 'done');
          if (!id) { run && run.fail('没找到这场会议，请说出会议名称'); return; }
          if (mOf(id).status !== 'done') return actions.transcribe({ meeting: id, text }, run);
          await toMinutes(id, run);
          if (run) { await run.step(2); await run.highlight('[data-op="meeting.minutes"]'); const mi = S.minutes; const td = S.cur.todos || [];
            run.done(`「${S.cur.title}」整理出 ${mi.body.length} 个${sectionLabel(mi)}：${mi.body.map((b) => b.h.replace(/^[一二三四五六七八九]、/, '')).join('、')}；待办 ${td.length} 条，${td.filter((t) => t.owner === '待确认').length} 条缺负责人`, [{ label: '派发待办', say: `把${S.cur.title.slice(-6)}的待办派发下去` }, { label: '导出 Word', say: '把座谈会纪要导出 Word' }]); }
          return S.minutes;
        },
        async transcribe({ meeting, text, type } = {}, run) {
          await ready(); if (!canOp) return noPerm(run); const id = resolveMeeting(meeting, text, 'new'); if (!id) { run && run.fail('没找到这份录音，可以先上传'); return; }
          const m = mOf(id); if (m.status === 'done') return actions.summarize({ meeting: id }, run);
          if (!run) { await startJob(id, type); return; }
          await run.step(1); goFlow();
          if (m.status !== 'running') { await opPick(id, run); await run.wait('[data-op="meeting.start"]'); await run.step(2); if (type) { const tp = TEMPLATES.find((t) => t.name === type); if (tp) await run.click(`[data-op="meeting.tpl-${tp.id}"]`); } else await run.highlight(`[data-op="meeting.tpl-${(TEMPLATES.find((t) => t.name === m.type) || {}).id}"]`); await run.click('[data-op="meeting.start"]'); }
          else { S.id = id; S.step = 1; body(); poll(id, m.jobId); }
          await run.step(3); await run.wait(() => S.step === 2 && S.cur && S.cur.id === id, 30000); await run.step(4); await run.click('[data-op="meeting.to-minutes"]'); await run.wait('[data-op="meeting.minutes"]');
          const td = S.cur.todos || []; const unk = (S.cur.transcript || []).filter((l) => /\[听不清\]/.test(l[2])).length;
          run.done(`「${S.cur.title}」整理好了：${S.cur.transcript.length} 段转写、${S.minutes.body.length} 个${sectionLabel(S.minutes)}、${td.length} 条待办${unk ? `；有 ${unk} 处没听清，建议核对` : ''}`, [{ label: '派发待办', say: '把这场会的待办派发下去' }, { label: '导出 Word', say: '导出纪要' }]);
        },
        async todos({ meeting, text } = {}, run) {
          await ready(); if (!canView) return noPerm(run);
          const id = resolveMeeting(meeting, text, 'done') || (S.cur && S.cur.id);
          if (!id || /哪些.*没认领|还有哪些|总览/.test(text || '')) {
            if (S.tab !== 'todos') { stopPlay(); if (run) await run.click('[data-op="meeting.tab-todos"]'); else { S.tab = 'todos'; render(); } }
            if (run) { await run.wait(() => ALLTODOS && el.querySelector('[data-op="meeting.tf-待认领"]')); const p = ALLTODOS.filter((t) => t.status === '待认领'); run.done(`还有 ${p.length} 条待办没派发：${p.slice(0, 4).map((t) => `${t.task}（${t.owner}）`).join('；')}`); }
            return ALLTODOS;
          }
          if (mOf(id).status !== 'done') { run && run.fail('这场会还没整理，先说“整理录音”'); return; }
          await toMinutes(id, run); if (!run) return S.cur.todos;
          await run.step(2); const td = S.cur.todos.filter((t) => t.status !== '已派发');
          if (!td.length) { run.done('这场会的待办都已派发'); return; }
          for (const t of td.filter((x) => x.owner === '待确认')) { await run.highlight(`[data-op="meeting.owner-${t.id}"]`, '缺负责人'); }
          if (!canOp) { run.done(`待办 ${td.length} 条，你没有派发权限`); return; }
          let td2 = td;
          if (td.some((t) => t.owner === '待确认')) {
            const ps = (S.cur.participants || []).map(short).filter((p) => p.length <= 3);
            const sug = td.filter((t) => t.owner === '待确认').map((t) => ({ t, o: ps.find((p) => (t.task + (t.ref || '')).includes(p)) || ps.find((p) => p !== S.cur.host) || ps[0] || ctx.user.name }));
            const a = await run.ask(`有 ${sug.length} 条待办缺负责人，按建议补上再一起派发？\n${sug.map((x) => '· ' + x.o + '：' + String(x.t.task).slice(0, 16)).join('\n')}`, ['按建议补上', '我自己补']);
            if (a !== '按建议补上') { run.done('好的，在待办表里选好负责人后点“派发选中”即可'); return; }
            for (const x of sug) { try { await run.highlight(`[data-op="meeting.owner-${x.t.id}"]`, '补上：' + x.o); } catch (e) {} await patchTodo(x.t.id, { owner: x.o, due: x.t.due === '待确认' ? '2026-11-25' : x.t.due }); }
            td2 = S.cur.todos.filter((t) => t.status !== '已派发');
          }
          const ok = td2.filter((t) => t.owner !== '待确认'); const miss = td2.length - ok.length;
          await run.highlight('[data-op="meeting.commit"]', '确认后才派发');
          const c = await run.ask(`拟派发 ${ok.length} 条${miss ? `，另有 ${miss} 条缺负责人（不会派发）` : ''}。${mixedMeeting() ? '本次为模拟会议，是否在演示数据中标记？' : '确认派发到负责人的“我的待办”吗？'}`, ['确认派发', '我先改一下']);
          if (c !== '确认派发') { run.done('好的，改好负责人后点“派发选中”即可'); return; }
          await run.step(3); S.sel = new Set(ok.map((t) => t.id)); step3();
          const result = await commit();
          const delivered = ok.filter((item) => result.committed.includes(item.id));
          const skipped = result.skipped || [];
          run.done(`${mixedMeeting() ? '演示中标记 ' : '已派发 '}${delivered.length} 条${delivered.length ? `：${delivered.map((t) => `${t.owner}·${t.task}`).join('；')}` : ''}${skipped.length ? `。有 ${skipped.length} 条未派发：${[...new Set(skipped.map((item) => item.reason))].join('、')}` : ''}${miss ? `。另有 ${miss} 条缺负责人，请补上` : ''}`);
        },
        async record(a, run) {
          await ready(); if (!canOp) return noPerm(run); goFlow(); S.step = 0; S.setup = null; body();
          if (run) { await run.step(1); await run.click('[data-op="meeting.src-live"]'); await run.step(2); await run.click('[data-op="meeting.rec"]'); run.done('已开始现场录音，结束时点方块按钮，会自动整理成纪要'); } else { S.src = 'live'; step0(); }
        },
        async export({ meeting, text } = {}, run) {
          await ready(); if (!canView) return noPerm(run); const id = resolveMeeting(meeting, text, 'done') || (S.cur && S.cur.id); if (!id || mOf(id).status !== 'done') { run && run.fail('没找到已整理的会议'); return; }
          if (!(S.tab === "flow" && S.cur && S.cur.id === id && S.step === 3)) await toMinutes(id, run);
          if (run) { await run.step(2); await run.click('[data-op="meeting.word"]'); run.done(`已导出「${S.minutes.title}」Word 文件`); } else exportWord();
        },
        async intake({ file } = {}, run) {
          await ready(); if (!canOp) return noPerm(run); goFlow();
          const s = C.sampleUpload; const title = String(file.name || '会议录音').replace(/\.[^.]+$/, '').replace(/^\d{4}-\d{2}-\d{2}\s*/, '');
          const type = (TEMPLATES.find((t) => title.includes(t.name.slice(0, 2))) || TEMPLATES[0] || {}).name;
          const b = httpMeeting() && file.id === 'rec-1117' ? demoSample : { title, type, participants: [], file: file.name, size: file.size ? (file.size / 1048576).toFixed(1) + ' MB' : s.size, source: '对话拖入' };
          const blob = file instanceof Blob ? file : file?.blob;
          if (!run) return createAndRun(b, blob);
          await run.step(1); const m = await createAndRun(b, blob); await run.step(2);
          await run.wait(() => S.step === 2 && S.cur && S.cur.id === m.id, 30000); await run.step(3);
          run.done(`录音「${S.cur.title}」已整理：${S.cur.transcript.length} 段转写、${(S.cur.todos || []).length} 条待办（按“${S.cur.type}”模板）`, [{ label: '看纪要', say: `看看${S.cur.title}纪要` }]);
        },
      };
      return {
        async go(route, params = {}) {
          await ready();
          if (!canView) return;
          const id = params.meetingId || params.id;
          if (route === 'all' || ((route === 'todos' || params.tab === 'todos') && !id)) {
            S.tab = route === 'all' ? 'all' : 'todos'; render(); return;
          }
          goFlow();
          if (route === 'record' || params.upload || !id) {
            S.step = 0; S.setup = null;
            if (route === 'record' || params.upload) S.src = canOp ? (route === 'record' ? 'live' : 'upload') : 'nas';
            body(); return;
          }
          return openMeeting(id, route === 'transcript' ? 2 : 3);
        },
        actions,
        unmount() { clearTimeout(timer); clearInterval(recTimer); stopPlay(); },
      };
    },
  });
})();

/* 一键演示：操作完成后才开始计算阅读时间，所有播放等待都归本轮所有。 */
(function () {
  const { h, esc, icon } = JK, Op = window.JKOp, CFG = window.JK_CONFIG || {};
  const D = { on: false, paused: false, skip: false, i: 0 };
  const EXIT = Symbol('exit'), NEXT = Symbol('next');
  let bar, activeRun;
  const notify = run => [...run.waiters].forEach(fn => fn());
  function wait(run, ms = 0, signal) {
    return new Promise((resolve, reject) => {
      let timer, since, remaining = ms;
      function update() {
        clearTimeout(timer);
        if (since !== undefined) remaining -= performance.now() - since;
        since = undefined;
        const reason = run !== activeRun || signal?.aborted ? EXIT : D.skip ? NEXT : null;
        if (!reason && (D.paused || remaining > 0)) {
          if (!D.paused) { since = performance.now(); timer = setTimeout(update, Math.ceil(remaining)); }
          return;
        }
        run.waiters.delete(update);
        signal?.removeEventListener('abort', update);
        reason ? reject(reason) : resolve();
      }
      run.waiters.add(update);
      signal?.addEventListener('abort', update);
      update();
    });
  }
  function caption(text) {
    D.cap = text;
    if (bar) bar.querySelector('.demo-caption').textContent = text;
  }
  function drawBar(run) {
    const { segs } = run;
    if (!bar) {
      bar = h('<div class="demobar" role="group" aria-label="演示播放控制"></div>');
      document.body.appendChild(bar);
    }
    const focused = document.activeElement?.dataset.a;
    const pct = Math.round((D.i / segs.length) * 100);
    bar.innerHTML = `<span class="tag" data-hue="blue">${icon('play')}一键演示</span><span class="seg-t">${D.i + 1}/${segs.length}</span>
      <span class="demo-caption">${esc(D.cap)}</span><span class="bar prog" aria-hidden="true"><i style="width:${pct}%"></i></span>
      <button class="btn sm" data-a="pause" aria-pressed="${D.paused}">${icon(D.paused ? 'play' : 'pause')}${D.paused ? '继续播放' : '暂停阅读'}</button>
      <button class="btn sm" data-a="skip" ${run.busy ? 'disabled title="请等待当前操作完成"' : 'title="播放下一段，结束后暂停"'}>${icon('chevron-right')}下一段</button>
      <button class="btn sm ghost" data-a="exit">${icon('x')}退出</button>`;
    if (['pause', 'skip', 'exit'].includes(focused)) bar.querySelector(`[data-a="${focused}"]`).focus();
    bar.onclick = e => {
      const a = e.target.closest('[data-a]')?.dataset.a;
      if (a === 'pause') { D.paused = !D.paused; run.playOne = false; notify(run); drawBar(run); }
      if (a === 'skip' && !run.busy) { run.playOne = true; D.paused = false; D.skip = true; notify(run); }
      if (a === 'exit') stop(run);
    };
  }
  async function perform(run, fn) {
    run.busy = true; drawBar(run);
    try {
      await fn();
      // 有些界面在打开确认框后就返回，并没有返回用户决定的 Promise。
      // 此时既不替用户点确定，也不开始结果页的阅读倒计时。
      while (document.querySelector('[role="dialog"] [data-ok]')) await wait(run, 150);
    }
    finally { run.busy = false; if (run === activeRun) drawBar(run); }
  }
  async function login(run, username) {
    if (JKShell.S.me?.username === username) return;
    // 等待现有切号流程；未取得目标身份不得开始或继续播放。
    if (bar) bar.hidden = true;
    const ok = await JKShell.switchUser(username, undefined, run.controller.signal);
    if (run !== activeRun || !ok || JKShell.S.me?.username !== username) throw EXIT;
    if (bar) bar.hidden = false;
  }
  async function typeAndSend(run, text) {
    const ta = document.querySelector('#chatcol textarea');
    if (ta) {
      const input = value => { ta.value = value; ta.dispatchEvent(new Event('input', { bubbles: true })); };
      ta.focus();
      const draft = ta.value;
      try { for (let i = 1; i <= text.length; i += 2) { input(text.slice(0, i)); await wait(run, 22); } }
      finally { input(draft); }
    }
    await perform(run, () => JKShell.send(text));
  }
  async function runStep(run, st, next) {
    await wait(run);
    const SH = window.JKShell;
    if (st.caption) caption(st.caption);
    else if (st.login) await login(run, st.login);
    else if (st.newChat) SH.newChat();
    else if (st.say) await typeAndSend(run, st.say);
    else if (st.file) {
      const file = (window.JK_SAMPLE_FILES || []).find(f => f.id === st.file);
      if (file) await perform(run, () => SH.handleFile({ ...file, sample: true }));
    } else if (st.appDemo) {
      const list = JK.registry[st.appDemo]?.manifest.demo || [];
      for (const d of list.slice(st.skipFirst ? 1 : 0)) {
        await wait(run);
        if (d.title) caption(d.title);
        if (d.open) await perform(run, () => SH.openApp(st.appDemo, d.route, d.params));
        else { await runStep(run, d); continue; }
        await wait(run, d.wait || CFG.demoReadMs);
      }
    } else if (st.open) await perform(run, () => SH.openBuiltin(st.open, st.tab));
    else if (st.theme) SH.setTheme(st.theme);
    else if (st.click) {
      let el;
      for (let k = 0; k < 30 && !(el = document.querySelector(st.click)); k++) await wait(run, 150);
      if (!el) throw Error('未找到演示操作入口');
      el.scrollIntoView({ block: 'center' });
      if (Op.cursor?.moveTo) await Op.cursor.moveTo(el);
      await wait(run, 400);
      await perform(run, async () => {
        el.click();
        while (el.getAttribute('aria-busy') === 'true') await wait(run, 150);
        if (el.dataset.failed) throw Error('演示操作未完成，请查看页面提示');
      });
    }
    // wait 是编排者指定的阅读时长，不是操作员的动画速度。未指定时给新字幕、操作结果留出阅读时间。
    const hasResult = st.caption || st.say || st.file || st.open || st.theme || st.click;
    await wait(run, st.wait ?? (hasResult && !next?.wait ? CFG.demoReadMs : 0));
  }
  async function start(from = 0) {
    const segs = window.JK_DEMO_SCRIPT || [];
    if (activeRun || !JKShell.canPresentDemo() || !segs[from] || document.querySelector('[role="dialog"]')) return;
    const run = { theme: JKShell.theme(), segs, waiters: new Set(), controller: new AbortController() };
    activeRun = run;
    D.i = from; D.paused = D.skip = false;
    try {
      const first = segs[from].steps[0];
      if (first?.login) await login(run, first.login);
      if (run !== activeRun) return;
      D.on = Op.demo = true; Op.speed = CFG.demoSpeed || 1;
      document.body.classList.add('demo-on');
      for (; D.i < segs.length; D.i++) {
        D.skip = false; D.cap = segs[D.i].title;
        drawBar(run);
        try {
          const steps = segs[D.i].steps;
          for (const [i, st] of steps.entries()) await runStep(run, st, steps[i + 1]);
          // 手动前往下一段会实际展示该段，而非只换标题。读完后由观众决定是否继续。
          if (run.playOne) { run.playOne = false; D.paused = true; drawBar(run); }
          await wait(run);
        } catch (e) { if (e !== NEXT) throw e; }
        if (run !== activeRun) return;
        // 只关闭演示段的展示层，走组件正常关闭路径，不移除确认框或伪造回执。
        document.querySelectorAll('.drawer, .modal').forEach(el => {
          if (!el.querySelector('[data-ok]')) el.querySelector('[data-x]')?.click();
        });
      }
    } catch (e) { if (run === activeRun && e !== EXIT) console.warn('demo', e); }
    finally { stop(run); }
  }
  function stop(run = activeRun) {
    if (!run || run !== activeRun) return;
    activeRun = null; run.controller.abort(); notify(run);
    const started = D.on;
    D.on = D.paused = D.skip = Op.demo = false; Op.speed = CFG.operatorSpeed || 1;
    if (started) {
      Op.running?.stop(true);
      JKShell.setTheme(run.theme);
    }
    bar?.remove(); bar = null; D.cap = ''; document.body.classList.remove('demo-on');
  }
  // 沿用演示脚本原有的自动示范选择；暂停、手动选择、退出都必须撤销其倒计时。
  function scheduleChoice(pick) {
    const ctl = new AbortController();
    wait(activeRun, CFG.demoReadMs, ctl.signal).then(pick, () => {});
    return () => ctl.abort();
  }
  window.JKDemo = { start, stop, state: D, scheduleChoice,
    ownsSwitch: signal => !!signal && activeRun?.controller.signal === signal };
})();

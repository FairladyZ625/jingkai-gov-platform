/* 一键演示引擎：按 config/demo-script.js 执行；可暂停 / 跳过 / 退出。 */
(function () {
  const { h, esc, icon, sleep, $ } = JK; const Op = window.JKOp; const CFG = window.JK_CONFIG || {};
  const D = { on: false, paused: false, skip: false, i: 0 };
  let bar, cap;
  const gate = async () => { while (D.paused && D.on) await sleep(150); if (!D.on) throw new Error('DEMO_EXIT'); };
  function caption(t) { D.cap = t; const c = bar && bar.querySelector('.demo-caption'); if (c) c.textContent = t; }
  function drawBar(segs) {
    if (!bar) { bar = h('<div class="demobar"></div>'); document.body.appendChild(bar); }
    const s = segs[D.i] || {}; const pct = Math.round((D.i / segs.length) * 100);
    document.body.classList.add('demo-on');
    bar.innerHTML = `<span class="tag" data-hue="blue">${icon('play')}一键演示</span><span class="seg-t">${D.i + 1}/${segs.length}</span><span class="demo-caption">${esc(D.cap || s.title || '')}</span><span class="bar prog"><i style="width:${pct}%"></i></span><button class="btn sm ghost" data-a="pause">${icon(D.paused ? 'play' : 'pause')}${D.paused ? '继续' : '暂停'}</button><button class="btn sm ghost" data-a="skip">${icon('chevron-right')}下一段</button><button class="btn sm ghost" data-a="exit">${icon('x')}退出</button>`;
    bar.onclick = (e) => { const b = e.target.closest('[data-a]'); if (!b) return; const a = b.dataset.a; if (a === 'pause') { D.paused = !D.paused; drawBar(segs); } else if (a === 'skip') { D.skip = true; if (Op.running) Op.running.stop(true); } else if (a === 'exit') stop(); };
  }
  async function typeAndSend(text) {
    const ta = document.querySelector('#chatcol textarea'); if (ta) { ta.focus(); for (let i = 1; i <= text.length; i += 2) { ta.value = text.slice(0, i); ta.dispatchEvent(new Event('input', { bubbles: true })); await sleep(22); } ta.value = ''; ta.dispatchEvent(new Event('input', { bubbles: true })); }
    await JKShell.send(text);
  }
  async function runStep(st) {
    await gate(); if (D.skip) return;
    const SH = window.JKShell;
    if (st.caption) caption(st.caption);
    else if (st.login) { if (!SH.S.me || SH.S.me.username !== st.login) await SH.switchUser(st.login); }
    else if (st.newChat) SH.newChat();
    else if (st.say) await typeAndSend(st.say);
    else if (st.file) { const f = (window.JK_SAMPLE_FILES || []).find((x) => x.id === st.file); if (f) await SH.handleFile({ ...f, sample: true }); }
    else if (st.appDemo) { const def = JK.registry[st.appDemo]; if (!def) return; const list = (def.manifest.demo || []).slice(st.skipFirst ? 1 : 0); for (const d of list) { await gate(); if (D.skip) return; if (d.title) caption(d.title); if (d.say) await typeAndSend(d.say); else if (d.file) await runStep({ file: d.file }); else if (d.open) await SH.openApp(st.appDemo, d.route, d.params); if (d.wait) await sleep(d.wait); await sleep(500); } }
    else if (st.open) await SH.openBuiltin(st.open, st.tab);
    else if (st.theme) SH.setTheme(st.theme);
    else if (st.click) { let el = null; for (let k = 0; k < 30 && !(el = document.querySelector(st.click)); k++) await sleep(150); if (el) { el.scrollIntoView({ block: 'center' }); Op.cursor && Op.cursor.moveTo ? await Op.cursor.moveTo(el) : 0; await sleep(400); el.click(); } }
    if (st.wait) await sleep(st.wait / (CFG.demoSpeed || 1));
    await sleep(250);
  }
  async function start(from = 0) {
    if (D.on) return; const segs = window.JK_DEMO_SCRIPT || []; D.on = true; D.paused = false; D.i = from;
    Op.demo = true; Op.speed = CFG.demoSpeed || 1.6;
    try {
      for (; D.i < segs.length; D.i++) { D.skip = false; document.querySelectorAll('.mask-bg, [role="dialog"]').forEach((x) => x.remove()); drawBar(segs); for (const st of segs[D.i].steps) { await runStep(st); if (D.skip) break; } }
    } catch (e) { if (e.message !== 'DEMO_EXIT') console.warn('demo', e); }
    finally { stop(); }
  }
  function stop() { D.on = false; Op.demo = false; Op.speed = CFG.operatorSpeed || 1; if (Op.running) Op.running.stop(true); if (bar) bar.remove(); bar = null; D.cap = ''; document.body.classList.remove('demo-on'); }
  window.JKDemo = { start, stop, state: D };
})();

/* =====================================================================
 * v4 外壳：登录 · 侧栏 · 对话（首页/消息/输入框/文件投递）· 右侧应用面板 · 模型切换 · ⌘K · 收件箱 · 个人设置
 * 只通过 window.JKApi（接口适配层）取数，不读模拟数据。
 * ===================================================================== */
(function () {
  const { $, $$, h, esc, md, icon, sleep, tag, toast, modal, menu, appIcon } = JK;
  const API = window.JKApi; const H = window.JKHttp; const CFG = window.JK_CONFIG || {};
  const Op = window.JKOp;
  const S = { me: null, role: null, grants: {}, models: [], model: 'auto', convs: [], cur: null, open: [], active: null, mounted: {}, inbox: [], todos: [], layout: 'home' };
  const root = () => $('#root');

  /* ---------------- 工具 ---------------- */
  const can = (app, action) => { const g = S.grants || {}; const acts = [...(g['*'] || []), ...(g[app] || [])]; return acts.includes('admin') || acts.includes(action || 'view'); };
  const isAdmin = () => (S.grants['*'] || []).includes('admin');
  const roleName = () => (S.role && S.role.name) || '';
  const greet = () => { const hr = new Date().getHours(); return hr < 6 ? '夜深了' : hr < 11 ? '早上好' : hr < 13 ? '中午好' : hr < 18 ? '下午好' : '晚上好'; };
  const appsVisible = (group) => (window.JK_APP_LIST || []).filter((a) => a.enabled !== false && JK.registry[a.id] && (!group || a.group === group) && can(a.id, 'view'));
  const mf = (id) => (JK.registry[id] ? JK.registry[id].manifest : JK.BUILTIN[id] || { name: id });
  const roleHue = () => JK.hue(roleName(), 'role');
  const storeKey = () => 'jk4-convs:' + (S.me ? S.me.id : '');
  const saveConvs = () => { try { localStorage.setItem(storeKey(), JSON.stringify(S.convs.slice(0, 30))); } catch (e) {} };
  const loadConvs = () => { try { S.convs = JSON.parse(localStorage.getItem(storeKey()) || '[]'); } catch (e) { S.convs = []; } };
  const nowHM = () => new Date().toTimeString().slice(0, 5);
  const setTheme = (t) => { document.documentElement.dataset.theme = t; try { localStorage.setItem('jk4-theme2', t); } catch (e) {} JK.bus.emit('theme', t); const b = $('#btn-theme'); if (b) b.innerHTML = icon(t === 'dark' ? 'sun' : 'moon'); };
  const theme = () => document.documentElement.dataset.theme || 'dark';
  const maskVal = (field, v) => { if (!(S.role && S.role.mask)) return v; const s = String(v == null ? '' : v); if (/phone|tel|mobile|电话|手机/.test(field)) return s.replace(/^(\d{3})\d+(\d{2})$/, '$1******$2').replace(/^(.{3}).+$/, '$1****'); if (/revenue|营收|tax|纳税|amount|金额|身份证|idcard/.test(field)) return '***'; return s; };

  /* ---------------- 启动 ---------------- */
  async function boot() {
    setTheme(theme());
    let u = null; try { u = (await API.auth.session()).user; } catch (e) {}
    if (!u) return renderLogin();
    await afterLogin();
  }
  async function afterLogin() {
    const r = await API.me.get(); S.me = r.user; S.role = r.role; S.grants = r.grants || {};
    try { const m = await API.models.list(); S.models = m.items || []; S.model = m.current || 'auto'; } catch (e) {}
    loadConvs(); S.cur = null; S.open = []; S.active = null; Object.values(S.mounted).forEach((x) => { try { x.ctl && x.ctl.unmount && x.ctl.unmount(); } catch (e) {} }); S.mounted = {};
    renderShell(); Op.loadDict(); refreshInbox();
  }

  /* ---------------- 登录 ---------------- */
  function renderLogin(err, keepUser) {
    const accts = CFG.demoAccounts || [];
    root().innerHTML = `<div class="login">
      <div class="login-l">
        <div class="row"><span class="brand-mark">${icon('cube')}</span><b style="font-size:15px">${esc(CFG.platformName)}</b></div>
        <div class="pitch"><h1>说一句话，<br>AI 替你把事办完</h1><p>政策兑现、企业走访、会议纪要、公文起草，一个对话框全搞定。</p>
          <div class="feat">${[['sparkles', '在右侧亲自操作给你看，关键一步等你确认'], ['book', '回答都有出处，点开就是政策原文'], ['shield', '敏感数据走本地模型，操作全程留痕']].map(([i, t]) => `<div class="row">${icon(i)}<span>${t}</span></div>`).join('')}</div></div>
        <div class="t-3 t-xs">${esc(CFG.orgName)}</div>
      </div>
      <div class="login-r"><form class="login-box" id="lf" autocomplete="off">
        <h2>登录</h2><div class="sub">使用局内账号登录</div>
        <div class="col gap3">
          <div class="field"><label>账号</label><input class="input" name="u" data-op="login.user" placeholder="如 wangmin" value="${esc(keepUser || '')}" ${keepUser ? '' : 'autofocus'}></div>
          <div class="field"><label>密码</label><input class="input" name="p" type="password" data-op="login.pass" placeholder="密码"></div>
          ${err ? `<div class="callout h-red">${icon('alert')}<span>${esc(err)}</span></div>` : ''}
          <button class="btn primary lg" data-op="login.go" style="width:100%;margin-top:4px">登录</button>
        </div>
        ${accts.length ? `<div class="sect" style="margin-top:28px">演示账号 · 点一下直接进入</div><div class="qlogin">${accts.map((a) => `<button type="button" class="ql" data-u="${esc(a.username)}" data-p="${esc(a.password)}"><span class="avatar h-${JK.hue(a.role, 'role')}">${esc(a.name[0])}</span><span class="grow"><div class="nm">${esc(a.name)} ${tag(a.role, 'role')}</div><div class="rl clip">${esc(a.username)} / ${esc(a.password)}</div></span></button>`).join('')}</div>` : ''}
      </form></div></div>`;
    const go = async (u, p) => { try { await API.auth.login({ username: u, password: p }); await afterLogin(); } catch (e) { renderLogin(e.message || '登录失败', u); const pw = $('#lf [name=p]'); if (pw) pw.focus(); } };
    $('#lf').onsubmit = (e) => { e.preventDefault(); go(e.target.u.value.trim(), e.target.p.value); };
    $$('.ql').forEach((b) => (b.onclick = () => go(b.dataset.u, b.dataset.p)));
  }
  async function switchUser(username) {
    const a = (CFG.demoAccounts || []).find((x) => x.username === username); if (!a) return;
    if (Op.running) Op.running.stop(true);
    await API.auth.logout().catch(() => {}); await API.auth.login({ username: a.username, password: a.password }); await afterLogin();
    toast(`已切换为 ${a.name}（${a.role}）`);
  }
  async function logout() { await API.auth.logout().catch(() => {}); S.me = null; renderLogin(); }

  /* ---------------- 外壳骨架 ---------------- */
  function renderShell() {
    root().innerHTML = `<div class="shell ${localStorage.getItem('jk4-side') === 'min' ? 'side-min' : ''}">
      <nav class="rail" id="rail" aria-label="主导航"></nav>
      <aside class="side">
        <div class="brand"><span class="brand-mark">${icon('cube')}</span><b class="grow clip">${esc(CFG.platformName)}</b><button class="btn icon sm ghost" id="btn-side" title="收起侧栏">${icon('sidebar')}</button></div>
        <div class="side-sc" id="side-sc"></div>
        <div class="side-foot">
          <a class="nav-i" id="btn-plan" href="plan.html" target="_blank" rel="noopener" title="开发计划与任务进度（GitHub 实时）" style="text-decoration:none"><span class="ico">${icon('flag')}</span><span class="t">开发计划</span><span class="tag">50 项</span></a>
          <button class="nav-i" id="btn-demo" data-op="shell.demo" title="把每个功能自动走一遍"><span class="ico">${icon('play')}</span><span class="t">一键演示</span><span class="tag">约 3 分钟</span></button>
          <div class="me" id="btn-me" data-op="shell.me"><span class="avatar h-${roleHue()}">${esc(S.me.name[0])}</span><span class="grow"><div class="nm clip">${esc(S.me.name)}</div><div class="rl clip">${esc([S.me.title, (S.me.dept || '').split(' · ').pop()].filter(Boolean).join(' · '))}</div></span><button class="btn icon sm ghost" id="btn-theme" title="切换深色 / 浅色">${icon(theme() === 'dark' ? 'sun' : 'moon')}</button></div>
        </div>
      </aside>
      <main class="main" id="main">
        <section class="chatcol" id="chatcol"><div class="dropmask">${icon('upload', 22)}&nbsp;松开，AI 识别文件并帮你处理</div></section>
        <section class="panel" id="panel"><div class="bar-h"><div class="ptabs" id="ptabs"></div><button class="btn icon sm ghost" id="btn-chat-toggle" title="显示 / 隐藏对话">${icon('chat')}</button><button class="btn icon sm ghost" id="btn-max" title="最大化">${icon('maximize')}</button><button class="btn icon sm ghost" id="btn-pclose" title="关闭面板">${icon('x')}</button></div><div class="pbody" id="pbody"></div></section>
      </main></div>`;
    renderSide(); renderChat(); bindShell();
  }
  /* 图标竖栏（multica rail）：顶层入口，每项 48px 图标 + 11px 小字 */
  function renderRail() {
    const el = $('#rail'); if (!el) return;
    const work = appsVisible('work').some((a) => a.id === S.active);
    const it = (k, ic, t, on, extra = '') => `<button class="rail-i ${on ? 'on' : ''}" ${k} title="${esc(t)}"><span class="ri">${ic}${extra}</span><span class="rt">${esc(t)}</span></button>`;
    const has = (id) => appsVisible('platform').some((a) => a.id === id);
    const pending = S.inbox.length;
    el.innerHTML = `<button class="rail-logo" data-act="side" title="${esc(CFG.platformName)} · 展开/收起侧栏">${icon('cube')}</button>
      ${it('data-nav="chat" data-op="rail.chat"', icon('chat'), '对话', !S.active || work)}
      ${it('data-nav="inbox" data-op="rail.inbox"', icon('inbox'), '收件箱', S.active === 'inbox', pending ? `<span class="rb">${pending}</span>` : '')}
      ${it('data-nav="cmdk" data-op="rail.cmdk"', icon('search'), '搜索', false)}
      ${has('kb') ? it('data-app="kb" data-op="rail.kb"', icon(mf('kb').icon || 'book'), '知识库', S.active === 'kb') : ''}
      ${has('skills') ? it('data-app="skills" data-op="rail.skills"', icon(mf('skills').icon || 'wand'), '技能', S.active === 'skills') : ''}
      ${has('computer') ? it('data-app="computer" data-op="rail.computer"', icon(mf('computer').icon || 'computer'), '电脑', S.active === 'computer') : ''}
      ${isAdmin() ? it('data-nav="admin" data-op="rail.admin"', icon('shield'), '后台', S.active === 'admin') : ''}
      <span class="sp"></span>
      ${it('data-act="demo" data-op="rail.demo"', icon('play'), '演示', false)}`;
  }
  function renderSide() {
    renderRail();
    const el = $('#side-sc'); if (!el) return;
    const navApp = (a) => { const m = mf(a.id); return `<button class="nav-i ${S.active === a.id ? 'on' : ''}" data-app="${a.id}" data-op="nav.${a.id}" title="${esc(m.summary || m.name)}">${appIcon(a.id, 'sm')}<span class="t">${esc(m.name)}</span></button>`; };
    const pending = S.inbox.length;
    el.innerHTML = `
      <button class="nav-i entry" data-nav="chat" data-op="nav.chat" title="新对话">${icon('chat')}<span class="t">总控对话</span><span class="kbd">新</span></button>
      <button class="nav-i" data-nav="cmdk" data-op="nav.cmdk">${icon('search')}<span class="t">搜索与命令</span><span class="kbd">⌘K</span></button>
      <button class="nav-i ${S.active === 'inbox' ? 'on' : ''}" data-nav="inbox" data-op="nav.inbox">${icon('inbox')}<span class="t">收件箱</span>${pending ? `<span class="count">${pending}</span>` : ''}</button>
      ${appsVisible('work').length ? `<div class="side-h">应用</div>${appsVisible('work').map(navApp).join('')}` : ''}
      ${appsVisible('platform').length || isAdmin() ? `<div class="side-h">平台</div>${appsVisible('platform').map(navApp).join('')}${isAdmin() ? `<button class="nav-i ${S.active === 'admin' ? 'on' : ''}" data-nav="admin" data-op="nav.admin">${appIcon('admin', 'sm')}<span class="t">管理后台</span></button>` : ''}` : ''}
      <div class="side-h">最近对话</div>
      <div class="hist">${S.convs.slice(0, 6).map((c) => `<button class="nav-i ${S.cur === c.id ? 'on' : ''}" data-conv="${c.id}"><span class="t">${esc(c.title)}</span><span class="tm">${esc(c.at || '')}</span><span class="del" data-del="${c.id}" title="删除对话">${icon('x')}</span></button>`).join('') || '<div class="t-3 t-xs" style="padding:4px 10px">还没有对话</div>'}</div>`;
  }
  function bindShell() {
    $('#side-sc').onclick = (e) => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.dataset.app) { const id = b.dataset.app; const had = S.mounted[id]; if (S.active === id && had && had.ctl.go) { try { had.ctl.go('home', {}); } catch (e) {} return; } return openApp(id).then(() => { if (had && had.ctl && had.ctl.go && !(Op.running)) { try { had.ctl.go('home', {}); } catch (e) {} } }); }
      const del = e.target.closest('[data-del]'); if (del) { const id = del.dataset.del; const old = S.convs.slice(); S.convs = S.convs.filter((c) => c.id !== id); if (S.cur === id) S.cur = null; saveConvs(); renderSide(); renderChatBody(); toast('对话已删除', { action: { label: '撤销', fn: () => { S.convs = old; saveConvs(); renderSide(); } } }); return; }
      if (b.dataset.conv) return openConv(b.dataset.conv);
      const n = b.dataset.nav; if (n === 'chat') newChat(); else if (n === 'cmdk') cmdk(); else if (n) openBuiltin(n);
    };
    $('#rail').onclick = (e) => { const b = e.target.closest('button'); if (!b) return; if (b.dataset.act === 'demo') return window.JKDemo && JKDemo.start(); if (b.dataset.act === 'side') return $('#btn-side').click(); if (b.dataset.app) return openApp(b.dataset.app); const n = b.dataset.nav; if (n === 'chat') return newChat(); if (n === 'cmdk') return cmdk(); if (n) openBuiltin(n); };
    $('#btn-side').onclick = () => { const s = $('.shell'); s.classList.toggle('side-min'); localStorage.setItem('jk4-side', s.classList.contains('side-min') ? 'min' : ''); };
    $('#btn-theme').onclick = (e) => { e.stopPropagation(); setTheme(theme() === 'dark' ? 'light' : 'dark'); };
    $('#btn-me').onclick = (e) => { if (e.target.closest('#btn-theme')) return; meMenu($('#btn-me')); };
    $('#btn-demo').onclick = () => window.JKDemo && JKDemo.start();
    $('#btn-max').onclick = () => setLayout(S.layout === 'max' ? 'split' : 'max');
    $('#btn-chat-toggle').onclick = () => setLayout(S.layout === 'max' ? 'split' : 'max');
    $('#btn-pclose').onclick = () => closePanel();
    $('#ptabs').onclick = (e) => { const x = e.target.closest('.x'); const t = e.target.closest('.ptab'); if (!t) return; if (x) return closeTab(t.dataset.id); activate(t.dataset.id); };
    // 拖文件
    const cc = $('#chatcol'); let dc = 0;
    cc.addEventListener('dragenter', (e) => { if ([...(e.dataTransfer.types || [])].includes('Files')) { dc++; cc.classList.add('dragging'); e.preventDefault(); } });
    cc.addEventListener('dragover', (e) => { if ([...(e.dataTransfer.types || [])].includes('Files')) e.preventDefault(); });
    cc.addEventListener('dragleave', () => { dc = Math.max(0, dc - 1); if (!dc) cc.classList.remove('dragging'); });
    cc.addEventListener('drop', (e) => { e.preventDefault(); dc = 0; cc.classList.remove('dragging'); const f = e.dataTransfer.files && e.dataTransfer.files[0]; if (f) readFile(f).then(handleFile); });
  }
  if (!window.__jk4keys) { window.__jk4keys = 1; document.addEventListener('keydown', (e) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k' && S.me) { e.preventDefault(); cmdk(); } if (e.key === 'Escape' && Op.running && !$('.modal')) Op.running.stop(); }); }
  function meMenu(anchor) {
    const items = [{ head: `${S.me.name} · ${roleName()}` }, { v: 'settings', icon: 'user', label: '个人设置' }];
    if (isAdmin()) items.push({ v: 'admin', icon: 'shield', label: '管理后台' });
    items.push({ head: '切换视角（演示）' }); (CFG.demoAccounts || []).forEach((a) => items.push({ v: 'as:' + a.username, lead: `<span class="avatar h-${JK.hue(a.role, 'role')}" style="width:20px;height:20px;font-size:10px;flex:none">${esc(a.name[0])}</span>`, label: a.name, right: `<span class="t-3 t-xs">${esc(a.role)}</span>`, on: a.username === S.me.username }));
    items.push({ sep: true }, { v: 'reset', icon: 'refresh', label: '重置演示数据' }, { v: 'logout', icon: 'logout', label: '退出登录' });
    menu(anchor, items, async (v) => { if (v === 'settings') openSettings(); else if (v === 'admin') openBuiltin('admin'); else if (v.startsWith('as:')) switchUser(v.slice(3)); else if (v === 'reset') { if (await JK.confirm('会清空本机所有修改，恢复初始演示数据。', { okText: '重置', danger: true })) reset(); } else if (v === 'logout') logout(); });
  }
  async function reset() { await API.demo.reset(); localStorage.removeItem(storeKey()); try { await API.auth.login({ username: S.me.username, password: (CFG.demoAccounts.find((a) => a.username === S.me.username) || { password: 'jk123456' }).password }); } catch (e) { return renderLogin(); } JK.bus.emit('data:reset'); await afterLogin(); toast('演示数据已重置'); }

  /* ---------------- 布局与面板 ---------------- */
  const shellRoutedApps = ['policy', 'enterprise', 'meeting', 'document'];
  async function waitForApp(ctl) {
    if (typeof ctl.ready !== 'function') return true;
    let timer;
    try {
      return await Promise.race([
        Promise.resolve(ctl.ready()).then(() => true),
        new Promise((resolve) => { timer = setTimeout(() => resolve(false), 3000); }),
      ]);
    } catch (e) {
      return true;
    } finally {
      clearTimeout(timer);
    }
  }
  function mountApp(id, params) {
    const view = h(`<div class="pview" data-view="${id}"><div class="app-root app-${id}"></div></div>`);
    $('#pbody').appendChild(view);
    const el = view.firstElementChild; const ctx = makeCtx(id, el, params);
    const slot = S.mounted[id] = { view, el, ctx, ctl: null };
    try { slot.ctl = JK.registry[id].mount(el, ctx) || {}; } catch (e) { console.error(e); el.innerHTML = JK.empty({ icon: 'alert', title: '应用加载出错', desc: String(e.message || e) }); slot.ctl = {}; }
    return slot;
  }
  function setLayout(l) { S.layout = l; const m = $('#main'); if (!m) return; m.classList.toggle('split', l === 'split'); m.classList.toggle('max', l === 'max'); $('#btn-max').innerHTML = icon(l === 'max' ? 'minimize' : 'maximize'); renderChatBody(); }
  async function openApp(id, route, params) {
    if (!JK.registry[id]) { toast('该应用还没有启用', { type: 'warn' }); return; }
    if (!can(id, 'view')) { toast(`你的角色没有「${mf(id).name}」的使用权限`, { type: 'err' }); return; }
    if (!S.open.includes(id)) { S.open.push(id); S.lru = (S.lru || []).filter((x) => x !== id); }
    S.lru = [...(S.lru || []).filter((x) => x !== id), id];
    if (S.open.length > 6) { const old = S.lru.find((x) => x !== id && S.open.includes(x)) || S.open.find((x) => x !== id); if (old) { closeTab(old); S.lru = S.lru.filter((x) => x !== old); } }
    let slot = S.mounted[id]; const fresh = !slot;
    const args = { ...params };
    if (!slot) slot = mountApp(id, args);
    const hasParams = Object.keys(args).length > 0;
    // 这四个应用的 mount 只初始化首屏，其余应用保留已有的 ctx.params 初始化。
    const shouldGo = fresh ? shellRoutedApps.includes(id) && route && (route !== 'home' || hasParams) : route || hasParams;
    const navigation = slot.navigation = {};
    if (args.via !== 'operator') {
      // 恢复历史时打开电脑操作首页，避免重复启动操作。
      if (id === 'computer' && route === 'run') rememberPanel(id);
      else rememberPanel(id, route, args);
    }
    activate(id); if (S.layout !== 'max') setLayout('split');
    const ready = await waitForApp(slot.ctl);
    if (S.mounted[id] !== slot || slot.navigation !== navigation) return;
    if (!ready) {
      console.warn(`「${mf(id).name}」等待就绪超过 3 秒，已显示首页`);
      if (S.active === id && args.via !== 'operator') rememberPanel(id);
      if (hasParams || !fresh) {
        const active = S.active;
        unmountApp(id);
        slot = mountApp(id, {});
        activate(active);
      }
      return slot;
    }
    if (shouldGo && slot.ctl.go) {
      slot.ctx.params = args;
      try { await slot.ctl.go(route || 'home', args); } catch (e) { console.error(e); }
    }
    await sleep(fresh ? 160 : 30);
    return slot;
  }
  function openBuiltin(id, tab) {
    if (id === 'admin' && !isAdmin()) { toast('需要管理员权限', { type: 'err' }); return; }
    if (!S.open.includes(id)) { S.open.push(id); S.lru = (S.lru || []).filter((x) => x !== id); }
    S.lru = [...(S.lru || []).filter((x) => x !== id), id];
    if (S.open.length > 6) { const old = S.lru.find((x) => x !== id && S.open.includes(x)) || S.open.find((x) => x !== id); if (old) { closeTab(old); S.lru = S.lru.filter((x) => x !== old); } }
    let slot = S.mounted[id]; const fresh = !slot;
    if (!slot) { const view = h(`<div class="pview" data-view="${id}"><div class="app-root pad"></div></div>`); $('#pbody').appendChild(view); slot = S.mounted[id] = { view, el: view.firstElementChild, builtin: true, ctl: {} }; }
    slot.tab = tab || slot.tab; renderBuiltin(id);
    activate(id); if (S.layout !== 'max') setLayout('split');
    return sleep(30);
  }
  function renderBuiltin(id) { const slot = S.mounted[id]; if (!slot) return; if (id === 'inbox') renderInbox(slot.el); else if (id === 'admin') window.JKAdmin.render(slot.el, slot.tab || 'users', shellApi); }
  function activate(id) {
    S.active = id; $$('.pview').forEach((v) => v.classList.toggle('on', v.dataset.view === id));
    $('#ptabs').innerHTML = S.open.map((x) => `<button class="ptab ${x === id ? 'on' : ''}" data-id="${x}">${appIcon(x, 'sm')}<span>${esc(mf(x).short || mf(x).name)}</span><span class="x" title="关闭">${icon('x')}</span></button>`).join('');
    const pt = $('#ptabs'); pt.classList.toggle('many', S.open.length > 4); const on = pt.querySelector('.ptab.on'); if (on) on.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    renderSide();
  }
  function unmountApp(id) {
    const slot = S.mounted[id]; if (slot) { try { slot.ctl && slot.ctl.unmount && slot.ctl.unmount(); } catch (e) {} slot.view.remove(); delete S.mounted[id]; }
  }
  function closeTab(id) {
    unmountApp(id);
    S.open = S.open.filter((x) => x !== id); if (!S.open.length) return closePanel(); if (S.active === id) activate(S.open[S.open.length - 1]); else activate(S.active);
  }
  function closePanel() { S.open.forEach(unmountApp); S.open = []; S.active = null; S.layout = 'home'; const m = $('#main'); m.classList.remove('split', 'max'); renderSide(); renderChatBody(); }

  /* ---------------- ctx（注入应用） ---------------- */
  function makeCtx(id, el, params) {
    const ui = { tag: (l, g, o) => tag(l, g, o), hue: JK.hue, icon: (n, s) => icon(n, s), appIcon: (a, s) => appIcon(a, s), toast, modal: JK.modal, drawer: JK.drawer, confirm: JK.confirm, menu: JK.menu, empty: JK.empty, steps: JK.steps, esc, md, download: JK.download, fmtMoney: JK.fmtMoney, fmtDate: JK.fmtDate };
    const api = Object.assign(Object.create(window.JKApi), { get: (p, q) => H.get(p, q), post: H.post, put: H.put, patch: H.patch, del: H.del, request: H.request });
    const kb = {
      search: (q, o = {}) => (JK.services.kb && JK.services.kb.search ? JK.services.kb.search(q, o) : API.kb.search({ q, lib: o.space || o.lib, filters: o.filters })),
      ask: (q, o = {}) => (JK.services.kb && JK.services.kb.ask ? JK.services.kb.ask(q, o) : API.kb.ask({ q, lib: o.space || o.lib })),
      open: (docId, o = {}) => (JK.services.kb && JK.services.kb.open ? JK.services.kb.open(docId, o) : openApp('kb', 'doc', { fileId: docId, highlight: o.highlight })),
      spaces: () => (JK.services.kb && JK.services.kb.spaces ? JK.services.kb.spaces() : API.kb.libraries().then((r) => r.items)),
      import: (files, o = {}) => (JK.services.kb && JK.services.kb.import ? JK.services.kb.import(files, o) : Promise.resolve({ docs: [] })),
    };
    return {
      appId: id, api, kb, ui, bus: JK.bus, params,
      get user() { return { id: S.me.id, name: S.me.name, role: S.me.role, roleName: roleName(), dept: S.me.dept, title: S.me.title, username: S.me.username }; },
      perms: { can: (action, app) => can(app || id, action), mask: maskVal, get isPartner() { return !!(S.role && S.role.mask); } },
      theme: { get: theme, on: (f) => JK.bus.on('theme', f) },
      nav: { open: (a, r, p) => (a === 'inbox' || a === 'admin' ? openBuiltin(a, r) : openApp(a, r, p)), go: (r, p) => { const s = S.mounted[id]; s && s.ctl.go && s.ctl.go(r, p); }, back: () => {}, chat: (text) => send(text) },
      operator: { isRunning: () => !!Op.running },
      chat: { post: (card) => postAI(typeof card === 'string' ? { text: card } : card), say: (t) => postAI({ text: t }) },
      audit: (action, detail) => H.post('/api/v1/audit', { app: mf(id).name, action: detail ? `${action} · ${detail}` : action }).catch(() => {}),
    };
  }

  /* ---------------- 对话 ---------------- */
  function conv() { return S.convs.find((c) => c.id === S.cur); }
  function rememberPanel(app, route = 'home', params = {}) {
    const c = conv(); if (!c) return;
    c.panel = { app, route, params: { ...params } };
    saveConvs();
  }
  function switchConversation(id) {
    if (Op.running) Op.running.stop(true);
    S.cur = id;
    // go('home') 会保留部分应用的企业和向导状态，关闭挂载才能完整复位。
    closePanel();
    const panel = conv()?.panel;
    if (panel) return openApp(panel.app, panel.route, panel.params);
  }
  function newChat() {
    switchConversation(null);
    setTimeout(() => { const t = $('#chatcol textarea'); t && t.focus(); }, 30);
  }
  function openConv(id) { if (id !== S.cur) return switchConversation(id); }
  function ensureConv(title) { let c = conv(); if (!c) { c = { id: 'c' + Date.now().toString(36), title: title.slice(0, 18), at: nowHM(), msgs: [] }; S.convs.unshift(c); S.cur = c.id; renderSide(); } return c; }
  function renderChat() { renderChatBody(); }
  function renderChatBody() {
    const cc = $('#chatcol'); if (!cc) return; const mask = cc.querySelector('.dropmask');
    [...cc.children].forEach((x) => { if (x !== mask) x.remove(); });
    const c = conv();
    if (!c) { cc.appendChild(homeView()); }
    else {
      const head = h(`<div class="bar-h"><span class="ttl clip">${esc(c.title)}</span><span class="sp"></span>${modelChip()}<button class="btn icon sm ghost" data-op="chat.new" title="新对话">${icon('plus')}</button></div>`);
      const box = h('<div class="msgs scroll"><div class="msgs-in"></div></div>');
      cc.append(head, box, composer());
      head.querySelector('[data-op="chat.new"]').onclick = newChat; bindModelChip(head);
      c.msgs.forEach((m) => box.firstElementChild.appendChild(renderMsg(m)));
      scrollEnd();
    }
  }
  function homeView() {
    const sugs = (CFG.homeSuggestions || []).filter((s) => !s.app || JK.registry[s.app] && can(s.app, 'view')).slice(0, 3);
    const apps = appsVisible('work').slice(0, 4);
    const v = h(`<div class="home scroll">
      <div style="position:absolute;top:10px;right:16px">${modelChip()}</div>
      <div class="hello">${esc(S.me.name)}，${greet()}</div>
      <div class="hello-sub">说一句要办的事，我在右边替你操作；关键一步会停下来等你确认。</div>
      ${composerHTML(true)}
      <div class="sugs">${sugs.map((s) => `<button class="sug" data-say="${esc(s.text)}">${s.app ? appIcon(s.app, 'sm') : icon(s.icon)}<span>${esc(s.text)}</span><span class="arrow">${icon('arrow-right')}</span></button>`).join('')}</div>
      ${S.layout === 'home' && apps.length ? `<div class="quick-apps">${apps.map((a) => { const m = mf(a.id); return `<button class="qa" data-app="${a.id}">${appIcon(a.id)}<div><div class="n">${esc(m.name)}</div><div class="d clamp2">${esc(m.summary || '')}</div></div></button>`; }).join('')}</div>` : ''}
    </div>`);
    v.style.position = 'relative';
    bindComposer(v); bindModelChip(v);
    v.querySelectorAll('[data-say]').forEach((b) => (b.onclick = () => send(b.dataset.say)));
    v.querySelectorAll('.qa').forEach((b) => (b.onclick = () => openApp(b.dataset.app)));
    return v;
  }
  function composerHTML(big) {
    return `<div class="composer" data-op="chat.composer"><div class="pending-file hide"></div><textarea rows="${big ? 2 : 1}" data-op="chat.input" placeholder="${esc(CFG.composerPlaceholder || '说一句要办的事')}"></textarea>
      <div class="tools"><button class="btn icon sm ghost" data-act="attach" data-op="chat.attach" title="添加文件（也可以直接拖进来或粘贴）">${icon('paperclip')}</button><button class="btn icon sm ghost" data-act="at" title="指定应用">${icon('grid')}</button><span class="sp"></span><span class="t-3 t-xs" data-hint></span><button class="send" data-act="send" data-op="chat.send" disabled title="发送（Enter）">${icon('send')}</button></div></div>`;
  }
  function composer() { const w = h(`<div class="composer-wrap">${composerHTML(false)}</div>`); bindComposer(w); return w; }
  let pendingFile = null;
  function bindComposer(scope) {
    const ta = scope.querySelector('textarea'); const sendB = scope.querySelector('[data-act="send"]'); const pf = scope.querySelector('.pending-file');
    const upd = () => { sendB.disabled = !ta.value.trim() && !pendingFile; ta.style.height = 'auto'; ta.style.height = Math.min(180, ta.scrollHeight) + 'px'; };
    const showPF = () => { if (!pendingFile) { pf.classList.add('hide'); pf.innerHTML = ''; return; } pf.classList.remove('hide'); pf.innerHTML = fileChip(pendingFile, true); pf.querySelector('[data-rm]').onclick = () => { pendingFile = null; showPF(); upd(); }; };
    ta.addEventListener('input', () => { upd(); if (ta.value === '/') { ta.value = ''; upd(); scope.querySelector('[data-act="at"]').click(); } });
    ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); go(); } });
    ta.addEventListener('paste', (e) => {
      const f = e.clipboardData && e.clipboardData.files && e.clipboardData.files[0]; if (f) { e.preventDefault(); readFile(f).then((x) => { pendingFile = x; showPF(); upd(); }); return; }
      const t = e.clipboardData && e.clipboardData.getData('text'); if (t && t.length > 160) { e.preventDefault(); pendingFile = { name: '粘贴的文本（' + t.length + ' 字）.txt', ext: 'txt', size: t.length + ' 字', text: t, pasted: true }; showPF(); upd(); }
    });
    const go = () => { const t = ta.value.trim(); const f = pendingFile; if (!t && !f) return; ta.value = ''; pendingFile = null; showPF(); upd(); if (f) handleFile(f, t); else send(t); };
    sendB.onclick = go;
    scope.querySelector('[data-act="attach"]').onclick = (e) => attachMenu(e.currentTarget, (f) => { pendingFile = f; showPF(); upd(); ta.focus(); });
    scope.querySelector('[data-act="at"]').onclick = (e) => menu(e.currentTarget, [{ head: '让 AI 用哪个应用' }, ...[...appsVisible('work'), ...appsVisible('platform')].map((a) => ({ v: a.id, lead: appIcon(a.id, 'sm'), label: mf(a.id).name, desc: mf(a.id).summary || '' }))], (v) => { const st = (mf(v).starters || [])[0]; ta.value = st || ('打开' + mf(v).name); upd(); ta.focus(); });
    showPF(); upd();
  }
  function attachMenu(anchor, pick) {
    const samples = window.JK_SAMPLE_FILES || [];
    menu(anchor, [{ v: '__pick', icon: 'upload', label: '从电脑选择文件…' }, { head: '试试样例文件' }, ...samples.map((s) => ({ v: s.id, lead: fileIco(s), label: s.name }))], (v) => {
      if (v === '__pick') { const inp = h('<input type="file" style="display:none">'); document.body.appendChild(inp); inp.onchange = () => { const f = inp.files[0]; inp.remove(); if (f) readFile(f).then(pick); }; inp.click(); return; }
      const s = samples.find((x) => x.id === v); if (s) pick({ ...s, sample: true });
    });
  }
  async function readFile(f) {
    const ext = (f.name.split('.').pop() || '').toLowerCase(); const size = f.size > 1048576 ? (f.size / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(f.size / 1024)) + ' KB';
    let text = ''; if (/^(txt|md|csv|json|html?)$/.test(ext) || (f.type || '').startsWith('text')) { try { text = (await f.text()).slice(0, 20000); } catch (e) {} }
    const kind = /^(mp3|m4a|wav|aac|amr|ogg)$/.test(ext) ? '会议录音' : /^(png|jpe?g|gif|webp)$/.test(ext) ? '图片' : /^(xlsx?|csv)$/.test(ext) ? '表格' : undefined;
    return { name: f.name, ext, size, text, kind, real: true };
  }
  const KIND_ICON = { 会议录音: 'mic', 会议纪要: 'meeting', 公文草稿: 'doc', 政策文件: 'policy', 企业资料: 'building', 表格: 'table', 图片: 'eye', 其他: 'file' };
  const fileIco = (f) => { const k = f.kind || '其他'; return `<span class="app-ico sm h-${JK.hue(k, 'fileKind')}">${icon(KIND_ICON[k] || 'file')}</span>`; };
  const fileChip = (f, rm) => `<div class="file-chip h-${JK.hue(f.kind || '其他', 'fileKind')}"><span class="fi">${icon(KIND_ICON[f.kind] || 'file')}</span><span class="grow" style="min-width:0"><div class="fn clip">${esc(f.name)}</div><div class="fm">${esc(f.size || '')}${f.kind ? ' · ' + esc(f.kind) : ''}</div></span>${rm ? `<button class="btn icon sm ghost" data-rm title="移除">${icon('x')}</button>` : ''}</div>`;
  function modelChip() { const m = S.models.find((x) => x.id === S.model) || { name: '自动选择' }; return `<button class="model-chip" data-op="chat.model" title="切换模型"><span class="sdot"></span>${esc(m.name)}${icon('chevron-down')}</button>`; }
  function bindModelChip(scope) { const b = scope.querySelector('.model-chip'); if (b) b.onclick = () => modelMenu(b); }
  function modelMenu(anchor) {
    const groups = {}; S.models.forEach((m) => (groups[m.group] = groups[m.group] || []).push(m));
    const items = []; Object.entries(groups).forEach(([g, list]) => { items.push({ head: g }); list.forEach((m) => items.push({ v: m.id, on: m.id === S.model, disabled: !m.enabled, label: m.name, desc: m.enabled ? m.desc : '管理员开启后可用', right: m.kind === 'local' ? tag('本地', null, { hue: 'green' }) : !m.enabled ? tag('未开启', null, { hue: 'gray' }) : '' })); });
    const mm = menu(anchor, items, async (v) => { const m = S.models.find((x) => x.id === v); if (!m.enabled) return toast('该模型默认关闭（政务数据不出境），需管理员开启', { type: 'warn' }); try { await API.models.setCurrent(v); } catch (e) { return toast((e && e.message) || '切换失败', { type: 'warn' }); } S.model = v; renderChatBody(); toast('已切换到 ' + m.name); });
    mm.style.width = '340px';
  }
  async function setModel(text) {
    const t = text.toLowerCase(); const key = [['deepseek', 'deepseek'], ['千问', 'qwen'], ['通义', 'qwen'], ['qwen', 'qwen'], ['kimi', 'kimi'], ['智谱', 'glm'], ['glm', 'glm'], ['豆包', 'doubao'], ['文心', 'ernie'], ['混元', 'hunyuan'], ['本地', 'local'], ['自动', 'auto'], ['gpt', 'gpt'], ['claude', 'claude']].find(([k]) => t.includes(k));
    if (!key) return null; const m = S.models.find((x) => x.id.includes(key[1]) && x.enabled); if (!m) return null;
    await API.models.setCurrent(m.id); S.model = m.id; $$('.model-chip').forEach((b) => (b.outerHTML = modelChip())); $$('#chatcol .bar-h, #chatcol .home').forEach(bindModelChip); return m;
  }

  /* 消息渲染 */
  function scrollEnd() { const b = $('#chatcol .msgs'); if (b) b.scrollTop = b.scrollHeight; }
  function push(m) { const c = ensureConv(m.text || m.title || '新对话'); c.msgs.push(m); c.at = nowHM(); saveConvs(); if (!$('#chatcol .msgs')) renderChatBody(); else { $('#chatcol .msgs-in').appendChild(renderMsg(m)); } scrollEnd(); return m; }
  function renderMsg(m) {
    if (m.role === 'user') return h(`<div class="msg user"><div class="col" style="align-items:flex-end;max-width:86%">${m.file ? fileChip(m.file) : ''}${m.text ? `<div class="bubble">${esc(m.text)}</div>` : ''}</div></div>`);
    if (m.role === 'plan') return planEl(m);
    const el = h(`<div class="msg ai"><div class="av">${icon('sparkles')}</div><div class="body"><div class="txt">${md(m.text || '')}</div></div></div>`);
    const body = el.querySelector('.body');
    if (m.cites && m.cites.length) {
      body.appendChild(h(`<div class="srcs">${m.cites.slice(0, 4).map((c) => `<div class="src" data-cid="${esc(c.id || '')}" data-hl="${esc((c.snippet || '').slice(0, 60))}"><span class="n">${c.n}</span><span class="grow" style="min-width:0"><div class="st clip">${esc(c.title || '')}</div><div class="sm clip">${esc([c.source && c.source.docNo, c.source && c.source.org, c.source && c.source.date].filter(Boolean).join(' · ') || (c.snippet || '').slice(0, 40))}</div></span>${c.source && c.source.url ? `<a class="btn icon sm ghost" href="${esc(c.source.url)}" target="_blank" rel="noopener" title="官网原文">${icon('external')}</a>` : ''}</div>`).join('')}</div>`));
      body.querySelectorAll('.src').forEach((s) => (s.onclick = (e) => { if (e.target.closest('a')) return; openCite(s.dataset.cid, s.dataset.hl); }));
      body.querySelectorAll('.cite').forEach((c) => (c.onclick = () => { const x = m.cites.find((y) => String(y.n) === c.dataset.cite); if (x) openCite(x.id, (x.snippet || '').slice(0, 60)); }));
    }
    if (m.next && m.next.length) { const n = h(`<div class="next-acts">${m.next.map((a, i) => `<button class="btn" data-i="${i}">${esc(a.label)}</button>`).join('')}</div>`); n.onclick = (e) => { const b = e.target.closest('[data-i]'); if (!b) return; const a = m.next[+b.dataset.i]; if (a.say) send(a.say); else if (a.open) openApp(a.open, a.route, a.params); }; body.appendChild(n); }
    if (m.model) { const meta = h(`<div class="meta"><span>${esc(m.model)}${m.routeNote ? ' · ' + esc(m.routeNote) : ''}</span><span class="sp"></span><button class="btn sm ghost" data-a="copy" title="复制">${icon('copy')}</button>${m.q ? `<button class="btn sm ghost" data-a="redo" title="换个模型重答">${icon('refresh')}</button>${JK.registry.skills ? `<button class="btn sm ghost" data-a="skill" title="存为我的技能">${icon('skill')}</button>` : ''}` : ''}</div>`); body.appendChild(meta);
      meta.onclick = (e) => { const b = e.target.closest('[data-a]'); if (!b) return; const a = b.dataset.a;
        if (a === 'copy') { const t = (m.text || '').replace(/\*\*/g, ''); (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(() => toast('已复制'), () => toast('已复制')); }
        if (a === 'redo') { const others = S.models.filter((x) => x.enabled && x.id !== S.model && x.kind !== 'route').slice(0, 6); menu(b, [{ head: '换个模型重答' }, ...others.map((x) => ({ v: x.id, label: x.name }))], async (v) => { await API.models.setCurrent(v); S.model = v; $$('.model-chip').forEach((c) => (c.outerHTML = modelChip())); $$('#chatcol .bar-h, #chatcol .home').forEach(bindModelChip); answer(m.q); }); }
        if (a === 'skill') send('帮我做一个技能：' + m.q); }; }
    return el;
  }
  function openCite(id, hl) { if (!id) return; if (JK.services.kb && JK.services.kb.open) JK.services.kb.open(id, { highlight: hl }); else if (JK.registry.kb) openApp('kb', 'doc', { fileId: id, highlight: hl }); }
  function postAI(o) { return push({ role: 'ai', text: o.text, cites: o.cites, next: o.next, model: o.model, routeNote: o.routeNote, q: o.q }); }
  function planEl(m) {
    const el = h(`<div class="msg ai"><div class="av">${icon('sparkles')}</div><div class="body"><div class="plan"><div class="plan-h">${m.appId && m.appId !== 'shell' && (JK.registry[m.appId] || JK.BUILTIN[m.appId]) ? appIcon(m.appId, 'sm') : icon('bolt')}<span class="ptitle">${esc(m.title)}</span><span class="sp"></span><span class="pstate"></span></div><div class="psteps"></div><div class="pnotes"></div><div class="pask"></div></div></div></div>`);
    const draw = () => {
      el.querySelector('.psteps').innerHTML = m.steps.map((s, i) => `<div class="pstep ${s.s}"><span class="pi"></span><span>${i + 1}. ${esc(s.t)}</span></div>`).join('');
      el.querySelector('.pnotes').innerHTML = (m.notes || []).slice(-2).map((n) => `<div class="t-3 t-xs" style="padding-left:30px">${esc(n)}</div>`).join('');
      const st = el.querySelector('.pstate');
      st.innerHTML = m.state === 'run' ? `<button class="btn sm ghost" data-stop title="Esc">${icon('hand')}我来接手</button>` : m.state === 'done' ? tag('已完成') : m.state === 'fail' ? tag('失败') : m.state === 'stopped' ? tag('已停下', null, { hue: 'gray' }) : '';
      const sb = st.querySelector('[data-stop]'); if (sb) sb.onclick = () => m._card && m._card.onStop && m._card.onStop();
      const pl = el.querySelector('.plan'); const fin = m.state && m.state !== 'run';
      if (fin && m._open === undefined) pl.classList.add('folded'); else if (!fin) pl.classList.remove('folded');
      let pc = el.querySelector('.pcount'); if (!pc) { pc = h('<span class="pcount"></span>'); el.querySelector('.ptitle').after(pc); }
      pc.textContent = fin ? ` · ${m.steps.length} 步` : '';
    };
    el.querySelector('.plan-h').addEventListener('click', (e) => { if (e.target.closest('button')) return; const pl = el.querySelector('.plan'); if (!m.state || m.state === 'run') return; m._open = !pl.classList.contains('folded') ? undefined : true; pl.classList.toggle('folded'); });
    draw(); m._draw = draw; Object.defineProperty(m, '_el', { value: el, enumerable: false, writable: true, configurable: true }); return el;
  }
  function postPlan({ title, appId, steps }) {
    const m = push({ role: 'plan', title, appId, steps: steps.map((t) => ({ t, s: 'todo' })), state: 'run', notes: [] });
    const node = $$('#chatcol .msgs-in > .msg').pop();
    const askBox = () => ((m._el && m._el.isConnected ? m._el : node).querySelector('.pask')); // 对话区重绘后仍找到当前卡片
    const card = {
      set(k, s) { if (m.steps[k]) m.steps[k].s = s; m._draw(); saveConvs(); },
      note(t) { m.notes.push(t); m._draw(); scrollEnd(); },
      ask(q, opts, cb) {
        const overlayOpen = !!document.querySelector('.modal:not(.cmdk),.drawer');
        if (overlayOpen) { const f = h(`<div class="op-ask"><div class="row" style="gap:8px;align-items:flex-start">${icon('hand')}<div class="grow">${md(q)}</div></div><div class="row" style="justify-content:flex-end;margin-top:10px">${opts.map((o, i) => `<button class="btn sm ${i === 0 ? 'primary' : ''}" data-o="${esc(o)}">${esc(o)}</button>`).join('')}</div></div>`); document.body.appendChild(f); card._float = f; f.onclick = (e) => { const b = e.target.closest('[data-o]'); if (!b) return; const ib = askBox().querySelector(`[data-o="${CSS.escape(b.dataset.o)}"]`); if (ib) ib.click(); }; }
        const a = askBox(); a.innerHTML = `<div class="ask"><div>${md(q)}</div><div class="row">${opts.map((o, i) => `<button class="btn sm ${i === 0 ? 'primary' : ''}" data-o="${esc(o)}">${esc(o)}</button>`).join('')}</div></div>`; a.onclick = (e) => { const b = e.target.closest('[data-o]'); if (!b) return; if (card._float) { card._float.remove(); card._float = null; } a.innerHTML = `<div class="t-3 t-xs" style="padding:2px 0 0 30px">${icon('check')} 你选择了：${esc(b.dataset.o)}</div>`; m.notes.push('你选择了：' + b.dataset.o); cb(b.dataset.o); }; scrollEnd(); },
      pick(o) { if (card._float) { const fb = card._float.querySelector(`[data-o="${CSS.escape(o)}"]`); if (fb) return fb.click(); } const b = askBox().querySelector(`[data-o="${CSS.escape(o)}"]`); if (b) b.click(); },
      finish(state) { m.state = state; askBox().innerHTML = ''; if (card._float) { card._float.remove(); card._float = null; } m._draw(); saveConvs(); },
      onStop: null,
    };
    Object.defineProperty(m, '_card', { value: card, enumerable: false, writable: true });
    return card;
  }

  /* 发送：理解 → 操作 / 确认 / 回答 */
  async function send(text, opt = {}) {
    text = String(text || '').trim(); if (!text) return;
    if (!opt.silentUser) push({ role: 'user', text });
    const current = conv();
    const u = Op.understand(text); const b = u.best;
    if (!u.slots.ent && !opt.noFuzzy) { const fz = Op.fuzzyEnt(text); if (fz) {
      const fixed = text.replace(fz.span, fz.ent.short);
      if (Op.demo) return send(fixed, { silentUser: true, noFuzzy: true });
      const m = postAI({ text: `你是不是想说「**${fz.ent.short}**」（${fz.ent.name}）？`, next: [{ label: '是，' + fz.ent.short }, { label: '不是' }] });
      const node = $$('#chatcol .msgs-in > .msg').pop(); const n = node.querySelector('.next-acts');
      if (n) n.onclick = (e) => { const bb = e.target.closest('[data-i]'); if (!bb) return; n.remove(); if (bb.dataset.i === '0') send(fixed, { silentUser: true, noFuzzy: true }); else send(text, { silentUser: true, noFuzzy: true }); };
      return; } }
    // 技能触发语
    let sk = null; try { sk = JK.services.skills && JK.services.skills.match ? await JK.services.skills.match(text) : null; } catch (e) {}
    if (current !== conv()) return;
    if (sk && sk.skill && (!b || sk.score >= b.score)) return runIntent({ app: 'skills', action: 'run', title: '运行技能：' + sk.skill.name, plan: ['打开技能中心', '准备输入', '运行技能', '整理结果'] }, { ...u.slots, skillId: sk.skill.id }, text);
    if (b && b.score >= 2.6) return runIntent(b.intent, b.slots, text);
    if (b && b.score >= 1.5 && Op.demo) return runIntent(b.intent, b.slots, text);
    if (b && b.score >= 1.5 && !opt.noConfirm) {
      const alts = [b, ...u.alts.filter((x) => x.score >= 1.5)].slice(0, 2);
      const m = postAI({ text: `我理解为「**${alts[0].intent.title || alts[0].intent.plan[0]}**」，要这样做吗？`, next: [...alts.map((a) => ({ label: a.intent.title || a.intent.plan[0], _run: a })), { label: '都不是，直接回答', _answer: true }] });
      const node = $$('#chatcol .msgs-in > .msg').pop(); const n = node.querySelector('.next-acts');
      if (n) n.onclick = (e) => { const bb = e.target.closest('[data-i]'); if (!bb) return; const a = m.next[+bb.dataset.i]; n.remove(); if (a._run) runIntent(a._run.intent, a._run.slots, text); else answer(text); };
      return;
    }
    return answer(text);
  }
  async function runIntent(intent, slots, text, file) {
    const app = intent.app;
    if (intent.needsAdmin && !isAdmin()) return postAI({ text: '这件事需要**管理员**来做。你可以在头像菜单里切换到管理员视角（演示）。' });
    if (app && !intent.platform && JK.registry[app] && !can(app, 'view')) return postAI({ text: `你的角色（${roleName()}）没有「${mf(app).name}」的使用权限。需要的话请管理员在“角色与授权”里开通。` });
    if (app && !intent.platform && !JK.registry[app]) return postAI({ text: `「${app}」应用还没有启用。` });
    const current = conv();
    const messageCount = current?.msgs.length || 0;
    const previous = current?.panel;
    await Op.start({ intent, slots, text, file, appId: intent.platform ? 'shell' : app });
    // 跨应用动作已经由 openApp 保存了目标页。成功完成的原地动作补记应用内深链。
    if (!app || intent.platform || !current || current !== conv() || S.active !== app || current.panel !== previous) return;
    const plan = current.msgs.slice(messageCount).find((m) => m.role === 'plan' && m.appId === app);
    if (plan?.state !== 'done') return;
    const saved = previous?.app === app ? previous : null;
    const { action } = intent;
    const entId = slots.ent?.id || saved?.params?.entId;
    if (app === 'policy') {
      if (entId && ['match', 'notice'].includes(action)) return rememberPanel(app, action, { entId });
      if (action === 'detail' && slots.policy?.id) return rememberPanel(app, 'detail', { itemId: slots.policy.id });
      if (action === 'items') return rememberPanel(app, 'items');
    }
    if (app === 'enterprise') {
      if (entId && ['find', 'visit', 'intake'].includes(action)) return rememberPanel(app, 'profile', { entId });
      if (action === 'issues') return rememberPanel(app, 'board');
      if (['filter', 'export'].includes(action)) return rememberPanel(app, 'list');
    }
    rememberPanel(app, intent.route || saved?.route, intent.params || saved?.params);
  }
  function citesOf(r) { return ((r && r.citations) || []).map((c, i) => ({ n: c.n || i + 1, id: c.id || c.fileId, title: c.title || c.name, snippet: c.snippet, source: c.source || {} })); }
  async function answer(text) {
    const thinking = postAI({ text: '…' }); const node = $$('#chatcol .msgs-in > .msg').pop();
    const finish = (o) => { Object.assign(thinking, o); const n2 = renderMsg(thinking); node.replaceWith(n2); saveConvs(); scrollEnd(); };
    const kbLike = /[？?]|什么|怎么|如何|哪些|多少|是否|能不能|可以|条件|标准|规定|政策|办法|补贴|申报|流程|要求/.test(text);
    try {
      if (kbLike && (JK.services.kb || JK.registry.kb)) {
        const r = await (JK.services.kb && JK.services.kb.ask ? JK.services.kb.ask(text, {}) : API.kb.ask({ q: text }));
        if (r && (r.confidence === 'none' || (r.answer && ((r.citations || []).length || JK.services.kb)))) { if (!r.answer) r.answer = '知识库里没有找到能回答这个问题的原文，我没有编答案。可以导入相关资料后再问。'; const m = S.models.find((x) => x.id === S.model); const none = r.confidence === 'none' || !(r.citations || []).length;
          const next = (r.suggestions || []).map((x) => ({ label: x.label, say: x.say }));
          if (!none && JK.registry.kb) next.push({ label: '在知识库里看全部结果', open: 'kb', route: 'search', params: { q: text } });
          return finish({ q: text, text: r.summary ? r.answer.split('\n\n').slice(0, 2).join('\n\n') : r.answer.split('\n\n**其他相关**')[0], cites: citesOf(r), model: (m && m.name) || '自动选择', routeNote: none ? '知识库未命中' : '知识库检索', next: next.slice(0, 3) }); }
      }
      const c = ensureConv(text); const cid = await serverConv(c);
      const r = await API.chat.send(cid, { text, model: S.model });
      const rep = r.reply || {};
      if ((!JK.registry[rep.intent] || /^收到。关于/.test(rep.content || '')) && (!rep.citations || !rep.citations.length) && (text.length < 14 || /^收到。关于/.test(rep.content || ''))) return finish({ text: '我没太听懂，你是想：', q: text, next: fallbackNext() });
      finish({ q: text, text: (rep.content || '好的。').replace(/（演示环境[^）]*）/g, '').trim(), cites: (rep.citations || []).map((x, i) => ({ n: i + 1, id: x.fileId, title: x.name, snippet: x.snippet })), model: rep.model, routeNote: rep.routeNote, next: suggestFor(rep.intent) });
    } catch (e) { finish({ text: '抱歉，这个问题我暂时答不上来：' + (e.message || '出错了') }); }
  }
  async function serverConv(c) { if (c.sid) return c.sid; try { const r = await API.chat.create({ title: c.title }); c.sid = r.item.id; } catch (e) { c.sid = 'C-301'; } saveConvs(); return c.sid; }
  function fallbackNext() {
    const list = [];
    Object.values(JK.registry).forEach((d) => { const st = (d.manifest.starters || [])[0]; if (st && can(d.manifest.id, 'view') && list.length < 4) list.push({ label: st, say: st }); });
    return list;
  }
  function suggestFor(intent) { const d = JK.registry[intent]; return d ? (d.manifest.starters || []).slice(0, 2).map((t) => ({ label: t, say: t })) : []; }

  /* 文件投递 */
  async function handleFile(file, text) {
    push({ role: 'user', text: text || '', file });
    const ext = String(file.ext || (file.name || '').split('.').pop() || '').toLowerCase();
    if (/^(exe|msi|bat|cmd|sh|dll|apk|dmg|iso|zip|rar|7z|tar|gz)$/.test(ext)) { postAI({ text: `「${file.name}」是${/^(zip|rar|7z|tar|gz)$/.test(ext) ? '压缩包' : '程序文件'}，我暂时处理不了。${/^(zip|rar|7z|tar|gz)$/.test(ext) ? '解压后把里面的文件拖进来就行。' : ''}\n可以发 PDF、Word、Excel、TXT、图片或录音。` }); return; }
    const c = Op.classify(file);
    if (!c.length) {
      const opts = [];
      if (JK.registry.kb) opts.push({ label: '存入知识库', run: { app: 'kb', accept: { kind: '其他', plan: ['识别文件', '打开知识库', '解析入库'] } } });
      Object.values(JK.registry).forEach((d) => { if ((d.manifest.accepts || []).length && d.manifest.id !== 'kb') opts.push({ label: '交给' + d.manifest.short, run: { app: d.manifest.id, accept: d.manifest.accepts[0] } }); });
      const m = postAI({ text: `我没认出「${file.name}」是什么。想怎么处理？`, next: opts.slice(0, 3).map((o) => ({ label: o.label, _r: o.run })) });
      const node = $$('#chatcol .msgs-in > .msg').pop(); const n = node.querySelector('.next-acts'); if (n) n.onclick = (e) => { const b = e.target.closest('[data-i]'); if (!b) return; n.remove(); intake(m.next[+b.dataset.i]._r, file, text); };
      return;
    }
    return intake(c[0], file, text);
  }
  async function intake(cand, file, text) {
    const a = cand.accept || {}; const m = mf(cand.app); file.kind = file.kind || a.kind;
    if (!can(cand.app, 'operate')) return postAI({ text: `这是一份${a.kind || '文件'}，需要「${m.name}」的操作权限，你的角色暂时没有。` });
    postAI({ text: `这是一份**${a.kind || '文件'}**，${a.say || `我交给「${m.name}」处理`}。` });
    const intent = { app: cand.app, action: 'intake', title: `处理：${file.name.length > 18 ? file.name.slice(0, 18) + '…' : file.name}`, plan: a.plan || ['识别文件', `打开${m.short || m.name}`, '处理内容', '等你确认'] };
    return runIntent(intent, Op.understand(file.name + ' ' + (file.text || '').slice(0, 200)).slots, text || '', file);
  }

  /* ---------------- ⌘K ---------------- */
  function cmdk() {
    if ($('.cmdk')) return;
    const x = JK.modal({ title: '', body: `<div class="cmdk-in">${icon('search')}<input placeholder="搜应用、功能、对话，或直接说要办的事…" data-op="cmdk.input"><span class="kbd">Esc</span></div><div class="cmdk-list"></div>` });
    x.el.classList.add('cmdk'); const inp = x.el.querySelector('input'); const list = x.el.querySelector('.cmdk-list'); let items = [], sel = 0;
    const draw = async () => {
      const q = inp.value.trim(); items = [];
      if (q) items.push({ g: '交给 AI', label: `“${q}”`, d: 'AI 理解后替你操作', icon: 'sparkles', fn: () => send(q) });
      [...appsVisible('work'), ...appsVisible('platform')].forEach((a) => { const m = mf(a.id); if (!q || (m.name + m.summary).includes(q)) items.push({ g: '打开应用', label: m.name, d: m.summary, app: a.id, fn: () => openApp(a.id) }); });
      [['inbox', '收件箱', '待我审签 / 确认'], ...(isAdmin() ? [['admin', '管理后台', '账号、权限、模型、审计']] : [])].forEach(([id, n, d]) => { if (!q || n.includes(q)) items.push({ g: '平台', label: n, d, app: id, fn: () => openBuiltin(id) }); });
      Op.allIntents().filter((it) => !it.platform && JK.registry[it.app] && can(it.app, 'view')).forEach((it) => (it.examples || []).slice(0, 1).forEach((ex) => { if (!q || ex.includes(q) || (it.keywords || []).some((k) => q.includes(k))) items.push({ g: '试试这样说', label: ex, app: it.app, fn: () => send(ex) }); }));
      S.convs.filter((c) => q && c.title.includes(q)).slice(0, 4).forEach((c) => items.push({ g: '最近对话', label: c.title, icon: 'history', fn: () => openConv(c.id) }));
      items = items.slice(0, 14); sel = 0; render();
    };
    const render = () => { let g = ''; list.innerHTML = items.map((it, i) => `${it.g !== g ? `<div class="mh">${esc((g = it.g))}</div>` : ''}<div class="mi ${i === sel ? 'on' : ''}" data-i="${i}">${it.app ? appIcon(it.app, 'sm') : icon(it.icon || 'arrow-right')}<span class="ck-t">${esc(it.label)}</span>${it.d ? `<span class="ck-d">${esc(it.d)}</span>` : ''}${i === sel ? '<span class="ck-k">↵</span>' : ''}</div>`).join('') || JK.empty({ icon: 'search', title: '没有匹配的结果' }); };
    list.onclick = (e) => { const it = e.target.closest('[data-i]'); if (!it) return; x.close(); items[+it.dataset.i].fn(); };
    inp.oninput = draw; inp.onkeydown = (e) => { if (e.key === 'ArrowDown') { sel = Math.min(items.length - 1, sel + 1); render(); e.preventDefault(); } if (e.key === 'ArrowUp') { sel = Math.max(0, sel - 1); render(); e.preventDefault(); } if (e.key === 'Enter' && items[sel]) { x.close(); items[sel].fn(); } };
    draw(); setTimeout(() => inp.focus(), 20);
  }

  /* ---------------- 收件箱 ---------------- */
  async function refreshInbox() {
    try { const r = await API.reviews.list(); S.inbox = (r.items || []).filter((x) => { const a = x.app === 'market' ? 'skills' : x.app; return x.status === 'pending' && (x.approver ? can(a, 'approve') : (can(a, 'operate') && !(x.type === 'proposal' && S.me && S.me.role === 'leader'))); }); } catch (e) { S.inbox = []; }
    try { S.todos = (await API.todos.list()).items || []; } catch (e) { S.todos = []; }
    renderSide(); if (S.mounted.inbox) renderInbox(S.mounted.inbox.el);
  }
  JK.bus.on('api:write', (x) => { if (S.me && !/\/auth\//.test(x.path)) { clearTimeout(refreshInbox._t); refreshInbox._t = setTimeout(refreshInbox, 150); } });
  const TYPE_LABEL = { review: '待审签', proposal: '待确认', todo: '待确认', skill: '待上架审核' };
  function renderInbox(el) {
    const tab = el.dataset.tab || 'mine';
    const list = S.inbox; const todos = S.todos.filter((t) => t.status !== '已完成');
    el.innerHTML = `<div class="app-head">${appIcon('inbox', 'lg')}<div><h2>收件箱</h2><div class="sub">等你处理的事都在这里</div></div></div>
      <div class="tabs" style="margin-bottom:8px"><button class="tab ${tab === 'mine' ? 'on' : ''}" data-t="mine">待我处理 ${list.length ? `<span class="count muted">${list.length}</span>` : ''}</button><button class="tab ${tab === 'todo' ? 'on' : ''}" data-t="todo">我的待办 ${todos.length ? `<span class="count muted">${todos.length}</span>` : ''}</button></div>
      <div class="list">${tab === 'mine' ? (list.map((r) => { const app = r.app === 'market' ? 'skills' : r.app; return `<div class="inb-i">${appIcon(app, 'sm')}<div class="grow"><div class="row"><span class="ttl">${esc(r.title)}</span>${tag(TYPE_LABEL[r.type] || '待处理')}</div><div class="meta">${esc(r.meta || '')}</div></div><div class="row">${r.approver && can(app, 'approve') ? `<button class="btn sm" data-dec="reject" data-id="${r.id}" data-op="inbox.reject.${r.id}">退回</button><button class="btn sm soft" data-dec="approve" data-id="${r.id}" data-op="inbox.approve.${r.id}">通过</button>` : ''}<button class="btn sm ghost" data-open="${app}" data-ref="${esc(r.ref || '')}" data-type="${r.type}">查看 ${icon('chevron-right')}</button></div></div>`; }).join('') || JK.empty({ icon: 'check', title: '全部处理完了', desc: '新的审签、确认会出现在这里' })) : (todos.map((t) => `<div class="inb-i"><input type="checkbox" class="check" data-todo="${t.id}" style="margin-top:4px;accent-color:var(--accent)"><div class="grow"><div class="ttl">${esc(t.title || t.text)}</div><div class="meta">${esc([t.from, t.due && '截止 ' + t.due].filter(Boolean).join(' · '))}</div></div>${t.due ? tag(t.status || '待办') : ''}</div>`).join('') || JK.empty({ icon: 'check', title: '没有待办', desc: '会议纪要派发给你的待办会出现在这里' }))}</div>`;
    el.querySelectorAll('[data-t]').forEach((b) => (b.onclick = () => { el.dataset.tab = b.dataset.t; renderInbox(el); }));
    el.querySelectorAll('[data-dec]').forEach((b) => (b.onclick = async () => { const dec = b.dataset.dec; let comment = ''; if (dec === 'reject') { comment = prompt('退回原因（会发给提交人）', '请补充依据后再提交') || ''; if (!comment) return; } try { await API.reviews.decide(b.dataset.id, { decision: dec, comment }); toast(dec === 'approve' ? '已通过' : '已退回'); refreshInbox(); } catch (e) { toast(e.message, { type: 'err' }); } }));
    el.querySelectorAll('[data-open]').forEach((b) => (b.onclick = () => { const a = b.dataset.open; const ref = b.dataset.ref; const R = !ref ? null : a === 'document' ? ['detail', { id: ref }] : a === 'enterprise' ? ['profile', { entId: ref }] : a === 'meeting' ? ['detail', { id: ref, meetingId: ref }] : a === 'skills' ? ['detail', { skillId: ref, review: true }] : null; Promise.resolve(openApp(a)).then(() => { const sl = S.mounted[a]; if (R && sl && sl.ctl && sl.ctl.go) { sl.ctx.params = R[1]; try { sl.ctl.go(R[0], R[1]); } catch (e) { console.error(e); } } }); }));
    el.querySelectorAll('[data-todo]').forEach((c) => (c.onchange = async () => { try { await API.todos.patch(c.dataset.todo, { status: '已完成' }); toast('已完成'); refreshInbox(); } catch (e) { toast(e.message, { type: 'err' }); } }));
  }

  /* ---------------- 个人设置 ---------------- */
  function openSettings() {
    JK.modal({ title: '个人设置', width: 480, body: `<div class="col gap4">
      <div class="row gap3"><span class="avatar lg h-${roleHue()}" style="width:44px;height:44px;font-size:16px">${esc(S.me.name[0])}</span><div><div style="font-weight:500">${esc(S.me.name)} ${tag(roleName(), 'role')}</div><div class="t-3 t-sm">${esc(S.me.dept || '')} · ${esc(S.me.title || '')} · ${esc(S.me.username)}</div></div></div>
      <div class="field"><label>外观</label><div class="seg" id="st-theme"><button data-v="dark" class="${theme() === 'dark' ? 'on' : ''}">深色</button><button data-v="light" class="${theme() === 'light' ? 'on' : ''}">浅色</button></div></div>
      <div class="divider" style="margin:0"></div>
      <div class="field"><label>修改密码</label><input class="input" id="pw-old" type="password" placeholder="原密码"><input class="input" id="pw-new" type="password" placeholder="新密码（至少 6 位）"></div></div>`,
      okText: '保存密码', ok: async (d) => { const o = d.querySelector('#pw-old').value, n = d.querySelector('#pw-new').value; if (!o && !n) return true; try { await API.me.password({ old: o, new: n }); toast('密码已修改'); } catch (e) { toast(e.message, { type: 'err' }); return false; } },
      onMount: (d) => d.querySelectorAll('#st-theme button').forEach((b) => (b.onclick = () => { setTheme(b.dataset.v); d.querySelectorAll('#st-theme button').forEach((x) => x.classList.toggle('on', x === b)); })) });
  }

  /* ---------------- 帮助 ---------------- */
  function helpText() {
    const apps = [...appsVisible('work'), ...appsVisible('platform')].map((a) => `· **${mf(a.id).name}**：${mf(a.id).summary || ''}`).join('\n');
    return `我可以直接在右侧替你操作这些应用：\n${apps}\n也可以把文件拖进对话框，我会认出是什么并交给对应应用。`;
  }
  const helpNext = () => (CFG.homeSuggestions || []).slice(0, 3).map((s) => ({ label: s.text, say: s.text }));

  /* ---------------- 对外（操作员钩子、管理后台、演示） ---------------- */
  const shellApi = { S, can, citesOf, isAdmin, openApp, openBuiltin, send, handleFile, setTheme, theme, switchUser, toast, refreshInbox, reset, newChat, setLayout, roleName, modelsReload: async () => { const m = await API.models.list(); S.models = m.items || []; }, rerenderSide: renderSide, afterLogin };
  Object.assign(Op.hooks, {
    postPlan, postAI, async openApp(id, route, params) {
      const run = Op.running;
      run?.check();
      await openApp(id, route, params);
      run?.check();
    }, appCtl: (id) => S.mounted[id] && S.mounted[id].ctl, appEl: (id) => S.mounted[id] && S.mounted[id].el,
    openBuiltin, inboxCount: () => S.inbox.length, setModel, setTheme, switchUser: async (u) => { await switchUser(u); }, helpText, helpNext,
    startDemo: () => window.JKDemo && JKDemo.start(), reset,
  });
  window.JKShell = shellApi;
  document.addEventListener('DOMContentLoaded', boot);
})();

/* v4 外壳核心：图标、UI 工具、应用注册、服务注册。应用通过 window.JK 与 ctx 使用。 */
(function () {
  const P = {
    chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12z"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z"/>',
    plus: '<path d="M12 5v14M5 12h14"/>', send: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    paperclip: '<path d="m21 11-8.6 8.6a5 5 0 0 1-7-7l8.5-8.6a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.3-2.4l7.9-7.9"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    upload: '<path d="M12 15V4M7 9l5-5 5 5M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>',
    download: '<path d="M12 4v11M7 10l5 5 5-5M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>',
    play: '<path d="M7 4.5v15l12-7.5z"/>', pause: '<path d="M8 5v14M16 5v14"/>', stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>', x: '<path d="M6 6l12 12M18 6 6 18"/>',
    'chevron-right': '<path d="m9 6 6 6-6 6"/>', 'chevron-down': '<path d="m6 9 6 6 6-6"/>', 'chevron-left': '<path d="m15 6-6 6 6 6"/>',
    more: '<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6.5 6.5 0 0 1 3.5 6"/>',
    shield: '<path d="M12 3 4 6v6c0 5 3.4 8.3 8 9 4.6-.7 8-4 8-9V6z"/>', key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3M15 8l2 2"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    'eye-off': '<path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3 3.9M6.6 6.6C3.9 8.4 2 12 2 12s3.5 7 10 7c1.6 0 3-.4 4.3-1M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    sparkles: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    policy: '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 12l2 2 4-4M9 17h6"/>',
    building: '<path d="M4 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16M16 9h3a1 1 0 0 1 1 1v11M3 21h18M8 7h4M8 11h4M8 15h4"/>',
    meeting: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4M7 9h6M7 12h10"/>',
    doc: '<path d="M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M14 3v5h5M8.5 13h7M8.5 17h5"/>',
    book: '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5M8 7h7M8 11h5"/>',
    skill: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
    computer: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/><path d="m10 8 3 2-3 2"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    flag: '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>', alert: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17v.5"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
    edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>', trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.6-4.5L4 8M4 4v4h4M4 13a8 8 0 0 0 14.6 4.5L20 16M20 20v-4h-4"/>',
    filter: '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>', sort: '<path d="M7 4v16M3 16l4 4 4-4M17 20V4M13 8l4-4 4 4"/>',
    table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 4v16"/>', list: '<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/>',
    'arrow-right': '<path d="M5 12h14M13 6l6 6-6 6"/>', external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2"/>', logout: '<path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 17l5-5-5-5M15 12H3"/>',
    sidebar: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>', maximize: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>', minimize: '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
    cube: '<path d="M12 3 4 7.5v9L12 21l8-4.5v-9z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/>', hand: '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12M11 11V4.5a1.5 1.5 0 0 1 3 0V12M14 11.5V6a1.5 1.5 0 0 1 3 0v8a7 7 0 0 1-7 7h-.5a6 6 0 0 1-5-2.7L2 14.5a1.6 1.6 0 0 1 2.6-1.8L8 16"/>',
    cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M10 10h4v4h-4zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  };
  const icon = (n, size) => { if (n && n.trim && n.trim().startsWith('<svg')) return n; const p = P[n] || P.cube; return `<span class="ico"${size ? ` style="width:${size}px;height:${size}px"` : ''}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${p}</svg></span>`; };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\[(\d+)\]/g, '<span class="cite" data-cite="$1">$1</span>').replace(/^[·•-] (.*)$/gm, '<div class="li-b">$1</div>').replace(/\n/g, '<br>');
  const $ = (s, r) => (r || document).querySelector(s); const $$ = (s, r) => [...(r || document).querySelectorAll(s)];
  const h = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  /* 标签色 */
  const HUES = ['blue', 'indigo', 'violet', 'pink', 'orange', 'amber', 'green', 'teal', 'cyan'];
  function hue(label, group) {
    const T = window.JK_TAGS || {}; label = String(label == null ? '' : label).trim();
    if (group && T[group] && T[group][label]) return T[group][label];
    if (T.status && T.status[label]) return T.status[label];
    for (const k in T) if (T[k] && T[k][label]) return T[k][label];
    let x = 0; for (const c of label) x = (x * 31 + c.charCodeAt(0)) >>> 0; return HUES[x % HUES.length];
  }
  const tag = (label, group, opt) => `<span class="tag ${(opt && opt.cls) || ''}" data-hue="${opt && opt.hue || hue(label, group)}">${esc(label)}</span>`;
  const appHue = (id) => ((window.JK_APP_HUES || {})[id]) || 'gray';

  /* 浮层 */
  function toast(msg, o = {}) {
    let box = $('.toasts'); if (!box) { box = h('<div class="toasts"></div>'); document.body.appendChild(box); }
    const t = h(`<div class="toast ${o.type || ''}"><span class="sdot"></span><span>${esc(msg)}</span>${o.action ? `<button class="btn sm ghost">${esc(o.action.label)}</button>` : ''}</div>`);
    if (o.action) t.querySelector('button').onclick = () => { o.action.fn(); t.remove(); };
    placeToasts(box); box.appendChild(t); if (!box._tick) box._tick = setInterval(() => { if (!box.children.length) { clearInterval(box._tick); box._tick = null; return; } placeToasts(box); }, 150); setTimeout(() => t.remove(), o.ms || 2800); return t;
  }
  /* 提示条放在对话栏顶部（标题栏下方，压的是最早的消息）：不挡右侧应用面板、不挡输入框和待确认卡片；没有对话栏时放视口底部居中 */
  function placeToasts(box) {
    const col = document.getElementById('chatcol'); const r = col && col.offsetParent ? col.getBoundingClientRect() : null;
    box.style.top = box.style.bottom = '';
    if (r && r.width > 200) { const hd = col.querySelector('.bar-h, .chat-h, header'); const top = hd && hd.offsetParent ? hd.getBoundingClientRect().bottom : r.top; box.style.left = (r.left + r.width / 2) + 'px'; box.style.top = (top + 10) + 'px'; box.style.bottom = 'auto'; }
    else { box.style.left = '50%'; box.style.top = 'auto'; box.style.bottom = '24px'; }
  }
  function overlay(kind, { title, body, ok, okText, cancelText, onMount, onClose, width, danger, foot }) {
    const m = h('<div class="mask-bg"></div>');
    const d = h(`<div class="${kind}" ${width ? `style="width:min(${width}px,94vw)"` : ''} role="dialog"><div class="ov-h"><b>${esc(title || '')}</b><span class="sp"></span><button class="btn icon sm ghost" data-x aria-label="关闭">${icon('x')}</button></div><div class="ov-b">${body || ''}</div>${ok || foot ? `<div class="ov-f">${foot || ''}${ok ? `<button class="btn" data-cancel>${esc(cancelText || '取消')}</button><button class="btn ${danger ? 'danger' : 'primary'}" data-ok>${esc(okText || '确定')}</button>` : ''}</div>` : ''}</div>`);
    document.body.append(m, d);
    const close = () => { m.remove(); d.remove(); document.removeEventListener('keydown', onKey); onClose?.(); };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    m.onclick = close; d.querySelector('[data-x]').onclick = close;
    const c = d.querySelector('[data-cancel]'); if (c) c.onclick = close;
    const o = d.querySelector('[data-ok]'); if (o) o.onclick = async () => { const r = ok && (await ok(d)); if (r !== false) close(); };
    onMount && onMount(d, close);
    return { el: d, close };
  }
  const modal = (o) => overlay('modal', o); const drawer = (o) => overlay('drawer', o);
  const confirm = (text, o = {}) => new Promise((res) => { let done = false; const x = modal({ title: o.title || '请确认', body: `<div class="t-2">${esc(text)}</div>`, okText: o.okText || '确定', danger: o.danger, ok: () => { done = true; res(true); } }); const obs = new MutationObserver(() => { if (!x.el.isConnected) { obs.disconnect(); if (!done) res(false); } }); obs.observe(document.body, { childList: true }); });
  function menu(anchor, items, onPick) {
    $$('.menu').forEach((x) => x.remove());
    // 项：{v, label, desc?, right?(html), icon?, lead?(html 前缀，如应用图标), on?, disabled?, html?} | {head} | {sep:true}
    const row = (it) => { if (it.head) return `<div class="mh">${esc(it.head)}</div>`; if (it.sep) return '<div class="msep"></div>';
      const body = it.html || `<span class="mi-b"><span class="mi-t">${esc(it.label)}</span>${it.desc ? `<span class="mi-d">${esc(it.desc)}</span>` : ''}</span>`;
      return `<div class="mi ${it.on ? 'on' : ''} ${it.disabled ? 'dis' : ''}" data-v="${esc(it.v)}">${it.lead || (it.icon ? icon(it.icon) : '')}${body}${it.right || it.on ? `<span class="mi-r">${it.right || ''}${it.on ? `<span class="mi-ck">${icon('check')}</span>` : ''}</span>` : ''}</div>`; };
    const m = h(`<div class="menu scroll">${items.map(row).join('')}</div>`);
    document.body.appendChild(m);
    const r = anchor.getBoundingClientRect();
    let left = Math.min(r.left, innerWidth - m.offsetWidth - 8), top = r.bottom + 6;
    if (top + m.offsetHeight > innerHeight - 8) top = Math.max(8, r.top - m.offsetHeight - 6);
    m.style.left = Math.max(8, left) + 'px'; m.style.top = top + 'px';
    m.addEventListener('click', (e) => { const it = e.target.closest('[data-v]'); if (!it) return; m.remove(); onPick(it.dataset.v); });
    setTimeout(() => document.addEventListener('mousedown', function off(e) { if (!m.contains(e.target)) { m.remove(); document.removeEventListener('mousedown', off); } }), 0);
    return m;
  }
  const empty = ({ icon: ic = 'inbox', title = '这里还没有内容', desc = '', action } = {}) => `<div class="empty"><div class="e-ico">${icon(ic, 20)}</div><div class="e-t">${esc(title)}</div>${desc ? `<div class="e-d">${esc(desc)}</div>` : ''}${action ? `<button class="btn primary" data-empty-action>${esc(action)}</button>` : ''}</div>`;
  const steps = (list, cur) => `<div class="wiz-steps">${list.map((s, i) => `${i ? `<span class="wiz-line ${i <= cur ? 'done' : ''}"></span>` : ''}<span class="wiz-step ${i === cur ? 'on' : i < cur ? 'done' : ''}" data-step="${i}"><span class="n">${i < cur ? '✓' : i + 1}</span>${esc(s)}</span>`).join('')}</div>`;
  function download(name, content, mime) { const b = content instanceof Blob ? content : new Blob([content], { type: mime || 'text/plain;charset=utf-8' }); const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = name; document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500); }
  const fmtMoney = (n) => n >= 10000 ? (n / 10000).toFixed(n % 10000 ? 1 : 0).replace(/\.0$/, '') + ' 万元' : (n || 0) + ' 元';
  const fmtDate = (s) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || ''); return m ? `${+m[1]}年${+m[2]}月${+m[3]}日` : (s || ''); };
  const appIcon = (id, size) => { const a = (window.JK && JK.registry[id] && JK.registry[id].manifest) || (BUILTIN[id] || {}); return `<span class="app-ico ${size || ''} h-${a.hue || appHue(id)}">${icon(a.icon || id)}</span>`; };
  const BUILTIN = { chat: { icon: 'chat', name: '总控对话' }, inbox: { icon: 'inbox', name: '收件箱' }, admin: { icon: 'shield', name: '管理后台', hue: 'gray' }, settings: { icon: 'user', name: '个人设置', hue: 'gray' } };

  /* 事件总线 */
  const ev = {}; const bus = { on: (k, f) => (ev[k] = ev[k] || []).push(f), emit: (k, d) => (ev[k] || []).forEach((f) => { try { f(d); } catch (e) { console.warn(e); } }) };

  /* 注册 */
  const registry = {}; const services = {};
  function registerApp(def) {
    if (!def || !def.manifest || !def.manifest.id) { console.warn('registerApp: 缺少 manifest.id'); return; }
    const m = def.manifest; m.hue = m.hue || appHue(m.id); m.intents = m.intents || []; m.accepts = m.accepts || []; m.demo = m.demo || [];
    registry[m.id] = def; bus.emit('app:registered', m.id);
  }
  const provide = (name, svc) => { services[name] = svc; bus.emit('service:' + name, svc); };

  window.JK = { icon, esc, md, $, $$, h, sleep, hue, tag, appHue, appIcon, toast, modal, drawer, confirm, menu, empty, steps, download, fmtMoney, fmtDate, bus, registry, services, registerApp, provide, BUILTIN, ICONS: Object.keys(P) };
})();

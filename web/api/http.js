/* =====================================================================
 * 接口适配层 · 传输（唯一出口）。界面代码只通过 JK.http / api/*.js 访问后端。
 * JK_CONFIG.api.modules 可覆盖单个模块，其余请求沿用 api.mode。
 * mock 调 window.JKAPI，http 调 fetch 并携带会话 Cookie。
 * ===================================================================== */
(function () {
  const cfg = () => (window.JK_CONFIG && window.JK_CONFIG.api) || { mode: 'mock' };
  const modules = new Set(['platform', 'kb', 'policy', 'enterprise', 'meeting', 'document', 'skills', 'computer']);
  const warned = new Set();

  function overrides(config) {
    const entries = config.modules || {};
    for (const id of Object.keys(entries)) {
      if (!modules.has(id) && !warned.has(id)) {
        warned.add(id);
        console.warn('已忽略未知的 API 模块：' + id);
      }
    }
    return entries;
  }

  function modeFor(config, id) {
    const entries = overrides(config);
    const mode = modules.has(id) && Object.hasOwn(entries, id) ? entries[id] : undefined;
    return mode === 'http' || mode === 'mock' ? mode : config.mode;
  }

  function moduleFor(path) {
    const [, api, scope, resource] = path.split('?')[0].split('/');
    if (api !== 'api') return 'platform';
    if (scope === 'apps') return resource;
    if (scope !== 'v1') return 'platform';
    if (resource === 'kb' || resource === 'skills') return resource;
    if (resource === 'jobs') return 'meeting';
    return 'platform';
  }

  // 入口 HTML 在全局 HTTP 模式下跳过应用 mock。只为显式保留 mock 的应用补载脚本。
  const initial = cfg();
  overrides(initial);
  if (initial.mode === 'http' && typeof document !== 'undefined' &&
      document.readyState === 'loading' && document.currentScript) {
    const root = new URL('../mock/', document.currentScript.src);
    for (const app of window.JK_APP_LIST || []) {
      if (app.enabled !== false && app.mock && modeFor(initial, app.id) === 'mock') {
        document.write('<script src="' + new URL(app.id + '.js', root).href + '"><\/script>');
      }
    }
  }

  // 混合模式：平台走 HTTP、部分应用留在 mock 时，按 HTTP 会话的角色建立本地演示会话。
  // 真实账号口令只发往 HTTP 后端，本地只记录映射到的演示账号。
  const sessionPaths = /^\/api\/v1\/(?:auth\/(?:login|logout|session)|me)$/;
  function syncMockSession(path, out) {
    const X = window.JKAPI && window.JKAPI.ext;
    if (!X || !sessionPaths.test(path)) return;
    const S = X.state();
    const user = path.endsWith('/logout') ? null : out && out.user;
    if (!user) {
      if (S.session && S.session.bridged) { S.session = null; X.save(); }
      return;
    }
    const role = typeof user.role === 'string' ? user.role : (out.role && out.role.id) || (user.role && user.role.id);
    const active = (S.users || []).filter((u) => u.status === 'active');
    const local = active.find((u) => u.username === user.username && u.role === role) || active.find((u) => u.role === role);
    if (!local) {
      if (S.session && S.session.bridged) { S.session = null; X.save(); }
      return;
    }
    if (S.session && S.session.userId === local.id) return;
    S.session = { userId: local.id, at: X.now(), bridged: true }; S.me = local.id; X.save();
  }

  async function request(method, path, body) {
    const out = await raw(method, path, body);
    if (method !== 'GET' && window.JK && window.JK.bus) setTimeout(() => window.JK.bus.emit('api:write', { method, path }), 0);
    return out;
  }
  async function raw(method, path, body) {
    const c = cfg();
    if (modeFor(c, moduleFor(path)) === 'http') {
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), c.timeoutMs || 20000);
      try {
        const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
        const r = await fetch(c.baseUrl.replace(/\/$/, '') + path, { method, credentials: 'include', signal: ctl.signal,
          headers: isForm ? {} : { 'Content-Type': 'application/json' }, body: body == null || method === 'GET' ? undefined : isForm ? body : JSON.stringify(body) });
        const j = await r.json().catch(() => ({}));
        if (r.status === 401 && moduleFor(path) === 'platform') syncMockSession('/api/v1/auth/logout', null);
        if (!r.ok) {
          const error = j?.error || j || {};
          throw { status: r.status, code: error.code || 'HTTP_' + r.status,
            message: error.message || r.statusText, details: error.details };
        }
        if (moduleFor(path) === 'platform') syncMockSession(path.split('?')[0], j);
        return j;
      } catch (e) { if (e && e.name === 'AbortError') throw { status: 0, code: 'TIMEOUT', message: '服务器响应超时' }; throw e.status !== undefined ? e : { status: 0, code: 'NETWORK', message: '网络不可用' }; }
      finally { clearTimeout(t); }
    }
    if (!window.JKAPI) throw { status: 0, code: 'NO_MOCK', message: '模拟后端未加载' };
    if (method === 'POST' && path === '/api/v1/demo/reset') {
      window.JKAPI.reset();
      return { ok: true };
    }
    return window.JKAPI.request(method, path, body);
  }
  const qs = (o) => { const p = Object.entries(o || {}).filter(([, v]) => v !== undefined && v !== null && v !== ''); return p.length ? '?' + p.map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&') : ''; };
  window.JKHttp = {
    request, qs,
    get: (p, q) => request('GET', p + qs(q)), post: (p, b) => request('POST', p, b), put: (p, b) => request('PUT', p, b),
    patch: (p, b) => request('PATCH', p, b), del: (p) => request('DELETE', p),
    mode: () => modeFor(cfg(), 'platform'),
  };
})();

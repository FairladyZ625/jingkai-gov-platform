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
  const sessionPaths = /^(?:POST \/api\/v1\/auth\/login|GET \/api\/v1\/(?:auth\/session|me))$/;
  let sessionRevision = 0;
  let authPending = false;
  function clearMockSession() {
    const X = window.JKAPI && window.JKAPI.ext;
    if (X?.state().session) { X.state().session = null; X.save(); }
  }
  if (modeFor(initial, 'platform') === 'http') clearMockSession();

  function syncMockSession(config, out) {
    const X = window.JKAPI && window.JKAPI.ext;
    if (!X || ![...modules].some(id => id !== 'platform' && modeFor(config, id) === 'mock')) return;
    const S = X.state();
    const user = out?.user;
    if (!user) return clearMockSession();
    const role = typeof user.role === 'string' ? user.role : (out.role && out.role.id) || (user.role && user.role.id);
    const active = (S.users || []).filter((u) => u.status === 'active');
    const local = active.find((u) => u.username === user.username && u.role === role) || active.find((u) => u.role === role);
    if (!local) return clearMockSession();
    if (S.session?.bridged && S.session.userId === local.id) return;
    S.session = { userId: local.id, at: X.now(), bridged: true }; S.me = local.id; X.save();
  }

  async function requestMock(method, path, body) {
    const mock = window.JKAPI;
    if (!mock) throw { status: 0, code: 'NO_MOCK', message: '模拟后端未加载' };
    if (method === 'POST' && path === '/api/v1/demo/reset') {
      mock.reset();
      return { ok: true };
    }
    // Web 迁移基线的旧 mock 登录只有 user，权限延用同一会话的 /me。
    if (method === 'POST' && path === '/api/v1/auth/login') {
      const login = await mock.request(method, path, body);
      if (login.role === undefined && login.grants === undefined) {
        const { role, grants } = await mock.request('GET', '/api/v1/me');
        return { ...login, role, grants };
      }
      return login;
    }
    // 旧 mock 会移除自建资料的原始记录。保留已授权删除产生的记录供原 /restore 重建索引。
    const doc = /^\/api\/v1\/kb\/docs\/([^/?]+)(\/restore)?$/.exec(path);
    const kb = doc && mock.ext?.state().kb;
    if (kb && method === 'DELETE' && !doc[2]) {
      const imported = kb.added.find(item => item.id === doc[1]);
      const result = await mock.request(method, path, body);
      if (result.ok && imported && !kb.added.includes(imported)) {
        (kb.deletedImports ||= []).push(imported);
        mock.ext.save();
      }
      return result;
    }
    if (kb && method === 'POST' && doc[2]) {
      const imported = kb.deletedImports?.find(item => item.id === doc[1]);
      const result = await mock.request(method, path, body);
      if (result.ok && imported && !kb.added.some(item => item.id === imported.id)) {
        kb.added.push(imported);
        kb.deletedImports = kb.deletedImports.filter(item => item.id !== imported.id);
        window.JKKB.reload();
        mock.ext.save();
      }
      return result;
    }
    return mock.request(method, path, body);
  }

  async function request(method, path, body) {
    const out = await raw(method, path, body);
    if (method !== 'GET' && window.JK && window.JK.bus) setTimeout(() => window.JK.bus.emit('api:write', { method, path }), 0);
    return out;
  }
  async function raw(method, path, body) {
    const c = cfg();
    const module = moduleFor(path);
    if (modeFor(c, module) === 'http') {
      const operation = method + ' ' + path.split('?')[0];
      const isLogin = operation === 'POST /api/v1/auth/login';
      const changesSession = isLogin || operation === 'POST /api/v1/auth/logout';
      if (changesSession) {
        sessionRevision++;
        authPending = true;
        clearMockSession();
      }
      const revision = sessionRevision;
      const maySyncSession = isLogin || (!authPending && sessionPaths.test(operation));
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), c.timeoutMs || 20000);
      try {
        const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
        const r = await fetch(c.baseUrl.replace(/\/$/, '') + path, { method, credentials: 'include', signal: ctl.signal,
          headers: isForm ? {} : { 'Content-Type': 'application/json' }, body: body == null || method === 'GET' ? undefined : isForm ? body : JSON.stringify(body) });
        const j = await r.json().catch(() => ({}));
        if (r.status === 401 && module === 'platform' && revision === sessionRevision) clearMockSession();
        if (!r.ok) {
          const error = j?.error || j || {};
          throw { status: r.status, code: error.code || 'HTTP_' + r.status,
            message: error.message || r.statusText, details: error.details };
        }
        if (revision === sessionRevision && maySyncSession) syncMockSession(c, j);
        return j;
      } catch (e) { if (e && e.name === 'AbortError') throw { status: 0, code: 'TIMEOUT', message: '服务器响应超时' }; throw e.status !== undefined ? e : { status: 0, code: 'NETWORK', message: '网络不可用' }; }
      finally {
        clearTimeout(t);
        if (changesSession && revision === sessionRevision) authPending = false;
      }
    }
    return requestMock(method, path, body);
  }
  const qs = (o) => { const p = Object.entries(o || {}).filter(([, v]) => v !== undefined && v !== null && v !== ''); return p.length ? '?' + p.map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&') : ''; };
  window.JKHttp = {
    request, qs,
    get: (p, q) => request('GET', p + qs(q)), post: (p, b) => request('POST', p, b), put: (p, b) => request('PUT', p, b),
    patch: (p, b) => request('PATCH', p, b), del: (p) => request('DELETE', p),
    mode: () => modeFor(cfg(), 'platform'),
  };
})();

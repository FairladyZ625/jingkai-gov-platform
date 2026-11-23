/* =====================================================================
 * 接口适配层 · 传输（唯一出口）。界面代码只通过 JK.http / api/*.js 访问后端。
 * JK_CONFIG.api.modules 可覆盖单个模块，其余请求沿用 api.mode。
 * mock 调 window.JKAPI，http 调 fetch 并携带会话 Cookie；文件请求可解码响应体。
 * 错误统一抛 { status, code, message, details }。
 * ===================================================================== */
(function () {
  const cfg = () => (window.JK_CONFIG && window.JK_CONFIG.api) || { mode: 'mock' };
  const timeoutMs = () => cfg().timeoutMs || 20000;
  const apps = new Set(['kb', 'policy', 'enterprise', 'document', 'meeting', 'computer', 'skills']);
  const modules = new Set(['platform', ...apps]);
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
    const setting = modules.has(id) && Object.hasOwn(entries, id) ? entries[id] : undefined;
    return setting === 'http' || setting === 'mock' ? setting : config.mode;
  }

  function mode(id = 'platform') {
    return modeFor(cfg(), id);
  }

  function moduleFor(path) {
    const p = path.split('?')[0];
    const app = /^\/api\/apps\/([^/]+)(?:\/|$)/.exec(p)?.[1] ||
      /^\/api\/v1\/(kb|skills)(?:\/|$)/.exec(p)?.[1];
    return apps.has(app) ? app : 'platform';
  }

  // 独立环境在全局 HTTP 模式下未走入口 HTML 内联加载器时，只为显式保留 mock 的应用补载脚本。
  const initial = cfg();
  overrides(initial);
  if (initial.mode === 'http' && typeof document !== 'undefined' &&
      document.readyState === 'loading' && document.currentScript &&
      !document.getElementById?.('root')) {
    const root = new URL('../mock/', document.currentScript.src);
    for (const app of window.JK_APP_LIST || []) {
      if (app.enabled !== false && app.mock && modeFor(initial, app.id) === 'mock') {
        document.write('<script src="' + new URL(app.id + '.js', root).href + '"><\/script>');
      }
    }
  }

  let sessionEpoch = 0, changingSession = 0;
  function mockAuthorization(path) {
    const app = moduleFor(path);
    const module = apps.has(app) ? app : (/^\/api\/v1\/jobs\/[^/?]+$/.test(path) ? 'meeting' : null);
    const c = cfg();
    if (!module || c.mode !== 'http' || modeFor(c, module) !== 'mock')
      throw { status: 403, code: 'FORBIDDEN', message: '该接口不属于已配置的模拟模块' };
    const epoch = sessionEpoch;
    const check = () => {
      if (changingSession || epoch !== sessionEpoch) throw { status: 401, code: 'SESSION_CHANGED', message: '身份已变更，请重新操作' };
    };
    check();
    return {
      epoch, check,
      async profile() {
        check();
        const p = await raw('GET', '/api/v1/me', null, 'platform');
        check();
        if (!Array.isArray(p.grants?.[module]) || !p.grants[module].includes('view'))
          throw { status: 403, code: 'FORBIDDEN', message: '无权查看此模块' };
        return p;
      },
    };
  }

  // 渐进迁移混合模式（api.mode !== 'http' 且 platform 单独覆盖为 'http'）：
  // 真实账号口令只发往 HTTP 后端，本地仅按角色映射演示会话；部署态 api.mode === 'http' 由 mockAuthorization 实时鉴权且不落盘。
  const sessionPaths = /^(?:POST \/api\/v1\/auth\/login|GET \/api\/v1\/(?:auth\/session|me))$/;
  let sessionRevision = 0;
  let authPending = false;
  function clearMockSession() {
    if (cfg().mode === 'http') return;
    const X = window.JKAPI && window.JKAPI.ext;
    if (X?.state().session) { X.state().session = null; X.save(); }
  }
  if (initial.mode !== 'http' && modeFor(initial, 'platform') === 'http') clearMockSession();

  function syncMockSession(config, out) {
    if (config.mode === 'http') return;
    const X = window.JKAPI && window.JKAPI.ext;
    if (!X || ![...apps].some(id => modeFor(config, id) === 'mock')) return;
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

  async function requestMock(method, path, body, config) {
    const mock = window.JKAPI;
    if (config.mode === 'http') {
      if (!mock || (Object.hasOwn(mock, 'guard') && !mock.guard))
        throw { status: 503, code: 'NO_MOCK', message: '模块模拟服务或鉴权未加载' };
      return mock.request(method, path, body);
    }
    if (!mock) throw { status: 0, code: 'NO_MOCK', message: '模拟后端未加载' };
    if (method === 'POST' && path === '/api/v1/demo/reset') {
      mock.reset();
      return { ok: true };
    }
    if (method === 'POST' && path === '/api/v1/auth/login') {
      const login = await mock.request(method, path, body);
      if (login.role === undefined && login.grants === undefined) {
        const { role, grants } = await mock.request('GET', '/api/v1/me');
        return { ...login, role, grants };
      }
      return login;
    }
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

  async function request(method, path, body, module = moduleFor(path), decodeHttp) {
    const sessionChange = method === 'POST' && /^\/api\/v1\/auth\/(login|logout)$/.test(path);
    if (sessionChange) { ++sessionEpoch; ++changingSession; }
    let out;
    try { out = await raw(method, path, body, module, decodeHttp); }
    finally { if (sessionChange) { ++sessionEpoch; --changingSession; } }
    if (method !== 'GET' && window.JK && window.JK.bus) setTimeout(() => window.JK.bus.emit('api:write', { method, path }), 0);
    return out;
  }

  async function raw(method, path, body, module = moduleFor(path), decodeHttp) {
    const c = cfg();
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
      const mayInvalidateSession = !authPending;
      const maySyncSession = isLogin || (!authPending && sessionPaths.test(operation));
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), timeoutMs());
      try {
        const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
        const r = await fetch(c.baseUrl.replace(/\/$/, '') + path, { method, credentials: 'include', signal: ctl.signal,
          headers: isForm ? {} : { 'Content-Type': 'application/json' }, body: body == null || method === 'GET' ? undefined : isForm ? body : JSON.stringify(body) });
        if (r.ok && decodeHttp) return await decodeHttp(r);
        const j = await r.json().catch(e => {
          if (e?.name === 'AbortError') throw e;
          return {};
        });
        if (r.status === 401 && module === 'platform' && mayInvalidateSession && revision === sessionRevision) clearMockSession();
        if (!r.ok) {
          const err = j?.error || j || {};
          const message = [err?.message, j?.message, r.statusText].find((s) => typeof s === 'string' && s.trim());
          throw { status: r.status, code: err?.code || j?.code || 'HTTP_' + r.status,
            message: message || `请求失败（HTTP ${r.status}）`, details: err?.details };
        }
        if (revision === sessionRevision && maySyncSession) syncMockSession(c, j);
        return j;
      } catch (e) { if (e && e.name === 'AbortError') throw { status: 0, code: 'TIMEOUT', message: '服务器响应超时' }; throw e.status !== undefined ? e : { status: 0, code: 'NETWORK', message: '网络不可用' }; }
      finally {
        clearTimeout(t);
        if (changesSession && revision === sessionRevision) authPending = false;
      }
    }
    return requestMock(method, path, body, c);
  }

  const qs = (o) => { const p = Object.entries(o || {}).filter(([, v]) => v !== undefined && v !== null && v !== ''); return p.length ? '?' + p.map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&') : ''; };
  window.JKHttp = {
    request: (method, path, body) => request(method, path, body), qs, timeoutMs, mockAuthorization,
    get: (p, q) => request('GET', p + qs(q)), post: (p, b) => request('POST', p, b), put: (p, b) => request('PUT', p, b),
    getFile: (p, decode) => request('GET', p, undefined, moduleFor(p), decode),
    patch: (p, b) => request('PATCH', p, b), del: (p) => request('DELETE', p),
    // 通用 job 路径有多个所有者；只有会议适配器发出的轮询归属会议。
    meetingJob: id => request('GET', '/api/v1/jobs/' + encodeURIComponent(id), null, 'meeting'),
    mode,
  };
})();

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
        if (!r.ok) {
          const error = j?.error || j || {};
          throw { status: r.status, code: error.code || 'HTTP_' + r.status,
            message: error.message || r.statusText, details: error.details };
        }
        return j;
      } catch (e) { if (e && e.name === 'AbortError') throw { status: 0, code: 'TIMEOUT', message: '服务器响应超时' }; throw e.status !== undefined ? e : { status: 0, code: 'NETWORK', message: '网络不可用' }; }
      finally { clearTimeout(t); }
    }
    if (!window.JKAPI) throw { status: 0, code: 'NO_MOCK', message: '模拟后端未加载' };
    if (method === 'POST' && path === '/api/v1/demo/reset') {
      window.JKAPI.reset();
      return { ok: true };
    }
    // §7 的简写路径与 §3.6 的恢复路径共用同一个现有 mock 处理器。
    if (method === 'POST' && /^\/api\/v1\/kb\/docs\/[^/?]+$/.test(path)) path += '/restore';
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

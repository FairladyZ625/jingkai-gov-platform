/* =====================================================================
 * 接口适配层 · 传输（唯一出口）。界面代码只通过 JK.http / api/*.js 访问后端。
 * JK_CONFIG.api.mode = 'mock' → 调浏览器内模拟后端 mock/（window.JKAPI.request）
 *                    = 'http' → fetch(baseUrl + path)，带会话 Cookie；返回同构 JSON
 * 错误统一抛 { status, code, message }。
 * ===================================================================== */
(function () {
  const cfg = () => (window.JK_CONFIG && window.JK_CONFIG.api) || { mode: 'mock' };
  const timeoutMs = () => cfg().timeoutMs || 20000;
  async function request(method, path, body) {
    const out = await raw(method, path, body);
    if (method !== 'GET' && window.JK && window.JK.bus) setTimeout(() => window.JK.bus.emit('api:write', { method, path }), 0);
    return out;
  }
  async function raw(method, path, body) {
    const c = cfg();
    if (c.mode === 'http') {
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), timeoutMs());
      try {
        const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
        const r = await fetch(c.baseUrl.replace(/\/$/, '') + path, { method, credentials: 'include', signal: ctl.signal,
          headers: isForm ? {} : { 'Content-Type': 'application/json' }, body: body == null || method === 'GET' ? undefined : isForm ? body : JSON.stringify(body) });
        const j = await r.json().catch(e => {
          if (e?.name === 'AbortError') throw e;
          return {};
        });
        if (!r.ok) {
          const err = j?.error || j;
          const message = [err?.message, j?.message].find((s) => typeof s === 'string' && s.trim());
          throw { status: r.status, code: err?.code || j?.code || 'HTTP_' + r.status, message: message || `请求失败（HTTP ${r.status}）` };
        }
        return j;
      } catch (e) { if (e && e.name === 'AbortError') throw { status: 0, code: 'TIMEOUT', message: '服务器响应超时' }; throw e.status !== undefined ? e : { status: 0, code: 'NETWORK', message: '网络不可用' }; }
      finally { clearTimeout(t); }
    }
    if (!window.JKAPI) throw { status: 0, code: 'NO_MOCK', message: '模拟后端未加载' };
    return window.JKAPI.request(method, path, body);
  }
  const qs = (o) => { const p = Object.entries(o || {}).filter(([, v]) => v !== undefined && v !== null && v !== ''); return p.length ? '?' + p.map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&') : ''; };
  window.JKHttp = {
    request, qs, timeoutMs,
    get: (p, q) => request('GET', p + qs(q)), post: (p, b) => request('POST', p, b), put: (p, b) => request('PUT', p, b),
    patch: (p, b) => request('PATCH', p, b), del: (p) => request('DELETE', p),
    mode: () => cfg().mode,
  };
})();

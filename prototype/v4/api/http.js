/* =====================================================================
 * 接口适配层 · 传输（唯一出口）。界面代码只通过 JK.http / api/*.js 访问后端。
 * JK_CONFIG.api.mode = 'mock' → 调浏览器内模拟后端 mock/（window.JKAPI.request）
 *                    = 'http' → fetch(baseUrl + path)，带会话 Cookie；普通请求返回 JSON，文件请求解码响应体
 * 错误统一抛 { status, code, message }。
 * ===================================================================== */
(function () {
  const cfg = () => (window.JK_CONFIG && window.JK_CONFIG.api) || { mode: 'mock' };
  async function request(method, path, body, decodeHttp) {
    const out = await raw(method, path, body, decodeHttp);
    if (method !== 'GET' && window.JK && window.JK.bus) setTimeout(() => window.JK.bus.emit('api:write', { method, path }), 0);
    return out;
  }
  async function raw(method, path, body, decodeHttp) {
    const c = cfg();
    if (c.mode === 'http') {
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), c.timeoutMs || 20000);
      try {
        const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
        const r = await fetch(c.baseUrl.replace(/\/$/, '') + path, { method, credentials: 'include', signal: ctl.signal,
          headers: isForm ? {} : { 'Content-Type': 'application/json' }, body: body == null || method === 'GET' ? undefined : isForm ? body : JSON.stringify(body) });
        if (r.ok && decodeHttp) return await decodeHttp(r);
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw { status: r.status, code: j.code || 'HTTP_' + r.status, message: j.message || r.statusText };
        return j;
      } catch (e) { if (e && e.name === 'AbortError') throw { status: 0, code: 'TIMEOUT', message: '服务器响应超时' }; throw e.status !== undefined ? e : { status: 0, code: 'NETWORK', message: '网络不可用' }; }
      finally { clearTimeout(t); }
    }
    if (!window.JKAPI) throw { status: 0, code: 'NO_MOCK', message: '模拟后端未加载' };
    return window.JKAPI.request(method, path, body);
  }
  const qs = (o) => { const p = Object.entries(o || {}).filter(([, v]) => v !== undefined && v !== null && v !== ''); return p.length ? '?' + p.map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&') : ''; };
  window.JKHttp = {
    request, qs,
    get: (p, q) => request('GET', p + qs(q)), post: (p, b) => request('POST', p, b), put: (p, b) => request('PUT', p, b),
    getFile: (p, decode) => request('GET', p, undefined, decode),
    patch: (p, b) => request('PATCH', p, b), del: (p) => request('DELETE', p),
    mode: () => cfg().mode,
  };
})();

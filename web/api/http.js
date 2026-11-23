/* =====================================================================
 * 接口适配层 · 传输（唯一出口）。界面代码只通过 JK.http / api/*.js 访问后端。
 * JK_CONFIG.api.mode = 'mock' → 调浏览器内模拟后端 mock/（window.JKAPI.request）
 *                    = 'http' → fetch(baseUrl + path)，带会话 Cookie；普通请求返回 JSON，文件请求解码响应体
 * 错误统一抛 { status, code, message }。
 * ===================================================================== */
(function () {
  const cfg = () => (window.JK_CONFIG && window.JK_CONFIG.api) || { mode: 'mock' };
  const timeoutMs = () => cfg().timeoutMs || 20000;
  const apps = new Set(['kb', 'policy', 'enterprise', 'document', 'meeting', 'computer', 'skills']);
  function moduleFor(path) {
    const p = path.split('?')[0];
    const app = /^\/api\/apps\/([^/]+)(?:\/|$)/.exec(p)?.[1] ||
      /^\/api\/v1\/(kb|skills)(?:\/|$)/.exec(p)?.[1];
    return apps.has(app) ? app : null;
  }
  function mode(module) {
    const c = cfg();
    if (c.mode !== 'http' || !apps.has(module) || !Object.hasOwn(c.modules || {}, module)) return c.mode;
    const setting = c.modules[module];
    if (setting !== 'mock' && setting !== 'http') throw {status:503, code:'INVALID_TRANSPORT', message:'模块传输配置无效'};
    return setting;
  }
  let sessionEpoch = 0, changingSession = 0;
  function mockAuthorization(path) {
    const module = moduleFor(path) || (/^\/api\/v1\/jobs\/[^/?]+$/.test(path) ? 'meeting' : null);
    if (!module || cfg().mode !== 'http' || mode(module) !== 'mock')
      throw {status:403, code:'FORBIDDEN', message:'该接口不属于已配置的模拟模块'};
    const epoch = sessionEpoch;
    const check = () => {
      if (changingSession || epoch !== sessionEpoch) throw {status:401, code:'SESSION_CHANGED', message:'身份已变更，请重新操作'};
    };
    check();
    return {epoch, check, async profile() {
      check();
      const p = await raw('GET', '/api/v1/me', null, null);
      check();
      if (!Array.isArray(p.grants?.[module]) || !p.grants[module].includes('view'))
        throw {status:403, code:'FORBIDDEN', message:'无权查看此模块'};
      return p;
    }};
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
  async function raw(method, path, body, module, decodeHttp) {
    const c = cfg();
    if (c.mode === 'http' && mode(module) === 'mock') {
      if (!window.JKAPI?.guard) throw {status:503, code:'NO_MOCK', message:'模块模拟服务或鉴权未加载'};
      return window.JKAPI.request(method, path, body);
    }
    if (c.mode === 'http') {
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
    request: (method, path, body) => request(method, path, body), qs, timeoutMs, mockAuthorization,
    get: (p, q) => request('GET', p + qs(q)), post: (p, b) => request('POST', p, b), put: (p, b) => request('PUT', p, b),
    getFile: (p, decode) => request('GET', p, undefined, moduleFor(p), decode),
    patch: (p, b) => request('PATCH', p, b), del: (p) => request('DELETE', p),
    // 通用 job 路径有多个所有者；只有会议适配器发出的轮询归属会议。
    meetingJob: id => request('GET', '/api/v1/jobs/' + encodeURIComponent(id), null, 'meeting'),
    mode,
  };
})();

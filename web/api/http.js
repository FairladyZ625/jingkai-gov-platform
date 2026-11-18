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

  const loginPath = '/api/v1/auth/login';
  const retryLimit = 3;
  const actionNames = { view: '查看', operate: '操作', approve: '审批', admin: '管理' };
  const readPosts = new Set(['/api/v1/kb/search', '/api/v1/kb/ask', '/api/v1/kb/import/preview']);
  let sessionVersion = 0;

  function event(name, detail) {
    window.dispatchEvent?.(new CustomEvent('jk:api:' + name, { detail }));
  }

  function responseError(r, data, path) {
    const error = data?.error || data || {};
    const { app, need } = error.details || {};
    let message = error.message || '请求失败，请稍后重试';
    if (r.status === 401) message = path === loginPath ? '用户名或密码错误' : '登录已失效，请重新登录';
    if (r.status === 403 && app && need) message = `缺少应用「${app}」的${actionNames[need] || need}权限`;
    if (r.status >= 500) message = '服务暂时不可用，请稍后重试';
    return { status: r.status, code: error.code || 'HTTP_' + r.status, message, details: error.details };
  }

  async function readEvents(body, onEvent, resetTimeout) {
    const reader = body.pipeThrough(new TextDecoderStream()).getReader();
    let pending = '';
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) throw { status: 0, message: '对话连接中断，请重新发送' };
        resetTimeout();
        pending += value;
        for (let separator; (separator = /(?:\r\n|\r(?!\n)|\n){2}/.exec(pending));) {
          const lines = pending.slice(0, separator.index).split(/\r\n|\r|\n/);
          pending = pending.slice(separator.index + separator[0].length);
          let type = 'message';
          const data = [];
          for (const line of lines) {
            if (line.startsWith('event:')) type = line.slice(6).trim();
            if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
          }
          if (!data.length) continue;
          let payload;
          try { payload = JSON.parse(data.join('\n')); }
          catch { throw { status: 0, message: '对话返回了无法读取的内容，请重新发送' }; }
          onEvent(type, payload);
          if (type === 'done') return payload;
          if (type === 'error') throw { status: 0, message: payload?.error?.message || payload?.message || '对话生成失败' };
        }
      }
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }

  async function request(method, path, body, onEvent) {
    const out = await raw(method, path, body, onEvent);
    if (method !== 'GET' && window.JK && window.JK.bus) setTimeout(() => window.JK.bus.emit('api:write', { method, path }), 0);
    return out;
  }
  async function raw(method, path, body, onEvent) {
    const c = cfg();
    if (modeFor(c, moduleFor(path)) === 'http') {
      const version = sessionVersion;
      const route = path.split('?')[0];
      // 仅重放读请求。服务端可能已经接受写入，即使浏览器没收到响应。
      const retryable = method === 'GET' || (method === 'POST' && readPosts.has(route));
      // 旧演示配置指向静态服务端口。使用浏览器同源的实例地址，显式配置的其他地址仍生效。
      const base = (window.location && c.baseUrl === 'http://127.0.0.1:8080' ? '' : c.baseUrl || '').replace(/\/$/, '');
      const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
      const headers = isForm ? {} : { 'Content-Type': 'application/json' };
      if (onEvent) headers.Accept = 'text/event-stream, application/json';
      for (let attempt = 0; ; attempt++) {
        const ctl = new AbortController();
        let timeout;
        function resetTimeout() {
          clearTimeout(timeout);
          timeout = setTimeout(() => ctl.abort(), c.timeoutMs || 20000);
        }
        resetTimeout();
        try {
          const r = await fetch(base + path, { method, credentials: 'include', signal: ctl.signal, headers,
            body: body == null || method === 'GET' ? undefined : isForm ? body : JSON.stringify(body) });
          if (onEvent && r.ok && r.headers.get('content-type')?.includes('text/event-stream')) {
            resetTimeout();
            return await readEvents(r.body, onEvent, resetTimeout);
          }
          const data = await r.json().catch((error) => {
            if (ctl.signal.aborted) throw error;
            return {};
          });
          if (!r.ok) throw responseError(r, data, route);
          if (route === loginPath || route === '/api/v1/auth/logout') sessionVersion++;
          return data;
        } catch (cause) {
          const timedOut = ctl.signal.aborted;
          const error = cause?.status !== undefined ? cause : { status: 0, code: timedOut ? 'TIMEOUT' : 'NETWORK',
            message: timedOut ? '服务器响应超时' : '网络不可用，请检查连接' };
          if (error.status === 401 && route !== loginPath && version === sessionVersion) {
            event('unauthenticated', error);
          } else if ((error.status === 0 || error.status >= 500) && retryable &&
                     attempt < retryLimit && version === sessionVersion) {
            event('notice', { message: error.message + `，正在重试（${attempt + 1}/${retryLimit}）` });
            await new Promise((resolve) => setTimeout(resolve, 250 * 2 ** attempt));
            if (version === sessionVersion) continue;
          } else if (error.status === 403 || error.status === 0 || error.status >= 500) {
            event('notice', error);
          }
          throw error;
        } finally {
          clearTimeout(timeout);
        }
      }
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
    stream: (p, b, onEvent) => request('POST', p, b, onEvent),
    get: (p, q) => request('GET', p + qs(q)), post: (p, b) => request('POST', p, b), put: (p, b) => request('PUT', p, b),
    patch: (p, b) => request('PATCH', p, b), del: (p) => request('DELETE', p),
    mode: () => modeFor(cfg(), 'platform'),
  };
})();

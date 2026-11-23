/* =====================================================================
 * 接口适配层 · 传输（唯一出口）。界面代码只通过 JK.http / api/*.js 访问后端。
 * JK_CONFIG.api.modules 可覆盖单个模块，其余请求沿用 api.mode。
 * mock 调 window.JKAPI，http 调 fetch 并携带会话 Cookie；支持 SSE 流与文件响应解码。
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
  const loginPath = '/api/v1/auth/login';
  const retryLimit = 3;
  const actionNames = { view: '查看', operate: '操作', approve: '审批', admin: '管理' };
  const readPosts = new Set(['/api/v1/kb/search', '/api/v1/kb/ask', '/api/v1/kb/import/preview']);
  let sessionRevision = 0;
  let authPending = false;

  function emitEvent(name, detail) {
    if (typeof CustomEvent === 'function') window.dispatchEvent?.(new CustomEvent('jk:api:' + name, { detail }));
  }

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

  function responseError(r, data, route) {
    const error = data?.error || data || {};
    const { app, need } = error.details || {};
    const explicit = [error.message, data?.message].find((s) => typeof s === 'string' && s.trim());
    let message = explicit || r.statusText || `请求失败（HTTP ${r.status}）`;
    if (r.status === 401) message = route === loginPath ? '用户名或密码错误' : '登录已失效，请重新登录';
    else if (r.status === 403 && app && need) message = `缺少应用「${app}」的${actionNames[need] || need}权限`;
    else if (!explicit && r.status >= 500 && r.status !== 502) message = '服务暂时不可用，请稍后重试';
    return { status: r.status, code: error.code || data?.code || 'HTTP_' + r.status, message, details: error.details };
  }

  async function readEvents(body, onEvent, resetTimeout) {
    const reader = body.pipeThrough(new TextDecoderStream()).getReader();
    let pending = '';
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) throw { status: 0, code: 'STREAM_ABORTED', message: '对话连接中断，请重新发送' };
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
          catch { throw { status: 0, code: 'INVALID_STREAM', message: '对话返回了无法读取的内容，请重新发送' }; }
          onEvent(type, payload);
          if (type === 'done') return payload;
          if (type === 'error') throw { status: 0, code: 'STREAM_ERROR', message: payload?.error?.message || payload?.message || '对话生成失败' };
        }
      }
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
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

  async function request(method, path, body, module = moduleFor(path), decodeHttp, onEvent) {
    const sessionChange = method === 'POST' && /^\/api\/v1\/auth\/(login|logout)$/.test(path);
    if (sessionChange) { ++sessionEpoch; ++changingSession; }
    let out;
    try { out = await raw(method, path, body, module, decodeHttp, onEvent); }
    finally { if (sessionChange) { ++sessionEpoch; --changingSession; } }
    if (method !== 'GET' && window.JK && window.JK.bus) setTimeout(() => window.JK.bus.emit('api:write', { method, path }), 0);
    return out;
  }

  async function raw(method, path, body, module = moduleFor(path), decodeHttp, onEvent) {
    const c = cfg();
    if (modeFor(c, module) === 'http') {
      const route = path.split('?')[0];
      const operation = method + ' ' + route;
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
      const retryable = (module === 'platform' || module === 'kb') && !onEvent && !decodeHttp &&
        (method === 'GET' || (method === 'POST' && readPosts.has(route)));
      const maxRetries = Number.isInteger(c.retryLimit) && c.retryLimit >= 0 ? c.retryLimit : retryLimit;
      const sameOrigin = /^https?:$/.test(window.location?.protocol) && c.baseUrl === 'http://127.0.0.1:8080';
      const base = (sameOrigin ? '' : c.baseUrl || '').replace(/\/$/, '');
      const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
      const headers = isForm ? {} : { 'Content-Type': 'application/json' };
      if (onEvent) headers.Accept = 'text/event-stream, application/json';

      for (let attempt = 0; ; attempt++) {
        const ctl = new AbortController();
        let timeout;
        function resetTimeout() {
          clearTimeout(timeout);
          timeout = setTimeout(() => ctl.abort(), timeoutMs());
        }
        resetTimeout();
        try {
          const r = await fetch(base + path, { method, credentials: 'include', signal: ctl.signal, headers,
            body: body == null || method === 'GET' ? undefined : isForm ? body : JSON.stringify(body) });
          if (onEvent && r.ok && r.headers?.get('content-type')?.includes('text/event-stream')) {
            resetTimeout();
            return await readEvents(r.body, onEvent, resetTimeout);
          }
          if (r.ok && decodeHttp) return await decodeHttp(r);
          const data = await r.json().catch((err) => {
            if (ctl.signal.aborted || err?.name === 'AbortError') throw err;
            return {};
          });
          if (!r.ok) throw responseError(r, data, route);
          if (revision === sessionRevision && maySyncSession) syncMockSession(c, data);
          return data;
        } catch (cause) {
          const timedOut = ctl.signal.aborted || cause?.name === 'AbortError';
          const error = cause?.status !== undefined ? cause : {
            status: 0, code: timedOut ? 'TIMEOUT' : 'NETWORK',
            message: timedOut ? '服务器响应超时' : '网络不可用，请检查连接',
          };
          if (error.status === 401 && route !== loginPath && mayInvalidateSession && revision === sessionRevision) {
            sessionRevision++;
            clearMockSession();
            emitEvent('unauthenticated', error);
          } else if ((error.status === 0 || error.status >= 500) && retryable &&
                     attempt < maxRetries && revision === sessionRevision) {
            emitEvent('notice', { message: error.message + `，正在重试（${attempt + 1}/${maxRetries}）`, retrying: true });
            await new Promise((resolve) => setTimeout(resolve, 250 * 2 ** attempt));
            if (revision === sessionRevision) continue;
          } else if (error.status === 403 || error.status === 0 || error.status >= 500) {
            emitEvent('notice', error);
          }
          throw error;
        } finally {
          clearTimeout(timeout);
          if (changesSession && revision === sessionRevision) authPending = false;
        }
      }
    }
    return requestMock(method, path, body, c);
  }

  const qs = (o) => { const p = Object.entries(o || {}).filter(([, v]) => v !== undefined && v !== null && v !== ''); return p.length ? '?' + p.map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&') : ''; };
  window.JKHttp = {
    request: (method, path, body) => request(method, path, body), qs, timeoutMs, mockAuthorization,
    stream: (p, b, onEvent) => request('POST', p, b, moduleFor(p), undefined, onEvent),
    get: (p, q) => request('GET', p + qs(q)), post: (p, b) => request('POST', p, b), put: (p, b) => request('PUT', p, b),
    getFile: (p, decode) => request('GET', p, undefined, moduleFor(p), decode),
    patch: (p, b) => request('PATCH', p, b), del: (p) => request('DELETE', p),
    // 通用 job 路径有多个所有者；只有会议适配器发出的轮询归属会议。
    meetingJob: id => request('GET', '/api/v1/jobs/' + encodeURIComponent(id), null, 'meeting'),
    mode,
  };
})();

// HAiKnow 平台 SDK（浏览器端）。应用前端只能 import 本目录（/sdk/...）和自己 web/ 下的文件。
// 外壳调用应用的 mount(el, ctx)；ctx 由 createContext 生成。
import { appErrorMessage, defineErrors, loadAppErrors } from './preview/errors.js';

export const SDK_VERSION = '2.0.0';

export async function http(path, opts = {}) {
  const init = { credentials: 'same-origin', ...opts, headers: { ...(opts.headers || {}) } };
  if (opts.json !== undefined) {
    init.body = JSON.stringify(opts.json);
    init.headers['Content-Type'] = 'application/json';
    init.method = init.method || 'POST';
  }
  const r = await fetch(path, init);
  const type = r.headers.get('content-type') || '';
  const data = type.includes('json') ? await r.json() : await r.text();
  if (!r.ok) {
    const msg = data?.error?.message || (data && data.detail) || r.statusText;
    const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    err.status = r.status;
    if (data?.error) Object.assign(err, data.error);
    throw err;
  }
  return data;
}

// 外壳可直接使用；应用使用 createContext 上绑定 app 的句柄。
export const v1 = {
  me: () => http('/api/v1/me'),
  projects: () => http('/api/v1/projects'),
  reviews: (filters = { assignee: 'me' }) => http(`/api/v1/reviews?${new URLSearchParams(filters)}`),
  notifications: () => http('/api/v1/notifications'),
};

export function createContext(app, user, toast) {
  const base = `/api/apps/${app.id}`;
  return {
    app,
    user,
    can: (action) => app.actions.includes(action),
    api: (path, opts) => http(base + path, opts),
    upload: (path, file, field = 'file') => {
      const fd = new FormData();
      fd.append(field, file);
      return http(base + path, { method: 'POST', body: fd });
    },
    url: (path) => base + path,
    records: {
      save: (body, id) => http(`/api/v1/apps/${app.id}/records${id ? `/${encodeURIComponent(id)}` : ''}`, { method: id ? 'PUT' : 'POST', json: body }),
      get: (id, version) => http(`/api/v1/apps/${app.id}/records/${encodeURIComponent(id)}${version == null ? '' : `/versions/${version}`}`),
      list: (filters = {}) => http(`/api/v1/apps/${app.id}/records?${new URLSearchParams(filters)}`),
    },
    dataFiles: {
      save: (file, project, purpose) => {
        const fd = new FormData();
        for (const [key, value] of Object.entries({ file, project, purpose, app: app.id })) fd.append(key, value);
        return http('/api/v1/files', { method: 'POST', body: fd });
      },
      get: (id) => http(`/api/v1/files/${encodeURIComponent(id)}`),
      url: (id) => `/api/v1/files/${encodeURIComponent(id)}/content`,
    },
    reviews: {
      submit: (recordId, version, assignee) => http('/api/v1/reviews', { json: { appId: app.id, recordId, version, assignee } }),
      decide: (id, body) => http(`/api/v1/reviews/${encodeURIComponent(id)}/decisions`, { json: body }),
      list: (filters = { assignee: 'me' }) => http(`/api/v1/reviews?${new URLSearchParams({ ...filters, app: app.id })}`),
    },
    artifacts: {
      find: (filters = {}) => http(`/api/v1/artifacts?${new URLSearchParams(filters)}`),
    },
    notifications: {
      list: () => http(`/api/v1/notifications?${new URLSearchParams({ app: app.id })}`),
      read: (id) => http(`/api/v1/notifications/${encodeURIComponent(id)}/read`, { method: 'POST' }),
    },
    preview: {
      datasets: {
        list: async () => (await import('./preview/datasets.js')).list(http, app.id),
        query: async (id, options = {}) => (await import('./preview/datasets.js')).query(http, app.id, id, options),
      },
      members: {
        list: async (project, action = 'approve') => (await import('./preview/members.js')).list(http, app.id, project, action),
      },
      messages: {
        send: async (body) => (await import('./preview/messages.js')).send(http, app.id, body),
        inbox: async () => (await import('./preview/messages.js')).inbox(http),
        get: async (id) => (await import('./preview/messages.js')).get(http, id),
        read: async (id) => (await import('./preview/messages.js')).read(http, id),
        acknowledge: async (id) => (await import('./preview/messages.js')).acknowledge(http, id),
        sent: async () => (await import('./preview/messages.js')).sent(http, app.id),
      },
      schedules: {
        list: async () => (await import('./preview/schedules.js')).list(http, app.id),
        enable: async (name, project) => (await import('./preview/schedules.js')).enable(http, app.id, name, project),
        pause: async (name, project) => (await import('./preview/schedules.js')).pause(http, app.id, name, project),
        resume: async (name, project) => (await import('./preview/schedules.js')).resume(http, app.id, name, project),
        run: async (name, project) => (await import('./preview/schedules.js')).run(http, app.id, name, project),
      },
      aiTools: {
        embedding: async (text, options = {}) => (await import('./preview/ai-tools.js')).embedding(http, app.id, text, options),
        parse: async (fileId, options = {}) => (await import('./preview/ai-tools.js')).parse(http, app.id, fileId, options),
        search: async (query, options = {}) => (await import('./preview/ai-tools.js')).search(http, app.id, query, options),
        fetch: async (url, options = {}) => (await import('./preview/ai-tools.js')).fetchPage(http, app.id, url, options),
        vision: async (fileId, instruction, options = {}) => (await import('./preview/ai-tools.js')).vision(http, app.id, fileId, instruction, options),
        transcribe: async (fileId, options = {}) => (await import('./preview/ai-tools.js')).transcribe(http, app.id, fileId, options),
      },
      crossProject: {
        records: async (subject, filters = {}) => (await import('./preview/cross-project.js')).records(http, app.id, subject, filters),
        get: async (id, version) => (await import('./preview/cross-project.js')).get(http, app.id, id, version),
        readFile: async (id) => (await import('./preview/cross-project.js')).readFile(http, app.id, id),
      },
      knowledge: {
        categories: async () => (await import('./preview/knowledge.js')).categories(http),
        list: async (options = {}) => (await import('./preview/knowledge.js')).list(http, app.id, options),
        get: async (id) => (await import('./preview/knowledge.js')).get(http, id),
        upload: async (file, options = {}) => (await import('./preview/knowledge.js')).upload(http, app.id, file, options),
        addVersion: async (id, file, options = {}) => (await import('./preview/knowledge.js')).addVersion(http, id, file, options),
        update: async (id, patch) => (await import('./preview/knowledge.js')).update(http, id, patch),
        submit: async (id, version) => (await import('./preview/knowledge.js')).submit(http, id, version),
        publish: async (id, version) => (await import('./preview/knowledge.js')).publish(http, id, version),
        references: async (id) => (await import('./preview/knowledge.js')).references(http, id),
        recordFiles: async (appId, recordId, version) => (await import('./preview/knowledge.js')).recordFiles(http, appId, recordId, version),
        url: (id, version) => `/api/v1/knowledge/entries/${encodeURIComponent(id)}/versions/${version}/content`,
      },
      errors: {
        load: () => loadAppErrors(app.id),
        define: (table) => defineErrors(app.id, table),
        message: (error) => appErrorMessage(app.id, error),
      },
      latex: {
        templates: async () => (await import('./preview/latex.js')).templates(http),
        render: async (body) => (await import('./preview/latex.js')).render(http, app.id, body),
      },
      media: {
        capture: async (options = {}) => (await import('./preview/media.js')).capture(http, app.id, options),
        upload: async (file, options = {}) => (await import('./preview/media.js')).upload(http, app.id, file, options),
      },
      cad: {
        status: async () => (await import('./preview/cad.js')).status(http),
        parse: async (entryId, options = {}) => (await import('./preview/cad.js')).parse(http, app.id, entryId, options),
      },
      feishu: {
        messages: async (filters = {}) => (await import('./preview/feishu.js')).messages(http, app.id, filters),
        message: async (id) => (await import('./preview/feishu.js')).message(http, app.id, id),
        status: async () => (await import('./preview/feishu.js')).status(http, app.id),
      },
    },
    toast,
  };
}

// 统一界面组件：保证几十个应用风格一致。
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'class') el.className = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function steps(names, current) {
  return h('ol', { class: 'hk-steps' },
    names.map((n, i) => h('li', { class: i < current ? 'done' : i === current ? 'now' : '' }, n)));
}

export function uploadArea({ accept = '', label = '选择或拖入文件', onFile }) {
  const input = h('input', { type: 'file', accept, hidden: true, onChange: (e) => e.target.files[0] && onFile(e.target.files[0]) });
  const box = h('label', { class: 'hk-upload' }, input, h('strong', {}, label), h('span', {}, accept ? `支持 ${accept}` : ''));
  box.addEventListener('dragover', (e) => { e.preventDefault(); box.classList.add('over'); });
  box.addEventListener('dragleave', () => box.classList.remove('over'));
  box.addEventListener('drop', (e) => { e.preventDefault(); box.classList.remove('over'); e.dataTransfer.files[0] && onFile(e.dataTransfer.files[0]); });
  return box;
}

export function table(columns, rows) {
  return h('table', { class: 'hk-table' },
    h('thead', {}, h('tr', {}, columns.map((c) => h('th', {}, c.title)))),
    h('tbody', {}, rows.map((r, i) => h('tr', {}, columns.map((c) => h('td', {}, c.render ? c.render(r, i) : r[c.key]))))));
}

export function button(text, onClick, { primary = false, disabled = false, title } = {}) {
  return h('button', { class: primary ? 'hk-btn primary' : 'hk-btn', disabled, title, onClick }, text);
}

export function badge(text, tone = '') {
  return h('span', { class: `hk-badge ${tone}` }, text);
}

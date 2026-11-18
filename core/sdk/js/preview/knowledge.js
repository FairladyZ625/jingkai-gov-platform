// 实验能力：公司知识库（CAP-04）。路径固定，调用人身份由平台会话决定，应用 ID 由上下文传入。
function query(params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    search.append(key, value);
  }
  return search.toString();
}

function form(file, options, extra = {}) {
  const body = new FormData();
  if (file) body.append('file', file);
  for (const [key, value] of Object.entries({ ...options, ...extra })) {
    if (value === undefined || value === null || value === '') continue;
    body.append(key, Array.isArray(value) ? value.join(',') : value);
  }
  return body;
}

function entryPath(entryId, tail = '') {
  return `/api/v1/knowledge/entries/${encodeURIComponent(entryId)}${tail}`;
}

export function categories(http) {
  return http('/api/v1/knowledge/categories');
}

export function list(http, appId, options = {}) {
  return http(`/api/v1/knowledge/entries?${query(options)}`);
}

export function get(http, entryId) {
  return http(entryPath(entryId));
}

export function update(http, entryId, patch) {
  return http(entryPath(entryId), { method: 'PATCH', json: patch });
}

export function submit(http, entryId, version) {
  return http(entryPath(entryId, '/submit'), { json: { version } });
}

export function publish(http, entryId, version) {
  return http(entryPath(entryId, '/publish'), { json: { version } });
}

export function references(http, entryId) {
  return http(entryPath(entryId, '/references'));
}

export function recordFiles(http, appId, recordId, version) {
  return http(`/api/v1/knowledge/records/${encodeURIComponent(appId)}/${encodeURIComponent(recordId)}/versions/${version}/files`);
}

export function upload(http, appId, file, options = {}) {
  return http('/api/v1/knowledge/entries', { method: 'POST', body: form(file, options, { sourceApp: appId }) });
}

export function addVersion(http, entryId, file, options = {}) {
  return http(entryPath(entryId, '/versions'), { method: 'POST', body: form(file, options) });
}

export function url(entryId, version) {
  return entryPath(entryId, `/versions/${version}/content`);
}
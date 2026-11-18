// 实验性长任务：复用稳定 HTTP，应用编号由调用上下文提供，不接受选项覆盖。
export function submit(http, appId, body) {
  return http('/api/v1/jobs', { json: { ...body, appId } });
}

export function get(http, appId, id) {
  return http(`/api/v1/jobs/${encodeURIComponent(id)}?${new URLSearchParams({ app: appId })}`);
}

export function list(http, appId, filters = {}) {
  return http(`/api/v1/jobs?${new URLSearchParams({ ...filters, app: appId })}`);
}

export function cancel(http, appId, id) {
  return http(`/api/v1/jobs/${encodeURIComponent(id)}/cancel?${new URLSearchParams({ app: appId })}`, { method: 'POST' });
}

export function retry(http, appId, id) {
  return http(`/api/v1/jobs/${encodeURIComponent(id)}/retry?${new URLSearchParams({ app: appId })}`, { method: 'POST' });
}

export function notifications(http, appId) {
  return http(`/api/v1/jobs/notifications?${new URLSearchParams({ app: appId })}`);
}

export function readNotification(http, appId, id) {
  return http(`/api/v1/jobs/notifications/${encodeURIComponent(id)}/read?${new URLSearchParams({ app: appId })}`, { method: 'POST' });
}

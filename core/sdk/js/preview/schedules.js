// 定时调度管理面：应用编号始终由调用上下文绑定。
const query = (project) => `?project=${encodeURIComponent(project)}`;

export function list(http, appId) {
  return http(`/api/v1/schedules?app=${encodeURIComponent(appId)}`);
}

export function enable(http, appId, name, project) {
  return http(`/api/v1/schedules/${encodeURIComponent(appId)}/${encodeURIComponent(name)}/enable${query(project)}`, { method: 'POST' });
}

export function pause(http, appId, name, project) {
  return http(`/api/v1/schedules/${encodeURIComponent(appId)}/${encodeURIComponent(name)}/pause${query(project)}`, { method: 'POST' });
}

export function resume(http, appId, name, project) {
  return http(`/api/v1/schedules/${encodeURIComponent(appId)}/${encodeURIComponent(name)}/resume${query(project)}`, { method: 'POST' });
}

export function run(http, appId, name, project) {
  return http(`/api/v1/schedules/${encodeURIComponent(appId)}/${encodeURIComponent(name)}/run${query(project)}`, { method: 'POST' });
}

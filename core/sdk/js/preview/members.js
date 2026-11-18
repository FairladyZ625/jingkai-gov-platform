// 项目成员权限查询 preview 句柄；应用 ID 由上下文绑定。
export function list(http, appId, project, action = 'approve') {
  const query = new URLSearchParams({ project, action });
  return http(`/api/v1/apps/${encodeURIComponent(appId)}/members?${query}`);
}

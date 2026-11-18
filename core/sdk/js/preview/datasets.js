// 实验能力：SDK 使用上下文应用 ID，不接受选项覆盖；HTTP 应用 ID 由请求声明。
export function list(http, appId) {
  return http(`/api/v1/datasets?${new URLSearchParams({ appId })}`);
}

export function query(http, appId, id, options = {}) {
  return http(`/api/v1/datasets/${encodeURIComponent(id)}/query`, { json: { ...options, appId } });
}

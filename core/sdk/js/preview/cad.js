// 实验能力：CAD 文件只读解析（DXF / STEP）；输入是知识库条目 ID，不改原件。
export function status(http) {
  return http('/api/v1/cad/status');
}

// body: { entryId, version? }；appId 由调用上下文提供。
export function parse(http, appId, entryId, options = {}) {
  const json = { appId, entryId };
  if (options.version != null) json.version = options.version;
  return http('/api/v1/cad/parse', { json });
}
// 实验能力：按当前应用声明的主体键跨项目只读读取。
export function records(http, appId, subject, filters = {}) {
  return http(`/api/v1/apps/${encodeURIComponent(appId)}/cross-project/records?${new URLSearchParams({ subject, ...filters })}`);
}

export function get(http, appId, id, version) {
  const suffix = version == null ? '' : `?version=${encodeURIComponent(version)}`;
  return http(`/api/v1/apps/${encodeURIComponent(appId)}/cross-project/records/${encodeURIComponent(id)}${suffix}`);
}

export function readFile(http, appId, id) {
  const path = `/api/v1/apps/${encodeURIComponent(appId)}/cross-project/files/${encodeURIComponent(id)}/content`;
  return fetch(path, { credentials: 'same-origin' }).then(async (response) => {
    if (!response.ok) {
      const data = await response.json();
      const error = new Error(data?.error?.message || response.statusText);
      error.status = response.status;
      if (data?.error) Object.assign(error, data.error);
      throw error;
    }
    return new Uint8Array(await response.arrayBuffer());
  });
}

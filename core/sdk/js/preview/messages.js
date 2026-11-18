// 实验能力：应用 ID 固定为当前上下文；发送人与收件人权限由服务端校验。
export function send(http, appId, body) {
  return http(`/api/v1/apps/${encodeURIComponent(appId)}/messages`, { json: body });
}

export function inbox(http) {
  return http('/api/v1/messages');
}

export function get(http, id) {
  return http(`/api/v1/messages/${encodeURIComponent(id)}`);
}

export function read(http, id) {
  return http(`/api/v1/messages/${encodeURIComponent(id)}/read`, { method: 'POST' });
}

export function acknowledge(http, id) {
  return http(`/api/v1/messages/${encodeURIComponent(id)}/acknowledge`, { method: 'POST' });
}

export function sent(http, appId) {
  return http(`/api/v1/apps/${encodeURIComponent(appId)}/messages/sent`);
}

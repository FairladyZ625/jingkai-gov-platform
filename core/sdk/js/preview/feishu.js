// 实验能力：飞书消息抓取（CAP-01）。调用人身份由平台会话决定，应用 ID 由上下文传入。
function query(params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    search.append(key, value);
  }
  return search.toString();
}

export function messages(http, appId, filters = {}) {
  return http(`/api/v1/feishu/messages?${query({ ...filters, appId })}`);
}

export function message(http, appId, messageId) {
  return http(`/api/v1/feishu/messages/${encodeURIComponent(messageId)}?${query({ appId })}`);
}

export function status(http, appId) {
  return http(`/api/v1/feishu/status?${query({ appId })}`);
}
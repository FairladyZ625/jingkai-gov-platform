// 实验能力：AI 工具（文档解析、网络搜索、网页读取、读图识别）。
// 函数式，与 preview/datasets.js 一致：http 由调用方注入，应用 ID 由请求声明。
const API = '/api/v1/ai';

export function parse(http, appId, fileId, options = {}) {
  return http(`${API}/parse`, { json: { appId, fileId, ...options } });
}

export function search(http, appId, query, options = {}) {
  return http(`${API}/search`, { json: { appId, query, ...options } });
}

// 导出名用 fetchPage，避免遮蔽浏览器全局 fetch。
export function fetchPage(http, appId, url, options = {}) {
  return http(`${API}/fetch`, { json: { appId, url, ...options } });
}

export function embedding(http, appId, text, options = {}) {
  return http(`${API}/embedding`, { json: { appId, text, ...options } });
}

export function vision(http, appId, fileId, instruction, options = {}) {
  return http(`${API}/vision`, { json: { appId, fileId, instruction, ...options } });
}

export function transcribe(http, appId, fileId, options = {}) {
  return http(`${API}/transcribe`, { json: { appId, fileId, ...options } });
}

// preview 参数必须穿过浏览器上下文到 HTTP 请求体，稳定 SDK 面保持不变。
import assert from 'node:assert/strict';
import { createContext } from '../../core/sdk/js/haiknow.js';
import { embedding, fetchPage } from '../../core/sdk/js/preview/ai-tools.js';

const calls = [];
const http = async (url, options) => {
  calls.push([url, options.json]);
  return { result: [] };
};
await embedding(http, 'app-a', '公开样例', { classification: 'public' });
assert.deepEqual(calls.pop(), ['/api/v1/ai/embedding', {
  appId: 'app-a', text: '公开样例', classification: 'public',
}]);
await fetchPage(http, 'app-a', 'https://example.test/', { allowed_hosts: ['example.test'] });
assert.deepEqual(calls.pop(), ['/api/v1/ai/fetch', {
  appId: 'app-a', url: 'https://example.test/', allowed_hosts: ['example.test'],
}]);
globalThis.fetch = async (url, options) => {
  calls.push([url, JSON.parse(options.body)]);
  return { ok: true, headers: { get: () => 'application/json' }, json: async () => ({ result: [] }) };
};
const ctx = createContext({ id: 'app-b', actions: ['view'] }, {}, () => {});
await ctx.preview.aiTools.embedding('内部样例', { classification: 'internal' });
assert.deepEqual(calls.pop(), ['/api/v1/ai/embedding', {
  appId: 'app-b', text: '内部样例', classification: 'internal',
}]);
await ctx.preview.aiTools.fetch('https://example.test/', { allowed_hosts: ['example.test'] });
assert.deepEqual(calls.pop(), ['/api/v1/ai/fetch', {
  appId: 'app-b', url: 'https://example.test/', allowed_hosts: ['example.test'],
}]);
console.log('ai-tools preview SDK test ok');

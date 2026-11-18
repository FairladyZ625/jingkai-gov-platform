// 错误中文映射入口的 Node 行为测试。运行：node tests/js/errors.test.mjs
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const mod = await import(pathToFileURL(path.join(ROOT, 'core', 'sdk', 'js', 'preview', 'errors.js')).href);
const { errorMessage, issueMessage, PLATFORM_ERROR_MESSAGES, defineErrors, appErrorMessage, loadAppErrors, GENERIC_ERROR_MESSAGE } = mod;
const err = (message, props) => Object.assign(new Error(message), props);
const debug = console.debug;
const seen = [];
console.debug = (...args) => seen.push(args.join(' '));

// 服务端中文说明优先，且不带原始码
assert.equal(errorMessage(err('原口令不正确', { status: 401, code: 'invalid_credentials' })), '原口令不正确');
// 英文/空说明按码表映射
assert.equal(errorMessage(err('Forbidden', { status: 403, code: 'forbidden' })), '没有执行此操作的权限');
assert.equal(errorMessage(err('', { status: 401, code: 'unauthenticated' })), '登录已失效，请重新登录');
assert.equal(errorMessage(err('Bad gateway', { status: 502, code: 'provider_error' })), '服务商暂时不可用，请检查服务商配置或稍后重试');
assert.equal(errorMessage(err('', { status: 403, code: 'OUTBOUND_DENIED' })), PLATFORM_ERROR_MESSAGES.outbound_denied);
// 说明里夹带原始码时不直出，改走映射
assert.equal(errorMessage(err('操作失败（forbidden）', { code: 'forbidden' })), PLATFORM_ERROR_MESSAGES.forbidden);
// 未知码：不露码，按状态兜底；控制台留码
seen.length = 0;
assert.equal(errorMessage(err('boom', { status: 500, code: 'weird_failed' })), PLATFORM_ERROR_MESSAGES.internal_error);
assert.equal(errorMessage(err('boom', { status: 418, code: 'weird_failed' })), GENERIC_ERROR_MESSAGE);
assert.ok(seen.some((line) => line.includes('weird_failed')));
// 组件校验码：回中文类别，未知码也不回原始码
assert.equal(issueMessage('required'), '必填项缺失');
assert.equal(issueMessage('brand_new'), '校验问题');
assert.equal(errorMessage(null), GENERIC_ERROR_MESSAGE);
assert.equal(errorMessage(new TypeError('Failed to fetch')), PLATFORM_ERROR_MESSAGES.network_error);
// 应用登记：只作用于自己的应用
assert.equal(errorMessage(err('x', { code: 'xxx_failed' }), { xxx_failed: '导出失败，请重试' }), '导出失败，请重试');
defineErrors('app-a', { xxx_failed: 'A 应用导出失败' });
assert.equal(appErrorMessage('app-a', err('x', { code: 'xxx_failed' })), 'A 应用导出失败');
assert.equal(appErrorMessage('app-a', err('x', { code: 'XXX_FAILED' })), 'A 应用导出失败');
assert.equal(errorMessage(err('操作失败（forbidden）', { code: 'FORBIDDEN' })), PLATFORM_ERROR_MESSAGES.forbidden);
assert.equal(appErrorMessage('app-b', err('x', { code: 'xxx_failed' })), GENERIC_ERROR_MESSAGE);
// 从 errors.json 加载；缺失文件静默
await loadAppErrors('app-c', async (url) => {
  assert.equal(url, '/apps/app-c/web/errors.json');
  return { ok: true, json: async () => ({ yyy_failed: 'C 应用处理失败' }) };
});
assert.equal(appErrorMessage('app-c', err('x', { code: 'yyy_failed' })), 'C 应用处理失败');
await loadAppErrors('app-d', async () => ({ ok: false }));
await loadAppErrors('app-d', async () => { throw new Error('offline'); });
// 原型链上的名字不能当码
assert.equal(errorMessage(err('x', { code: 'constructor' })), GENERIC_ERROR_MESSAGE);
console.debug = debug;
console.log('errors ok');

const { parseArgs } = require('node:util');
const { createMock } = require('./mock.cjs');
const { createHttp, ConnectionError } = require('./http.cjs');
const { verify } = require('./assertions.cjs');
const models = require('./models.json');

const modules = ['platform', 'kb', 'policy', 'enterprise', 'meeting', 'document', 'skills', 'computer'];
const loginPath = '/api/v1/auth/login';

function lookup(context, reference) {
  let value = context;
  for (const key of reference.split('.')) {
    if (value == null || !Object.hasOwn(value, key)) throw new Error(`缺少测试数据 ${reference}`);
    value = value[key];
  }
  return value;
}

function resolve(template, context) {
  if (Array.isArray(template)) return template.map(value => resolve(value, context));
  if (template && typeof template === 'object') {
    return Object.fromEntries(Object.entries(template).map(([key, value]) => [key, resolve(value, context)]));
  }
  if (typeof template !== 'string') return template;
  const whole = /^\{\{([\w.]+)\}\}$/.exec(template);
  if (whole) return lookup(context, whole[1]);
  return template.replace(/\{\{([\w.]+)\}\}/g, (_, reference) => String(lookup(context, reference)));
}

function requestPath(contract, context) {
  const path = contract.path.replace(/\{(\w+)\}/g, (_, name) => {
    const value = resolve(contract.params[name], context);
    if (typeof value !== 'string' || !value) throw new Error(`缺少路径参数 ${name}`);
    return encodeURIComponent(value);
  });
  return path + (contract.query ? '?' + new URLSearchParams(resolve(contract.query, context)) : '');
}

async function runModule(id, base, env, write, fail) {
  const transport = base ? createHttp(base) : createMock();
  const fixture = {
    todoId: env.CONTRACT_TODO_ID || 'contract-todo',
    enterpriseId: env.CONTRACT_ENTERPRISE_ID || 'E001',
    meetingId: env.CONTRACT_MEETING_ID || 'MT-1112',
    reviewId: env.CONTRACT_REVIEW_ID || 'R-01',
    kbDocId: env.CONTRACT_KB_DOC_ID || 'KB-P4949503',
    kbUrl: env.CONTRACT_KB_URL || 'https://example.com/contract-fixture',
    username: 'jk-contract-' + Date.now().toString(36),
  };
  const context = { fixture };
  if (base) {
    if (!env.CONTRACT_USERNAME || !env.CONTRACT_PASSWORD) {
      // 先报告不可达，即使调用方没提供演示账号。
      await transport.request('GET', '/api/v1/auth/session');
      throw new Error('HTTP 模式需要通过环境变量设置 CONTRACT_USERNAME 和 CONTRACT_PASSWORD');
    }
    context.credentials = { username: env.CONTRACT_USERNAME, password: env.CONTRACT_PASSWORD };
  } else {
    context.credentials = transport.credentials;
  }
  if (id !== 'platform') {
    const response = await transport.request('POST', loginPath, context.credentials);
    verify(response, { response: { user: '@user' } }, models);
  }

  const { routes, errors } = require('./cases/' + id + '.json');
  let passed = 0;
  let errorPassed = 0;
  async function check(contract) {
    try {
      const body = resolve(contract.body, context);
      const response = await transport.request(contract.method, requestPath(contract, context), body);
      verify(response, contract, models);
      if (contract.save) context[contract.save] = response.body;
      return true;
    } catch (error) {
      if (error instanceof ConnectionError) throw error;
      fail(`[${id}] ${contract.method} ${contract.path}${contract.error ? ' · ' + contract.error : ''}：${error.message}`);
      return false;
    }
  }
  for (const contract of routes) {
    if (await check(contract)) passed++;
  }
  for (const contract of errors) {
    if (await check(contract)) errorPassed++;
  }
  write(`${id}: ${passed}/${routes.length}，错误样例 ${errorPassed}/${errors.length}`);
  return { passed, total: routes.length, errorPassed, errorTotal: errors.length };
}

async function main(args, env = process.env, write = console.log, fail = console.error) {
  const { values } = parseArgs({
    args, options: { base: { type: 'string' }, module: { type: 'string' } },
  });
  if (values.module !== undefined && !modules.includes(values.module)) {
    throw new Error(`未知模块 ${values.module}，可用模块：${modules.join('、')}`);
  }
  let base;
  if (values.base !== undefined) {
    const url = URL.parse(values.base);
    if (!url || !['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
      throw new Error('--base 需要不含凭据、查询或片段的 HTTP(S) 地址');
    }
    base = url.href.replace(/\/$/, '');
  }
  const selected = values.module ? [values.module] : modules;
  write(`契约模式：${base ? 'HTTP' : 'mock'}；模块：${selected.join('、')}`);
  let passed = 0;
  let total = 0;
  let errorPassed = 0;
  let errorTotal = 0;
  for (const id of selected) {
    const result = await runModule(id, base, env, write, fail);
    passed += result.passed;
    total += result.total;
    errorPassed += result.errorPassed;
    errorTotal += result.errorTotal;
  }
  write(`合计 ${passed}/${total}，错误样例 ${errorPassed}/${errorTotal}`);
  return passed === total && errorPassed === errorTotal ? 0 : 1;
}

if (require.main === module) {
  main(process.argv.slice(2)).then(code => { process.exitCode = code; }).catch(error => {
    console.error('契约运行失败：' + error.message);
    process.exitCode = 1;
  });
}

module.exports = { main, modules };

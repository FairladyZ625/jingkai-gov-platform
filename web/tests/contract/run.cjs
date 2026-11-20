const { parseArgs } = require('node:util');
const { randomUUID } = require('node:crypto');
const { createMock } = require('./mock.cjs');
const { createHttp, ConnectionError } = require('./http.cjs');
const { verify } = require('./assertions.cjs');
const models = require('./models.json');

const modules = ['platform', 'kb', 'policy', 'enterprise', 'meeting', 'document', 'skills', 'computer'];
const loginPath = '/api/v1/auth/login';
const resetPath = '/api/v1/demo/reset';
const loginContract = require('./cases/platform.json').routes.find(route => route.path === loginPath);

class MissingData extends Error {}

function isWrite(contract) {
  if (contract.method === 'GET') return contract.path.endsWith('/export');
  return contract.method !== 'POST' || contract.path !== loginPath;
}

function isLoopback(hostname) {
  const host = hostname.replace(/^\[|\]$/g, '').toLowerCase();
  return host === 'localhost' || host === '::1' || /^127(?:\.\d{1,3}){3}$/.test(host);
}

function lookup(context, reference) {
  // a.b|c.d：依次尝试，取第一个存在的值。
  for (const alternative of reference.split('|')) {
    let value = context;
    let found = true;
    for (const key of alternative.split('.')) {
      if (value == null || !Object.hasOwn(value, key)) { found = false; break; }
      value = value[key];
    }
    if (found) return value;
  }
  throw new MissingData(`缺少测试数据 ${reference}`);
}

function resolve(template, context) {
  if (Array.isArray(template)) return template.map(value => resolve(value, context));
  if (template && typeof template === 'object') {
    return Object.fromEntries(Object.entries(template).map(([key, value]) => [key, resolve(value, context)]));
  }
  if (typeof template !== 'string') return template;
  const whole = /^\{\{([\w.|]+)\}\}$/.exec(template);
  if (whole) return lookup(context, whole[1]);
  return template.replace(/\{\{([\w.|]+)\}\}/g, (_, reference) => String(lookup(context, reference)));
}

function requestPath(contract, context) {
  const path = contract.path.replace(/\{(\w+)\}/g, (_, name) => {
    const value = resolve(contract.params[name], context);
    if (typeof value !== 'string' || !value) throw new Error(`缺少路径参数 ${name}`);
    return encodeURIComponent(value);
  });
  return path + (contract.query ? '?' + new URLSearchParams(resolve(contract.query, context)) : '');
}

async function login(transport, credentials) {
  const response = await transport.request('POST', loginPath, credentials);
  try {
    verify(response, loginContract, models);
  } catch (error) {
    throw new Error(`登录失败（HTTP ${response.status}），已中止：${error.message}`);
  }
  return response;
}

async function confirmSession(transport, userId) {
  const session = await transport.request('GET', '/api/v1/auth/session');
  verify(session, { response: { user: '@user' } }, models);
  if (session.body.user.id !== userId) throw new Error('会话账号与本轮登录账号不一致，已中止');
}

async function loginForWrites(transport, credentials) {
  const response = await login(transport, credentials);
  if (response.body.role.id !== 'admin') throw new Error('完整写入契约需要隔离演示实例的管理员');
  await confirmSession(transport, response.body.user.id);
  return response;
}

async function reset(transport) {
  const response = await transport.request('POST', resetPath, {});
  verify(response, { response: { ok: 'boolean' } }, models);
  if (response.body.ok !== true) throw new Error('演示实例未确认重置成功');
}

async function runModule(id, base, env, write, fail, writes, track = {}) {
  const transport = base ? createHttp(base) : createMock();
  const fixture = {
    todoId: env.CONTRACT_TODO_ID || 'contract-todo',
    enterpriseId: env.CONTRACT_ENTERPRISE_ID || 'E001',
    meetingId: env.CONTRACT_MEETING_ID || 'MT-1112',
    reviewId: env.CONTRACT_REVIEW_ID || 'R-01',
    kbDocId: env.CONTRACT_KB_DOC_ID || 'KB-P4949503',
    kbUrl: env.CONTRACT_KB_URL || 'https://example.com/contract-fixture',
    username: 'jk-contract-' + randomUUID().slice(0, 12),
    kbTitle: '契约测试资料 ' + randomUUID(),
  };
  const context = { fixture };
  if (base) {
    if (!env.CONTRACT_USERNAME || !env.CONTRACT_PASSWORD) {
      // 先报告不可达，即使调用方没提供演示账号。
      await transport.request('GET', '/api/v1/auth/session');
      throw new Error('HTTP 模式需要通过环境变量设置 CONTRACT_USERNAME 和 CONTRACT_PASSWORD');
    }
    context.credentials = { username: env.CONTRACT_USERNAME, password: env.CONTRACT_PASSWORD };
    context.login = await (writes ? loginForWrites : login)(transport, context.credentials);
  } else {
    context.credentials = transport.credentials;
    if (id !== 'platform') await login(transport, context.credentials);
  }

  const { routes, errors } = require('./cases/' + id + '.json');
  let passed = 0;
  let errorPassed = 0;
  let skipped = 0;
  const executed = { routes: 0, errors: 0 };
  async function check(contract, kind) {
    if (!writes && isWrite(contract)) { skipped++; return false; }
    let path;
    let body;
    try {
      body = resolve(contract.body, context);
      path = requestPath(contract, context);
    } catch (error) {
      // 只读模式下依赖被跳过写入生成的数据，同样跳过。
      if (!writes && error instanceof MissingData) { skipped++; return false; }
      executed[kind]++;
      fail(`[${id}] ${contract.method} ${contract.path}：${error.message}`);
      return false;
    }
    executed[kind]++;
    if (base && isWrite(contract)) track.wrote = true;
    try {
      const client = base && contract.error === 'UNAUTHENTICATED' ? createHttp(base) : transport;
      const response = base && path === loginPath ? context.login : await client.request(contract.method, path, body);
      verify(response, contract, models);
      if (path === resetPath && response.body.ok !== true) throw new Error('演示实例未确认重置成功');
      if (contract.save === 'imported' && response.body.docs[0]?.title !== fixture.kbTitle) {
        throw new Error('导入响应缺少本轮唯一标题，跳过资料修改和删除');
      }
      if (contract.sameId && response.body.item.id !== resolve(contract.sameId, context)) {
        throw new Error('响应资料 ID 与本轮创建的资料不一致');
      }
      if (contract.save) context[contract.save] = response.body;
      if (contract.after) {
        // 回读状态，确认写入真的生效。
        const after = contract.after;
        const readBack = await transport.request(after.method, requestPath(after, context), resolve(after.body, context));
        verify(readBack, after, models);
        if (after.sameId && readBack.body.item.id !== resolve(after.sameId, context)) {
          throw new Error('回读到的资料 ID 与本轮创建的资料不一致');
        }
      }
      return true;
    } catch (error) {
      if (error instanceof ConnectionError) throw error;
      fail(`[${id}] ${contract.method} ${contract.path}${contract.error ? ' · ' + contract.error : ''}：${error.message}`);
      return false;
    }
  }
  for (const contract of routes) {
    if (await check(contract, 'routes')) passed++;
  }
  for (const contract of errors) {
    if (await check(contract, 'errors')) errorPassed++;
  }
  const note = skipped ? `（只读模式跳过 ${skipped} 条写入或依赖用例）` : '';
  write(`${id}: ${passed}/${executed.routes}，错误样例 ${errorPassed}/${executed.errors}${note}`);
  return { passed, total: executed.routes, errorPassed, errorTotal: executed.errors, skipped };
}

function parseBase(value) {
  const url = URL.parse(value);
  if (!url || !['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error('--base 需要不含凭据、查询或片段的 HTTP(S) 地址');
  }
  if (url.protocol === 'http:' && !isLoopback(url.hostname)) {
    // 接口规范 §1：远程目标只用 HTTPS，明文 HTTP 仅限本机回环。
    throw new Error(`远程目标必须使用 HTTPS，明文 HTTP 仅允许 localhost/127.0.0.1/::1：${url.host}`);
  }
  return url;
}

async function main(args, env = process.env, write = console.log, fail = console.error) {
  const { values } = parseArgs({
    args, options: {
      base: { type: 'string' }, module: { type: 'string' }, 'allow-writes': { type: 'boolean' },
    },
  });
  if (values.module !== undefined && !modules.includes(values.module)) {
    throw new Error(`未知模块 ${values.module}，可用模块：${modules.join('、')}`);
  }
  let base;
  let writes = true;
  if (values.base !== undefined) {
    const url = parseBase(values.base);
    base = url.href.replace(/\/$/, '');
    writes = Boolean(values['allow-writes']);
    if (writes && env.CONTRACT_RESETTABLE_TARGET !== base) {
      throw new Error(`写入契约只用于独占且可重置的隔离演示实例，请确认 CONTRACT_RESETTABLE_TARGET=${base}`);
    }
  } else if (values['allow-writes']) {
    throw new Error('--allow-writes 只用于 HTTP 模式，mock 模式默认在独立内存状态中执行写入');
  }
  const selected = values.module ? [values.module] : modules;
  const mode = base ? (writes ? 'HTTP（含写入，结束后重置演示数据）' : 'HTTP（只读）') : 'mock';
  write(`契约模式：${mode}；模块：${selected.join('、')}`);
  let passed = 0;
  let total = 0;
  let errorPassed = 0;
  let errorTotal = 0;
  const track = { wrote: false };
  if (base && writes && env.CONTRACT_USERNAME && env.CONTRACT_PASSWORD) {
    const transport = createHttp(base);
    await loginForWrites(transport, { username: env.CONTRACT_USERNAME, password: env.CONTRACT_PASSWORD });
    try {
      await reset(transport);
    } catch (error) {
      throw new Error('演示实例重置预检失败，已中止业务写入：' + error.message);
    }
  }
  try {
    for (const id of selected) {
      const result = await runModule(id, base, env, write, fail, writes, track);
      passed += result.passed;
      total += result.total;
      errorPassed += result.errorPassed;
      errorTotal += result.errorTotal;
    }
  } finally {
    if (track.wrote) {
      // 共享状态统一回滚：用新会话请求演示重置。
      const transport = createHttp(base);
      try {
        await loginForWrites(transport, { username: env.CONTRACT_USERNAME, password: env.CONTRACT_PASSWORD });
        await reset(transport);
        write('已重置演示数据');
      } catch (error) {
        fail('演示数据重置失败，请手动重置目标实例：' + error.message);
        total += 1;
      }
    }
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

module.exports = { main, modules, isWrite, isLoopback };

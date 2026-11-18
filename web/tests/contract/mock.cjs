const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = path.resolve(__dirname, '../..');
// #4 移入 web/ 前用 main 上同一版 mock 作为基线。迁移后直接读取 web/。
const assets = fs.existsSync(path.join(web, 'mock/mock-api.js'))
  ? web
  : path.resolve(web, '../prototype/v4');

function loadScript(context, file) {
  const root = ['config/app.config.js', 'api/http.js'].includes(file) ? web : assets;
  const filename = path.join(root, file);
  vm.runInContext(fs.readFileSync(filename, 'utf8'), context, { filename });
}

function createMock() {
  const storage = new Map();
  const context = vm.createContext({
    console, setTimeout, clearTimeout, URL, URLSearchParams,
    localStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    },
  });
  context.window = context;
  for (const file of [
    'config/app.config.js', 'config/tags.js', 'config/apps.js',
    'config/mock-data.js', 'config/accounts.js',
    'data/real-supplement.js', 'data/real-policies.js', 'data/real-kb.js', 'data/kb-examples.js',
    'mock/mock-api.js', 'mock/auth.js', 'mock/platform-ext.js',
    'mock/policy.js', 'mock/kb.js', 'mock/skills.js', 'mock/computer.js',
    'api/http.js',
  ]) loadScript(context, file);
  context.JKAPI.latency = 0;
  context.JKAPI.state().myTodos.push({
    id: 'contract-todo', task: '核对契约测试', owner: '测试账号',
    due: '2026-12-01', from: '契约测试', app: 'meeting', done: false,
  });
  const { username, password } = context.JK_CONFIG.demoAccounts.find(account => account.username === 'admin');
  return {
    credentials: { username, password },
    async request(method, url, body) {
      try {
        // 在浏览器适配层运行实际 mock handler。它以 JS 异常携带业务错误。
        return { status: 200, body: await context.JKHttp.request(method, url, body) };
      } catch (error) {
        if (!Number.isInteger(error.status) || error.status < 400) throw error;
        return {
          status: error.status,
          body: { error: { code: error.code, message: error.message, details: error.details ?? {} } },
        };
      }
    },
  };
}

module.exports = { assets, createMock, loadScript };

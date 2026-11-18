const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

for (const extension of [false, true]) {
  test(extension ? '政策扩展匹配路由' : '基础匹配路由', async () => {
    const context = vm.createContext({ window: {}, setTimeout, URLSearchParams });
    function load(file) {
      const source = fs.readFileSync(path.join(__dirname, '../../prototype/v4', file), 'utf8');
      vm.runInContext(source, context, { filename: file });
    }
    load('config/app.config.js');
    const config = context.window.JK_CONFIG.modelRouting;
    load('config/mock-data.js');
    load('mock/mock-api.js');
    if (extension) load('mock/policy.js');

    const api = context.window.JKAPI;
    api.latency = 0;
    const { enterprises, models } = api.state();
    const company = enterprises.find(e => e.short === '书香里文化');
    const local = models.find(m => m.id === config.channels.local);
    const cloud = models.find(m => m.id === config.channels.cloud);
    const match = body => api.post('/api/apps/policy/match', body);
    const audit = async () => (await api.get('/api/v1/audit')).items;
    await match({ entId: company.id });
    await api.post('/api/apps/policy/notice', { entId: company.id, itemIds: [] });
    const rows = await audit();
    assert.equal(rows[0][3], '生成一次性告知单 · ' + company.short);
    assert.equal(rows[1][3], '匹配 · ' + company.short);
    for (const [, , , action, model] of rows) {
      if (enterprises.some(e => action.includes(e.short))) {
        assert.equal(model, local.name, action + ' 实际记录 ' + model);
      }
    }
    await match({ profile: {} });
    assert.equal((await audit())[0][4], cloud.name);
    config.defaultChannel = 'local';
    await match({ profile: {} });
    assert.equal((await audit())[0][4], local.name);
    const other = models.find(m => m.kind === 'cloud' && m.id !== cloud.id);
    await api.put('/api/v1/models/current', { model: other.id });
    await match({ profile: {} });
    assert.equal((await audit())[0][4], other.name);
    config.channels.local = models.find(m => m.kind === 'local' && m.id !== local.id).id;
    await match({ entId: company.id });
    const reply = await api.post('/api/v1/ai/chat', { messages: [{ content: '书香里文化能申报哪些政策' }] });
    assert.equal((await audit())[0][4], reply.model);
    assert.equal(reply.model, models.find(m => m.id === config.channels.local).name);
    config.channels.local = cloud.id;
    await assert.rejects(match({ entId: company.id }), { code: 'MODEL_UNAVAILABLE' });
  });
}

test('刷新已有会话时读取当前配置并保留管理员启停状态', async () => {
  let saved;
  const context = vm.createContext({
    window: {}, setTimeout, URLSearchParams,
    localStorage: { getItem: () => saved, setItem: (_, value) => { saved = value; } },
  });
  function load(file) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../prototype/v4', file), 'utf8'), context);
  }
  load('config/app.config.js');
  load('config/mock-data.js');
  load('mock/mock-api.js');
  const config = context.window.JK_CONFIG.modelRouting;
  const api = context.window.JKAPI;
  api.latency = 0;
  await api.patch('/api/v1/models/' + config.channels.cloud, { enabled: false });
  const local = config.models.find(m => m.id === config.channels.local);
  local.name = '内网测试模型';
  load('config/mock-data.js');
  load('mock/mock-api.js');
  const fresh = context.window.JKAPI;
  fresh.latency = 0;
  const company = fresh.state().enterprises[0];
  await fresh.post('/api/apps/policy/match', { entId: company.id });
  assert.equal(fresh.state().audit[0][4], local.name);
  await assert.rejects(fresh.post('/api/apps/policy/match', { profile: {} }), { code: 'MODEL_UNAVAILABLE' });
});

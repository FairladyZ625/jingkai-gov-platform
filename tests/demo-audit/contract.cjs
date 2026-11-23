const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

for (const extension of [false, true]) {
  test(extension ? '政策扩展匹配路由' : '基础匹配路由', async () => {
    const context = vm.createContext({ window: {}, setTimeout, URLSearchParams });
    function load(file) {
      const source = fs.readFileSync(path.join(__dirname, '../../web', file), 'utf8');
      vm.runInContext(source, context, { filename: file });
    }
    load('config/app.config.js');
    const config = context.window.JK_CONFIG.modelRouting;
    load('config/mock-data.js');
    load('config/accounts.js');
    load('data/real-policies.js');
    load('mock/mock-api.js');
    load('mock/computer.js');
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
    // 固定脚本启动、步骤回报和人工确认均无模型调用。
    const runs = '/api/apps/computer/runs';
    const { item: run } = await api.post(runs, { task: 'apply', ent: company.id });
    await api.patch(runs + '/' + run.id, { log: '打开统一身份认证 ✓' });
    await api.post(runs + '/' + run.id + '/confirm', { decision: 'approve' });
    const computerRows = (await audit()).slice(0, 3);
    assert.deepEqual(Array.from(computerRows, r => r[3]), [
      run.title + ' · ' + api.ext.me().name + ' 人工确认提交',
      run.title + ' · 打开统一身份认证 ✓',
      '开始任务 · ' + run.title + '（' + run.system.name + '）',
    ]);
    for (const row of computerRows) assert.equal(row[4], '—', row[3]);
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
    await api.put('/api/v1/models/current', { model: local.id });
    await api.patch('/api/v1/models/' + local.id, { enabled: false });
    const failed = { status: 503, code: 'MODEL_UNAVAILABLE' };
    const before = JSON.stringify(api.state());
    const visit = () => api.post('/api/apps/enterprise/companies/' + company.id + '/visits', { notes: '员工有35人' });
    await assert.rejects(match({ entId: company.id }), failed);
    await assert.rejects(api.post('/api/apps/policy/notice', { entId: company.id, itemIds: [] }), failed);
    await assert.rejects(visit(), failed);
    assert.equal(JSON.stringify(api.state()), before);
    await api.patch('/api/v1/models/' + local.id, { enabled: true });
    await visit();
    assert.equal(api.state().visits.length, JSON.parse(before).visits.length + 1);
    await api.put('/api/v1/models/current', { model: 'auto' });
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
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../web', file), 'utf8'), context);
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
  const cloudBefore = config.channels.cloud;
  config.channels.cloud = config.taskModels.writing;
  const legacy = JSON.parse(saved);
  delete legacy.legacyAudit;
  const oldSeed = legacy.audit.find(row => row[3] === '匹配 · 书香里文化');
  oldSeed[4] = '旧云模型';
  legacy.audit.unshift(['旧演示', ...oldSeed.slice(1)]);
  saved = JSON.stringify(legacy);
  load('config/mock-data.js');
  load('mock/mock-api.js');
  const fresh = context.window.JKAPI;
  fresh.latency = 0;
  const company = fresh.state().enterprises[0];
  const state = fresh.state();
  assert.deepEqual(JSON.parse(JSON.stringify(state.legacyAudit)), legacy.audit);
  assert.equal(state.audit.find(row => row[3] === oldSeed[3])[4], local.name);
  assert.ok(!state.audit.some(row => row[0] === '旧演示'));
  const names = state.usage.byModel.map(([name]) => name);
  assert.equal(new Set(names).size, names.length);
  const { job } = await fresh.post('/api/apps/meeting/meetings/' + state.meetings[0].id + '/transcribe', {});
  assert.equal(state.audit[0][4], 'SenseVoice（本地）');
  assert.ok(job.steps[1].includes(state.audit[0][4]));
  await fresh.post('/api/apps/policy/match', { entId: company.id });
  assert.equal(fresh.state().audit[0][4], local.name);
  config.channels.cloud = cloudBefore;
  await assert.rejects(fresh.post('/api/apps/policy/match', { profile: {} }), { code: 'MODEL_UNAVAILABLE' });
});

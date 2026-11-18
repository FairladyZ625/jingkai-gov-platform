const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../../..');
const source = file => fs.readFileSync(path.join(root, 'prototype/v4', file), 'utf8');
const seed = file => JSON.parse(fs.readFileSync(path.join(root, 'data/seed', file + '.json')));
const ctx = vm.createContext({ setTimeout, URLSearchParams, JK: { registry: {} }, localStorage: { getItem() {}, setItem() {} } });
ctx.window = ctx;
function run(file) {
  let code = source(file);
  if (file === 'mock/kb.js' && process.argv.includes('--positive-control')) {
    assert.ok(code.includes('docs: vis.length'));
    code = code.replace('docs: vis.length', 'docs: 18');
  }
  vm.runInContext(code, ctx, { filename: file });
}

async function check() {
  run('config/mock-data.js');
  const demo = seed('demo');
  const plain = x => JSON.parse(JSON.stringify(x));
  const generated = plain(ctx.JK_DATA);
  const real = seed('real-policies');
  const examples = seed('policy-examples');
  assert.deepEqual(generated, {
    ...demo,
    policyDocs: [...examples.policyDocs, ...real.policyDocs],
    policies: [...examples.policies, ...real.policies],
    realNotices: real.notices,
    realNews: real.news,
    departmentsReal: real.departments,
    districtFacts: real.facts,
  });
  assert.deepEqual(plain(ctx.JK_REAL), real);
  assert.deepEqual(plain(ctx.JK_REAL_KB), seed('real-kb'));
  assert.deepEqual(plain(ctx.JK_KB_EXAMPLES), seed('kb-examples'));
  const rows = generated.enterprises;
  assert.equal(rows.length, 24);
  assert.equal(new Set(rows.map(e => e.short.slice(0, 3))).size, rows.length);
  for (const [i, e] of rows.entries()) {
    assert.equal(e.id, 'E' + String(i + 1).padStart(3, '0'));
    assert.equal(e.example, true);
    assert.equal(e.creditCode, 'DEMO-' + e.id);
  }
  const ownedCopy = ['config/mock-data.js', 'config/app.config.js', 'config/demo-script.js', 'config/sample-files.js',
    'apps/enterprise/app.js', 'apps/enterprise/config.js', 'apps/computer/app.js', 'apps/meeting/config.js'];
  const copy = [JSON.stringify(demo), ...ownedCopy.map(source)].join('\n');
  const mapping = fs.readFileSync(path.join(__dirname, '企业名称映射.md'), 'utf8');
  for (const line of mapping.split('\n').filter(line => /^\| E\d{3} /.test(line))) {
    const [, id, oldShort, newShort, oldName, newName] = line.split('|').map(cell => cell.trim());
    const current = rows.find(e => e.id === id);
    assert.equal(current.short, newShort);
    assert.equal(current.name, newName);
    if (oldShort !== newShort) assert.ok(!copy.includes(oldShort), '旧简称残留：' + oldShort);
    if (oldName !== newName) assert.ok(!copy.includes(oldName), '旧全称残留：' + oldName);
  }
  console.log('生成文件与五份种子往返一致，对话样例、演示脚本与 starters 无旧企业名。');
  for (const f of ['config/app.config.js', 'config/apps.js', 'config/accounts.js', 'mock/mock-api.js', 'mock/kb.js', 'assets/operator.js', 'config/demo-script.js', 'config/sample-files.js']) run(f);
  for (const f of ['config/tags.js', 'apps/enterprise/config.js', 'apps/meeting/config.js']) run(f);
  assert.ok(ctx.JK_CONFIG.homeSuggestions.some(s => s.text.includes(rows[1].short)));
  const participants = ctx.JK_APPCFG.meeting.sampleUpload.participants;
  assert.ok(participants.includes(rows[1].short) && participants.includes(rows[4].short));
  const api = ctx.JKAPI;
  api.latency = 0;
  ctx.JKHttp = api;
  await ctx.JKOp.loadDict();
  for (const e of rows) {
    for (const n of [e.name, e.short]) assert.equal(ctx.JKOp.understand('查一下' + n).slots.ent.id, e.id, n);
  }
  assert.equal(ctx.JK_DEMO_SCRIPT.length, 12);
  for (const step of ctx.JK_DEMO_SCRIPT.flatMap(s => s.steps)) {
    if (step.file) assert.ok(ctx.JK_SAMPLE_FILES.some(f => f.id === step.file));
    if (step.appDemo) assert.ok(ctx.JK_APP_LIST.some(a => a.id === step.appDemo));
  }
  assert.ok(ctx.JK_DEMO_SCRIPT.some(s => s.steps.some(step => step.say === '查一下' + rows[1].short)));
  assert.ok(ctx.JK_SAMPLE_FILES.find(f => f.id === 'ent-xinghe').text.includes(rows[1].name));
  assert.ok(ctx.JK_SAMPLE_FILES.find(f => f.id === 'rec-1117').name.includes('示例'));
  assert.ok(demo.meetings.every(m => m.title.includes('示例')));
  for (const role of ['member', 'leader', 'admin', 'partner']) {
    const user = api.state().users.find(u => u.role === role);
    api.state().me = user.id;
    await checkStats(role);
  }
  api.state().me = api.state().users.find(u => u.role === 'member').id;
  await api.post('/api/v1/kb/import', { text: '用户补充独立样本甲', title: '导入核验甲', space: 'rules' });
  const st = await checkStats('经办人员导入后');
  assert.equal(st.otherSources['粘贴'], 1);

  async function checkStats(label) {
    const get = suffix => api.get('/api/v1/kb/' + suffix);
    const [st, list, spaces] = await Promise.all([get('stats'), get('docs?limit=1000'), get('spaces')]);
    assert.equal(st.docs, list.hits.length, '知识库总数必须等于角色可见的列表条数');
    assert.equal(st.real, list.hits.filter(d => d.real).length);
    assert.equal(st.example, list.hits.filter(d => d.example).length);
    assert.equal(st.docs, st.real + st.example + Object.values(st.otherSources).reduce((a,b) => a+b, 0));
    const visible = spaces.items.filter(s => s.visible);
    assert.equal(visible.reduce((sum,s) => sum+s.count, 0), st.docs);
    for (const s of spaces.items) assert.equal(s.count, list.hits.filter(d => d.space === s.id).length);
    if (label === 'partner') assert.ok(!visible.some(s => s.id === 'enterprise'));
    else {
      for (const [id,name] of [['template','申报通知'], ['rules','机构职责']]) assert.equal(visible.find(s => s.id === id).name, name);
      const minutes = list.hits.filter(d => d.space === 'minutes');
      assert.ok(minutes.length && minutes.every(d => d.example && d.title.includes('示例')));
      const item = (await get('docs/' + minutes[0].id)).item;
      assert.ok(item.text.includes('示例') && item.text.includes('参会：'));
    }
    console.log(label, st.docs, '份；真实', st.real, '示例', st.example, '其他来源', JSON.stringify(st.otherSources), '可见空间', visible.length);
    return st;
  }
}
check().catch(err => { console.error(err); process.exitCode = 1; });

const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const prototype = path.join(__dirname, '../../prototype/v4');
const documentApi = '/api/apps/document';

function mock() {
  const context = vm.createContext({
    window: {},
    localStorage: { getItem: () => null, setItem() {} },
    setTimeout,
  });
  function load(file) {
    vm.runInContext(readFileSync(path.join(prototype, file), 'utf8'), context, { filename: file });
  }
  for (const file of ['config/mock-data.js', 'config/accounts.js', 'config/demo-script.js',
    'config/sample-files.js', 'mock/mock-api.js']) {
    load(file);
  }
  context.window.JKAPI.latency = 0;
  return { ...context.window, load };
}

async function draft(api, overrides = {}) {
  const { items } = await api.get(documentApi + '/templates');
  const template = items.find(({ id }) => id === 'T06');
  const inputs = Object.fromEntries(template.inputs.map(([key, , value]) => [key, value]));
  const { item } = await api.post(documentApi + '/drafts', { templateId: template.id, inputs: { ...inputs, ...overrides } });
  return { inputs, url: documentApi + '/drafts/' + item.id, content: item.versions[0].content };
}

async function dateIssues(api, url) {
  const { issues } = await api.post(url + '/check');
  return issues.filter(({ kind }) => kind === '日期先后');
}

test('第 5 段 T06 默认截止日与演示附件一致，且原截止日和落款均早于新截止日', async () => {
  const { JKAPI, JK_DEMO_SCRIPT, JK_SAMPLE_FILES } = mock();
  const segment = JK_DEMO_SCRIPT[4];
  assert.equal(segment.title, '公文协作');
  const attachment = JK_SAMPLE_FILES.find(({ id }) => segment.steps.some(({ file }) => file === id));
  const attachmentEnd = attachment.text.match(/延长至(\d{4}-\d{2}-\d{2})/)[1];
  const { inputs, url, content } = await draft(JKAPI);
  assert.equal(attachmentEnd, '2026-12-15');
  assert.equal(inputs.newEnd, attachmentEnd, 'T06 新截止日应与第 5 段附件一致');
  assert.equal(inputs.oldEnd, '2026-11-30');
  assert.ok(inputs.oldEnd < inputs.newEnd);
  assert.equal(content.date, '2026年11月17日');
  assert.match(content.paragraphs[0], /由2026年11月30日延长至2026年12月15日/);
  assert.equal((await dateIssues(JKAPI, url)).length, 0);
});

const cases = [
  ['早于原截止日', '2026-11-30', '2026年11月29日', /新截止日须晚于原截止日/],
  ['等于原截止日', '2026-11-30', '2026年11月30日', /新截止日须晚于原截止日/],
  ['早于发文日期', '2026-11-01', '2026年11月16日', /新截止日须晚于发文日期/],
  ['等于发文日期（ISO）', '2026-11-01', '2026-11-17', /新截止日须晚于发文日期/],
  ['同时早于两个日期', '2026-11-30', '2026年11月6日', /原截止日.*发文日期/],
];

for (const [label, oldEnd, newDate, reason] of cases) {
  test(`手改正文后核查新截止日${label}，改正后日期建议消失`, async () => {
    const { JKAPI } = mock();
    const { url, content } = await draft(JKAPI, { oldEnd, newEnd: '2026-12-15' });
    const paragraphs = content.paragraphs.with(0, content.paragraphs[0].replace('2026年12月15日', newDate));
    await JKAPI.put(url, { content: { ...content, paragraphs } });
    const issues = await dateIssues(JKAPI, url);
    assert.equal(issues.length, 1);
    assert.equal(issues[0].level, 'warn');
    assert.equal(issues[0].para, 0);
    assert.match(issues[0].text, reason);

    await JKAPI.put(url, { content });
    assert.equal((await dateIssues(JKAPI, url)).length, 0);
  });
}

test('旧检索路径返回的 F008 将旧截止日明确标为往期', async () => {
  const { JKAPI } = mock();
  const { hits } = await JKAPI.post('/api/v1/kb/search', { q: '数据券 延期' });
  const notice = hits.find(({ fileId }) => fileId === 'F008');
  assert.ok(notice);
  assert.match(notice.name, /往期/);
  assert.match(notice.snippet, /往期.*2026年11月6日/);
});

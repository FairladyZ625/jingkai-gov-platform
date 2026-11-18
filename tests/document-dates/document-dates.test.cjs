const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const prototype = path.join(__dirname, '../../prototype/v4');
const documentApi = '/api/apps/document';

function mock(storage = new Map()) {
  const context = vm.createContext({
    window: {},
    localStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
    },
    setTimeout,
  });
  function load(file) {
    vm.runInContext(readFileSync(path.join(prototype, file), 'utf8'), context, { filename: file });
  }
  for (const file of ['config/app.config.js', 'config/mock-data.js', 'config/accounts.js',
    'config/demo-script.js', 'config/sample-files.js']) {
    load(file);
  }
  context.window.JK_STATE_KEY = context.window.JK_CONFIG.stateKey;
  load('mock/mock-api.js');
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

async function conversationHits(api) {
  const { item } = await api.post('/api/v1/conversations', {});
  const { reply } = await api.post('/api/v1/conversations/' + item.id + '/messages', {
    app: 'kb',
    text: '数据券 延期',
  });
  return reply.cards.find(({ type }) => type === 'kb-hits').hits;
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

test('加载旧版演示状态后使用最新示例和往期标注，并保留已有公文版本', async () => {
  const storage = new Map();
  const { JKAPI: oldApi, JK_STATE_KEY } = mock(storage);
  const state = oldApi.state();
  const template = state.docTemplates.find(({ id }) => id === 'T06');
  const legacyDefaults = {
    orig: '关于开展 2026 年数据券申报工作的通知',
    oldEnd: '2026-11-02',
    newEnd: '2026-11-06',
  };
  for (const input of template.inputs) {
    if (Object.hasOwn(legacyDefaults, input[0])) input[2] = legacyDefaults[input[0]];
  }
  const legacyNotice = state.files.find(({ id }) => id === 'F008');
  legacyNotice.name = '关于数据券申报延期的通知.pdf';
  legacyNotice.snippet = '延长至2026年11月6日。';
  const saved = await draft(oldApi);
  const edited = { ...saved.content, title: '旧版手改标题' };
  const { item: previousDraft } = await oldApi.put(saved.url, { content: edited });
  assert.equal(previousDraft.versions.length, 2);
  assert.match(saved.content.paragraphs[0], /由2026年11月2日延长至2026年11月6日/);
  assert.ok(storage.has(JK_STATE_KEY));

  const { JKAPI } = mock(storage);
  const { item: loadedDraft } = await JKAPI.get(saved.url);
  assert.equal(JSON.stringify(loadedDraft), JSON.stringify(previousDraft));
  const fresh = await draft(JKAPI);
  assert.match(fresh.content.paragraphs[0], /由2026年11月30日延长至2026年12月15日/);
  assert.match(fresh.inputs.orig, /后续批次/);
  const notice = (await conversationHits(JKAPI)).find(({ fileId }) => fileId === 'F008');
  assert.match(notice.name, /往期/);
  assert.match(notice.snippet, /往期.*2026年11月6日/);
});

const cases = [
  ['早于原截止日', '2026-11-30', '2026年11月29日', /新截止日须晚于原截止日/],
  ['等于原截止日', '2026-11-30', '2026年11月30日', /新截止日须晚于原截止日/],
  ['早于发文日期', '2026-11-01', '2026年11月16日', /新截止日须晚于发文日期/],
  ['等于发文日期（ISO）', '2026-11-01', '2026-11-17', /新截止日须晚于发文日期/],
  ['同时早于两个日期', '2026-11-30', '2026年11月6日', /原截止日.*发文日期/],
  ['早于原截止日（中文日期有空白）', '2026-11-30', '2026 年 11 月 29 日', /新截止日须晚于原截止日/],
  ['早于带时分的原截止日', '2026年11月30日17:00', '2026年11月29日', /新截止日须晚于原截止日/],
  ['早于带空格时分的原截止日', '2026年11月30日 17 时 00 分', '2026年11月29日', /新截止日须晚于原截止日/],
  ['早于带北京时间注记的原截止日', '2026年11月30日17:00（北京时间）', '2026年11月29日', /新截止日须晚于原截止日/],
  ['与原截止日同日但时分不同', '2026-11-30T09:00', '2026年11月30日 17：00', /新截止日须晚于原截止日/],
  ['早于发文日期（中文日期带时分）', '2026-11-01', '2026年11月16日17时30分', /新截止日须晚于发文日期/],
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

test('会话检索区分 F007 原通知、F008 往期延期和 T06 的后续批次', async () => {
  const { JKAPI } = mock();
  const hits = await conversationHits(JKAPI);
  const original = hits.find(({ fileId }) => fileId === 'F007');
  const notice = hits.find(({ fileId }) => fileId === 'F008');
  const { inputs, content } = await draft(JKAPI);
  assert.match(original.name, /关于开展2026年数据券申报工作的通知/);
  assert.match(original.snippet, /2026年10月12日至11月2日/);
  assert.match(inputs.orig, /后续批次/);
  assert.ok(content.paragraphs[0].includes(`《${inputs.orig}》`));
  assert.equal(inputs.oldEnd, '2026-11-30');
  assert.match(notice.name, /往期/);
  assert.match(notice.snippet, /往期.*2026年11月6日/);
});

test('首次加载的 DOC-1108 保留往期批次，新建 T06 使用后续批次', async () => {
  const { JKAPI } = mock();
  const url = documentApi + '/drafts/DOC-1108';
  const { item } = await JKAPI.get(url);
  const { content } = item.versions.at(-1);
  const previousBatch = /《关于开展 2026 年数据券申报工作的通知》/;
  const previousDates = /由2026年11月2日延长至2026年11月6日/;
  assert.equal(item.status, '已定稿');
  assert.equal(content.docNo, '');
  assert.match(content.paragraphs[0], previousBatch);
  assert.match(content.paragraphs[0], previousDates);
  const exported = await JKAPI.get(url + '/export');
  assert.equal(exported.final, true);
  assert.match(exported.html, previousBatch);
  assert.match(exported.html, previousDates);

  const fresh = await draft(JKAPI);
  assert.match(fresh.content.paragraphs[0], /《关于开展 2026 年数据券后续批次申报工作的通知》/);
  assert.match(fresh.content.paragraphs[0], /由2026年11月30日延长至2026年12月15日/);
});

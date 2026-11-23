const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const drafts = '/api/apps/document/drafts';
const historical = drafts + '/DOC-1108';

function boot(stored = null) {
  const localStorage = { getItem: () => stored, setItem: (_, value) => { stored = value; } };
  const context = vm.createContext({ window: {}, localStorage, setTimeout });
  for (const file of ['config/app.config.js', 'config/mock-data.js', 'config/accounts.js', 'mock/mock-api.js']) {
    vm.runInContext(readFileSync(path.join(__dirname, '../../web', file), 'utf8'), context);
  }
  const api = context.window.JKAPI;
  api.latency = 0;
  return api;
}

async function checkDates(api, url) {
  const { issues } = await api.post(url + '/check');
  return issues.filter(issue => issue.kind === '日期先后');
}

async function checkHistorical(api) {
  const { item } = await api.get(historical);
  assert.equal(item.versions[0].content.date, '2026年11月3日');
  assert.equal((await checkDates(api, historical)).length, 0);
}

test('往期定稿沿用 11 月 3 日落款，核查无日期先后建议', async () => {
  await checkHistorical(boot());
});

test('重开旧缓存时修正原始种子的落款，保留自定义日期', async () => {
  const state = boot().state();
  const content = state.drafts['DOC-1108'].versions[0].content;
  content.date = '2026年11月17日';
  await checkHistorical(boot(JSON.stringify(state)));
  content.date = '2026年11月4日';
  const { item } = await boot(JSON.stringify(state)).get(historical);
  assert.equal(item.versions[0].content.date, content.date);
});

for (const modifier of ['原定的', '原定于']) {
  test('原截止日前有「' + modifier + '」时提示倒挂，延至次日后建议消失', async () => {
    const api = boot();
    const { item } = await api.post(drafts, { templateId: 'T06', inputs: {} });
    const url = drafts + '/' + item.id;
    const content = item.versions[0].content;
    for (const [end, inverted] of [['2026年11月29日', true], ['2026年12月1日', false]]) {
      const paragraphs = ['现将申报截止时间由' + modifier + '2026年11月30日延长至' + end + '。'];
      await api.put(url, { content: { ...content, paragraphs } });
      const issues = await checkDates(api, url);
      assert.equal(issues.length, inverted ? 1 : 0);
      if (inverted) {
        assert.equal(issues[0].level, 'warn');
        assert.match(issues[0].text, /原截止日/);
      }
    }
  });
}

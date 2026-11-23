// 直接跑 file:// 原型所用的模拟服务；无 DOM、无网络，不冒充浏览器验收。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const read = name => readFileSync(new URL('../../web/' + name, import.meta.url), 'utf8');
const state = {}, win = { JK_APPCFG: {} }, routes = new Map();
let role = 'member';
let nextId = 0;
win.JKAPI = { ext: { state: () => state, me: () => ({role}), roleOf: () => ({mask:role === 'partner'}),
              first(method, path, fn) { routes.set(method + ' ' + path, fn); },
              can: () => role !== 'partner', nid: prefix => prefix + '-' + (++nextId), now: () => '2026-11-18', audit() {} },
              onLoad: fn => fn() };
const ctx = vm.createContext({ window: win });
for (const file of ['apps/kb/config.js', 'data/real-kb.js', 'mock/kb.js']) vm.runInContext(read(file), ctx);
const kb = win.JKKB;
const questions = win.JK_APPCFG.kb.suggestions;
for (const [i, q] of questions.entries()) {
  const answer = kb.ask(q);
  assert.ok(answer.citations.length, q);
  assert.match(answer.answer, [/100万元/, /奖励/, /11月20日/, /负责/][i]);
  for (const c of answer.citations) assert.ok(kb.docs().find(d => d.id === c.id).text.includes(c.snippet));
}
const follow = '请列出这项数据券政策的申报期限、适用对象和需要审签的材料；如果原文没有写，请明确说明';
const ref = kb.ask(questions[0]).citations[0];
const scope = ref.id + '@v1';
const answer = kb.ask(follow, {scope});
for (const name of ['申报期限', '适用对象', '审签材料']) assert.ok(answer.answer.includes(name + '：'));
assert.ok(answer.citations.every(c => c.citationId === scope));
assert.equal(kb.ask(follow, {scope: ref.id + '@v99'}).notFound, true);
const rules = kb.ask(questions[3]).citations.find(c => c.space === 'rules');
assert.ok(rules);
role = 'partner';
assert.equal(kb.ask(follow, {scope:rules.id + '@v1'}).notFound, true);
role = 'member';
const base = {id:'A', title:'山谷计划服务指南', space:'policy', text:'山谷计划每季度开放登记。', url:'https://example.invalid/a'};
state.kb.added.push(base, {...base, id:'B'}, {...base, id:'C', text:'山谷计划的资料归档期限为十日。'},
                   {...base, id:'D', space:'enterprise', url:'https://example.invalid/d'});
kb.reload();
const rows = () => kb.search('山谷计划', {limit:30}).hits.filter(h => h.title === base.title);
assert.equal(rows().length, 3, '相同来源和原文去重，同题不同条款和不同来源保留');
role = 'partner';
assert.equal(rows().length, 2); assert.ok(!rows().some(h => h.id === 'D'));
role = 'member';
const parking = {id:'park',title:'虚拟园区停车管理通知',space:'rules',text:'请在服务台登记。园区停车每次最长2小时，到时应驶离。'};
const loan = {id:'loan',title:'星湖仪器借用细则',space:'rules',text:'维护人员检修最长9小时。星湖仪器借用每次不得超过四十五分钟，不得续借。'};
state.kb.added.push(parking, loan); kb.reload();
for (const [q, expected] of [['群雁计划上市辅导补贴最高多少？','200万元'], ['园区停车最长能停多久？','最长2小时'],
  ['星湖仪器借用最长能用多久？','不得超过四十五分钟，不得续借']]) {
  const a = kb.ask(q); console.log(q, '目标引文', a.citations.some(c=>c.snippet.includes(expected)));
  assert.ok(a.citations.some(c=>c.snippet.includes(expected)));
}
assert.ok(kb.ask('星湖仪器借用最短需要多久？').notFound);
assert.ok(kb.ask('星湖仪器夜间借用最多几小时？').notFound);
assert.match(kb.ask('星湖仪器借用是否可以续借？').answer,/不得续借/);
assert.match(kb.ask('星湖仪器借用最长能用多久，押金是多少？').answer,/押金：当前引用原文未找到/);
assert.match(kb.ask('星湖仪器借用押金是多少，最长能用多久？').answer,/不得超过四十五分钟/);
role = 'partner'; assert.ok(kb.ask('星湖仪器借用最长能用多久？').notFound);
role = 'member';
const raw = readFileSync(new URL('../fixtures/kb_visitor_parking.txt', import.meta.url), 'utf8');
const [title, visitorQuote] = raw.split('\n');
const {docs:[visitor]} = routes.get('POST /api/v1/kb/import')({title,text:raw,space:'rules'});
const costQ = '群雁计划对境内上市辅导费用怎么补贴？';
const visitorQ = '鹿桥园区普通访客可以免费停车多久？';
const exactCost = kb.docs().find(d=>d.id==='KB-P4280732').text.split(/(?<=。)|\n/)
  .map(s=>s.trim()).find(s=>s.includes('境内上市辅导') && s.includes('200万元'));
assert.ok(exactCost);
const missingQuotes = [];
for (const [q, id, quote] of [[costQ,'KB-P4280732',exactCost],[visitorQ,visitor.id,visitorQuote]]) {
  assert.ok(kb.search(q).hits.some(h=>h.id===id), q+' 应召回原文');
  const result = kb.ask(q);
  if (!result.citations.some(c=>c.id===id && c.snippet===quote) ||
      !result.citations.every(c=>c.id===id && kb.docs().find(d=>d.id===id).text.includes(c.snippet))) missingQuotes.push(q);
}
assert.deepEqual(missingQuotes, [], '已召回，但没有对应的逐字引文');
for (const q of [costQ.replace('境内上市辅导','境外上市辅导'), costQ.replace('境内上市辅导','境内上市辅导差旅'),
                 visitorQ.replace('普通访客','驻场车辆'), '鹿桥园区普通访客停车缴费金额是多少？']) {
  const result = kb.ask(q);
  assert.ok(result.notFound && !result.citations.length,q);
}
const {docs:[decoy]} = routes.get('POST /api/v1/kb/import')({title:title+'（对照）',space:'rules',
  text:'鹿桥园区普通访客须登记，驻场车辆免费停车时长为两小时。\n鹿桥园区普通访客不再免费停车，停车时长为三天。'});
assert.ok(kb.ask(visitorQ,{scope:decoy.id+'@v'+decoy.version}).notFound);
role = 'partner';
assert.ok(kb.ask(visitorQ).notFound);
console.log('离线模拟服务：4 条界面示例、逐字引文、追问版本与空间隔离通过');

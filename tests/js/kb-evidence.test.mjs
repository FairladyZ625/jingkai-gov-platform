// 直接跑 file:// 原型所用的模拟服务；无 DOM、无网络，不冒充浏览器验收。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const read = name => readFileSync(new URL('../../prototype/v4/' + name, import.meta.url), 'utf8');
const state = {}, win = { JK_APPCFG: {} };
let role = 'member';
win.JKAPI = { ext: { state: () => state, me: () => ({role}), roleOf: () => ({mask:role === 'partner'}), first() {} },
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
console.log('离线模拟服务：4 条界面示例、逐字引文、追问版本与空间隔离通过');

// 运行真实 shell 的收件箱刷新；不挂载页面、不启动浏览器，响应由测试显式放行。
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = readFileSync(new URL('../../web/assets/shell.js', import.meta.url), 'utf8');
function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return {promise, resolve};
}
function fixture() {
  const calls = [];
  const context = {document: {addEventListener() {}}, JK: {$: () => null, bus: {on() {}}},
    JKOp: {hooks: {}}, JKApi: {
      reviews: {list: () => { const d = deferred(); calls.push(d); return d.promise; }},
      todos: {list: async () => ({items: []})},
    }};
  context.window = context;
  vm.runInNewContext(source, context);
  const shell = context.JKShell;
  shell.S.me = {id: 'fixture-reviewer'};
  shell.S.grants = {document: ['view', 'approve']};
  const list = id => ({items: [{id, status: 'pending', app: 'document', type: 'review', approver: true},
    {id: '不能办理', status: 'pending', app: 'document', type: 'review', approver: false}]});
  return {calls, shell, list};
}
test('旧收件箱响应晚到不能覆盖新待办或恢复无权办理的行', async () => {
  const {calls, shell, list} = fixture();
  const a = shell.refreshInbox(), b = shell.refreshInbox();
  calls[1].resolve(list('当前待办')); await b;
  calls[0].resolve(list('旧快照')); await a;
  assert.deepEqual(Array.from(shell.S.inbox, row => row.id), ['当前待办']);
});
test('打开时的刷新若被取代，调用方等待当前快照后才继续', async () => {
  const {calls, shell, list} = fixture();
  let ready = false;
  const opening = shell.refreshInbox().then(() => { ready = true; });
  const latest = shell.refreshInbox();
  calls[0].resolve(list('旧快照')); await new Promise(resolve => setImmediate(resolve));
  assert.equal(ready, false);
  calls[1].resolve(list('当前待办')); await Promise.all([latest, opening]);
  assert.deepEqual(Array.from(shell.S.inbox, row => row.id), ['当前待办']);
});
test('换号前已发出的刷新不会写入新会话', async () => {
  const {calls, shell, list} = fixture();
  const old = shell.refreshInbox();
  shell.S.me = {id: 'fixture-next'};
  calls[0].resolve(list('上个会话')); await old;
  assert.equal(shell.S.inbox.length, 0);
});

for (const [role, grants, expected] of [
  ['leader', {'*': ['view', 'operate', 'approve']}, ['S1', 'M1']],
  ['member', {'*': ['view', 'operate']}, ['E1', 'M1']],
  ['partner', {'*': ['view']}, []],
]) {
  test(`共享收件箱刷新保留非公文角色过滤：${role}`, async () => {
    const {calls, shell} = fixture();
    shell.S.me.role = role;
    shell.S.grants = grants;
    const loading = shell.refreshInbox();
    calls[0].resolve({items: [
      {id: 'S1', app: 'skills', type: 'skill', approver: true, status: 'pending'},
      {id: 'E1', app: 'enterprise', type: 'proposal', approver: false, status: 'pending'},
      {id: 'M1', app: 'meeting', type: 'todo', approver: false, status: 'pending'},
      {id: 'S2', app: 'skills', type: 'skill', approver: true, status: 'done'},
    ]});
    await loading;
    assert.deepEqual(Array.from(shell.S.inbox, row => row.id), expected);
  });
}

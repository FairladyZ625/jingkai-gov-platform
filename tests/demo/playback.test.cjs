const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../web/assets/demo.js'), 'utf8');

function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { promise, resolve };
}
// 真实演示引擎 + 可手动推进的单调时钟；壳的异步操作由夹具显式完成。
function player(script, shell = {}, elements = {}) {
  let now = 0, next = 0, bar;
  const timers = new Map(), sent = [];
  const timeout = (cb, ms) => { timers.set(++next, { at: now + ms, cb }); return next; };
  const flush = () => new Promise(resolve => setImmediate(resolve));
  async function advance(ms) {
    await flush();
    const end = now + ms;
    for (;;) {
      const first = [...timers].sort((a, b) => a[1].at - b[1].at)[0];
      if (!first || first[1].at > end) break;
      timers.delete(first[0]); now = first[1].at; first[1].cb(); await flush();
    }
    now = end;
  }
  const scope = { AbortController, performance: { now: () => now }, setTimeout: timeout, clearTimeout: id => timers.delete(id),
    document: { body: { classList: { add() {}, remove() {} }, appendChild(el) { bar = el; } },
      querySelectorAll: () => [], querySelector: sel => elements[sel] || null },
    JK: { h: () => ({ querySelector: () => ({}), remove() { bar = null; } }), esc: String, icon: () => '',
      sleep: ms => new Promise(resolve => timeout(resolve, ms)) },
    JKShell: { canPresentDemo: () => true, theme: () => 'light', setTheme() {}, S: { me: { username: 'original' } },
      send(text) { sent.push(text); }, ...shell },
    JK_CONFIG: { demoSpeed: 8, demoReadMs: 2400 }, JKOp: {}, JK_DEMO_SCRIPT: script, console };
  scope.window = scope;
  vm.runInNewContext(source, scope);
  return { demo: scope.JKDemo, advance, sent, timers, op: scope.JKOp,
    click(a) { bar.onclick({ target: { closest: () => ({ dataset: { a } }) } }); } };
}

test('#177 等待身份不计时，异步取消不会发送或留下定时器', async () => {
  const identity = deferred();
  const p = player([{ title: '切号', steps: [{ login: 'target' }, { say: '不应发送' }] }],
    { switchUser: () => identity.promise });
  const done = p.demo.start();
  await p.advance(60000);
  assert.equal(p.timers.size, 0);
  assert.equal(p.demo.state.on, false, '身份确认前不进入播放态');
  identity.resolve(false);
  await p.advance(60000);
  await done;
  assert.deepEqual(p.sent, []);
  assert.deepEqual([p.demo.state.i, p.demo.state.on, p.op.demo, p.timers.size], [0, false, false, 0]);
});

test('#177 中途切号取消后不推进，也不替先前角色执行下一步', async () => {
  const identity = deferred();
  const p = player([{ title: '已完成段', steps: [{ wait: 80 }] },
    { title: '换身份', steps: [{ login: 'target' }, { say: '不能代办' }] },
    { title: '后续段', steps: [{ say: '不能跳到此处' }] }], { switchUser: () => identity.promise });
  const done = p.demo.start();
  await p.advance(60000);
  assert.equal(p.demo.state.i, 1);
  assert.equal(p.timers.size, 0);
  identity.resolve(false);
  await done;
  await p.advance(60000);
  assert.deepEqual([p.demo.state.i, p.demo.state.on, p.sent, p.timers.size], [1, false, [], 0]);
});

test('#216 点击异步确认后，以回执完成而不是 click 返回作为阅读起点', async () => {
  let busy = false, clicks = 0;
  const button = { scrollIntoView() {}, dataset: {}, click() { busy = true; clicks++; },
    getAttribute(name) { return name === 'aria-busy' && busy ? 'true' : null; } };
  const p = player([{ title: '等待回执', steps: [{ click: '#decision', wait: 900 }] },
    { title: '结束', steps: [] }], {}, { '#decision': button });
  const done = p.demo.start();
  await p.advance(60000);
  assert.equal(clicks, 1);
  p.click('skip');
  assert.equal(p.demo.state.i, 0);
  busy = false;
  await p.advance(899);
  assert.equal(p.demo.state.i, 0);
  await p.advance(1000);
  await done;
  assert.equal(p.demo.state.i, 2);
});

test('#216 打开确认框后即返回的页面，必须等本人处理才继续', async () => {
  const elements = {};
  const selector = '[role="dialog"] [data-ok]';
  const p = player([{ title: '确认', steps: [{ open: 'inbox' }] },
    { title: '下一段', steps: [{ say: '后续' }] }],
    { openBuiltin() { elements[selector] = {}; } }, elements);
  const done = p.demo.start();
  await p.advance(60000);
  p.click('skip');
  assert.deepEqual([p.demo.state.i, p.sent], [0, []]);
  delete elements[selector];
  await p.advance(60000);
  await done;
  assert.deepEqual(p.sent, ['后续']);
});

test('#216 操作员的自动示范选择尊重暂停；手动回答、退出均撤销旧回调', async () => {
  const confirmation = deferred();
  const p = player([{ title: '确认', steps: [{ open: 'inbox' }] }], { openBuiltin: () => confirmation.promise });
  const done = p.demo.start();
  await p.advance(0);
  let picked = 0;
  const cancel = p.demo.scheduleChoice(() => { picked++; });
  await p.advance(400);
  p.click('pause');
  await p.advance(60000);
  assert.equal(picked, 0);
  p.click('pause');
  await p.advance(1999);
  assert.equal(picked, 0);
  await p.advance(1);
  assert.equal(picked, 1);
  cancel();
  const manual = p.demo.scheduleChoice(() => { picked++; });
  manual();
  p.demo.scheduleChoice(() => { picked++; });
  p.click('exit');
  confirmation.resolve();
  await done;
  await p.advance(60000);
  assert.equal(picked, 1);
  assert.equal(p.timers.size, 0);
});

test('#216 已配置的阅读时间不随操作动画加速，暂停冻结剩余时间', async () => {
  const p = player([{ title: '阅读', steps: [{ wait: 4000 }] }, { title: '下一页', steps: [{ wait: 4000 }] }]);
  p.demo.start();
  await p.advance(1000);
  assert.equal(p.demo.state.i, 0, '阅读时间被 demoSpeed 缩短');
  p.click('pause');
  await p.advance(60000);
  assert.equal(p.demo.state.i, 0);
  p.click('pause');
  await p.advance(2999);
  assert.equal(p.demo.state.i, 0);
  await p.advance(1);
  assert.equal(p.demo.state.i, 1, '恢复后应按剩余时长切段，而非从头倒计时');
  await p.advance(15000);
  assert.equal(p.demo.state.on, false);
});

test('#216 操作未返回不能切段；暂停时手动下一段只走一段，退出清除等待', async () => {
  const load = deferred();
  const p = player([{ title: '加载', steps: [{ open: 'admin' }] },
    { title: '二', steps: [{ say: '仅播放第二段' }] }, { title: '三', steps: [{ say: '不应发送' }] }],
    { openBuiltin: () => load.promise });
  const done = p.demo.start();
  await p.advance(60000);
  assert.equal(p.demo.state.i, 0);
  p.click('pause');
  load.resolve();
  await p.advance(60000);
  assert.equal(p.demo.state.i, 0, '暂停期间异步返回后自动切段');
  p.click('skip');
  await p.advance(60000);
  assert.deepEqual([p.demo.state.i, p.demo.state.paused, p.sent], [1, true, ['仅播放第二段']]);
  p.click('exit');
  await done;
  assert.equal(p.timers.size, 0);
});

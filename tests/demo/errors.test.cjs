const assert = require('node:assert/strict');
const { execFile } = require('node:child_process');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');
const { promisify } = require('node:util');

// 追加到临时副本的演示引擎末尾，通过真实浏览器事件触发故障。
function injectFaults() {
  const theme = localStorage.getItem('jk4-theme2');
  const state = JKDemo.state;
  if (innerWidth === 1440 && theme === 'dark') {
    let index = state.i;
    Object.defineProperty(state, 'i', {
      get: () => index,
      set(next) {
        index = next;
        if (next === 9) queueMicrotask(() => { throw new Error('第 10 段刚开始的异常'); });
      },
    });
  }
  if (innerWidth === 1440 && theme === 'light') {
    const switchUser = JKShell.switchUser;
    JKShell.switchUser = async function (user, ...rest) {
      const switched = await switchUser.call(this, user, ...rest);
      if (user === 'hejun' && state.i === 9) {
        queueMicrotask(() => { throw new Error('第 10 段执行中的异常'); });
      }
      return switched;
    };
  }
  if (innerWidth === 1280 && theme === 'dark') {
    // 第 10 段设置字幕时，由浏览器产生拒绝和控制台消息。
    const step = JK_DEMO_SCRIPT[9].steps[0];
    const caption = step.caption;
    Object.defineProperty(step, 'caption', {
      get() {
        queueMicrotask(() => {
          Promise.reject(new Error('第 10 段未处理的拒绝'));
          console.warn('demo', '第 10 段演示警告');
          console.error('第 10 段控制台错误');
          console.warn('普通警告不影响演示');
        });
        Object.defineProperty(step, 'caption', { value: caption });
        return caption;
      },
    });
  }
  if (innerWidth === 1280 && theme === 'light') {
    queueMicrotask(() => { throw new Error('演示启动前的异常'); });
  }
}

test('浏览器故障只归入发生时的段落，演示命令退出 1', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'jingkai-demo-errors-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const demo = path.join(root, 'tests/demo');
  const prototype = path.join(root, 'prototype/v4');
  await fs.mkdir(demo, { recursive: true });
  await Promise.all([
    fs.cp(path.resolve(__dirname, '../../prototype/v4'), prototype, { recursive: true }),
    ...['run.cjs', 'checks.cjs'].map(file => fs.copyFile(path.join(__dirname, file), path.join(demo, file))),
  ]);
  await fs.appendFile(path.join(prototype, 'assets/demo.js'), '\n(' + injectFaults.toString() + ')();\n');

  const modules = path.dirname(path.dirname(require.resolve('playwright/package.json')));
  const run = promisify(execFile)(process.execPath, [path.join(demo, 'run.cjs')], {
    env: { ...process.env, NODE_PATH: [modules, process.env.NODE_PATH].filter(Boolean).join(path.delimiter) },
    timeout: 240000,
  });
  await assert.rejects(run, error => error.code === 1 && !error.killed);

  const report = await fs.readFile(path.join(demo, 'REPORT.md'), 'utf8');
  const rows = report.split('\n').filter(line => /^\| \d+\. /.test(line))
    .map(line => line.split(' | ').slice(0, 5));
  assert.equal(rows.length, 48);
  // 四组所有未注入段均须通过，包括第 9 段和第 11 段。
  const failed = rows.filter(([, , , status]) => status !== '通过');
  assert.deepEqual(failed.map(row => row.slice(0, 4)), [
    ['| 10. 外部协作者', '1440', 'dark', '失败'],
    ['| 10. 外部协作者', '1440', 'light', '失败'],
    ['| 10. 外部协作者', '1280', 'dark', '失败'],
    ['| 1. 开场', '1280', 'light', '失败'],
  ]);
  assert.equal(failed[0][4], '第 10 段刚开始的异常');
  assert.equal(failed[1][4], '第 10 段执行中的异常');
  assert.deepEqual(failed[2][4].split('；').sort(), [
    'demo 第 10 段演示警告',
    '第 10 段控制台错误',
    '第 10 段未处理的拒绝',
  ].sort());
  assert.equal(failed[3][4], '演示启动前的异常');
});

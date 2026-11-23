const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');
const { labels, installChecks } = require('../demo/checks.cjs');

const entry = pathToFileURL(path.resolve(__dirname, '../../prototype/v4/index.html')).href;
const output = process.argv[2];
assert.ok(output, '请指定截图输出目录');

async function walkthrough(browser, width, theme) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, offline: true });
  try {
    const page = await context.newPage();
    const failures = [];
    page.on('pageerror', error => failures.push(error.message));
    page.on('console', msg => {
      if (msg.type() === 'error' || (msg.type() === 'warning' && /^demo\b/.test(msg.text()))) {
        failures.push(msg.text());
        console.error(width, theme, msg.text());
      }
    });
    await page.addInitScript(t => localStorage.setItem('jk4-theme2', t), theme);
    await page.goto(entry);
    assert.equal(await page.evaluate(() => JK_CONFIG.api.mode), 'mock');
    assert.deepEqual(await page.evaluate(() => JK_DEMO_SCRIPT.map(s => s.title)), labels.map(([t]) => t));
    const dir = path.join(output, width + '-' + theme);
    await fs.mkdir(dir, { recursive: true });

    const captured = new Set();
    async function capture(name, expectedTheme = theme) {
      assert.equal(await page.locator('html').getAttribute('data-theme'), expectedTheme);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
        width + '/' + theme + '/' + name + ' 页面横向溢出');
      await page.screenshot({ path: path.join(dir, name + '.jpg'), quality: 54, timeout: 10000 });
      captured.add(name);
    }

    async function checkInFrame(locator) {
      assert.ok(await locator.evaluate(el => {
        // 收件箱会异步替换整行，在同一次 DOM 调用中完成定位与命中检查。
        el.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' });
        const { left, right, top, bottom } = el.getBoundingClientRect();
        const x = (left + right) / 2;
        const y = (top + bottom) / 2;
        // 圆角按钮的四角透明，用中心与四边中点检查实际可见区域。
        const points = [[x, y], [left + 2, y], [right - 2, y], [x, top + 2], [x, bottom - 2]];
        return points.every(([px, py]) => el.contains(document.elementFromPoint(px, py)));
      }), '关键内容被遮挡或裁切：' + locator);
    }

    const login = page.locator('[data-u="wangmin"]');
    await login.waitFor();
    await page.screenshot({ path: path.join(dir, '00.jpg'), quality: 54,
      mask: [page.locator('.ql .rl')] });
    await login.click();
    await page.locator('#btn-demo').waitFor();
    await page.evaluate(installChecks);
    // 在真实引擎等待每条业务操作返回时拍照，避免把下一页误存为上一页。
    const lastOperation = new Map();
    await page.exposeFunction('beforeSubmit', async () => {
      const panel = page.locator('.pview.on [data-op="computer.wait"]');
      assert.match(await panel.innerText(), /停在「提交」前/);
      await checkInFrame(panel.locator('b').first());
      await checkInFrame(page.locator('[data-o="确认提交"]:visible').last());
      await capture('08-before');
    });
    await page.exposeFunction('captureOperation', async (segment, number) => {
      if (segment === '11') {
        await page.locator('.pview.on .adm-body .skel').waitFor({ state: 'hidden' });
      }
      if (segment === '09') {
        const { reviewId } = await page.evaluate(() => demoRegression.submittedDraft());
        await checkInFrame(page.locator('.pview.on [data-dec="approve"][data-id="' + reviewId + '"]'));
      }
      if (segment === '08' && number === 1) {
        const receipt = page.locator('.pview.on .cu-wait b').filter({ hasText: '已提交，受理编号' });
        await checkInFrame(receipt);
        const id = (await receipt.innerText()).split('受理编号 ')[1];
        assert.ok(id && (await page.locator('#chatcol').innerText()).includes(id), '回执编号不一致');
      }
      const name = segment + '-' + number;
      await capture(name);
      lastOperation.set(segment, name);
    });
    await page.evaluate(() => {
      const postPlan = JKOp.hooks.postPlan;
      JKOp.hooks.postPlan = function (...args) {
        const card = postPlan.apply(this, args);
        const pick = card.pick;
        card.pick = async function (choice) {
          if (JKDemo.state.i === 7 && choice === '确认提交') {
            try { await window.beforeSubmit(); }
            catch (error) { console.error('确认前取景失败：' + error.message); }
          }
          return pick.call(this, choice);
        };
        return card;
      };
      const counts = {};
      for (const method of ['send', 'handleFile', 'openApp', 'openBuiltin']) {
        const original = JKShell[method];
        JKShell[method] = async function (...args) {
          const result = await original.apply(this, args);
          const { on, i } = JKDemo.state;
          if (on) {
            counts[i] = (counts[i] || 0) + 1;
            await window.captureOperation(String(i + 1).padStart(2, '0'), counts[i]);
          }
          return result;
        };
      }
    });
    await page.locator('#btn-demo').click();
    for (const [i, [title]] of labels.entries()) {
      if (i === 11 && theme === 'light') {
        await page.waitForFunction(() => JKDemo.state.i === 11 &&
          document.documentElement.dataset.theme === 'light' && /深色、浅色/.test(JKDemo.state.cap));
        await capture('12');
      }
      const result = await page.waitForFunction(i => demoRegression.inspect(i), i, { timeout: 120000 });
      const { missing, active } = await result.jsonValue();
      assert.deepEqual(missing, [], title);
      assert.ok(active, title + ' 截图前已切段');
      if (i === 8) {
        const { reviewId } = await page.evaluate(() => demoRegression.submittedDraft());
        const inbox = page.locator('.pview.on[data-view="inbox"]');
        await inbox.locator('[data-dec="approve"][data-id="' + reviewId + '"]').waitFor({ state: 'detached' });
        await checkInFrame(inbox.locator('[data-t="mine"]'));
        assert.equal(await page.evaluate(() => JKDemo.state.i), i);
      }
      if (i === 0 || i === 8 || (i === 11 && theme === 'dark')) {
        await capture(String(i + 1).padStart(2, '0'));
      }
      console.log(width, theme, i + 1, title);
    }
    await page.waitForFunction(() => !JKDemo.state.on);
    assert.equal(await page.evaluate(() => JKDemo.state.i), labels.length);
    if (theme === 'light') {
      assert.equal(await page.evaluate(() => JKShell.S.me.username), 'wangmin');
      await checkInFrame(page.locator('#btn-me .nm'));
      // #144：演示结束后恢复启动时的主题，浅色组的结束页仍为浅色。
      // 主题切换的颜色过渡未结束时卡片仍是半深色，先等过渡完成再取景。
      await page.evaluate(() => Promise.all(document.getAnimations()
        .filter(animation => animation instanceof CSSTransition)
        .map(animation => animation.finished.catch(() => {}))));
      await capture('12-end', theme);
    }
    assert.deepEqual(failures, []);
    for (const name of ['08-before', '08-1', '09-1', '09', '12']) {
      assert.ok(captured.has(name), '本次运行缺少关键截图 ' + name);
    }
    // 以最后一条操作的结果作为段落封面，审签另存通过后的回执。
    for (const [segment, name] of lastOperation) {
      if (segment !== '09') {
        await fs.rename(path.join(dir, name + '.jpg'), path.join(dir, segment + '.jpg'));
      }
    }
  } catch (error) {
    const state = await context.pages()[0]?.evaluate(() => ({
      segment: window.JKDemo?.state.i + 1,
      caption: window.JKDemo?.state.cap,
      paused: window.JKDemo?.state.paused,
    })).catch(() => null);
    throw new Error(width + ' ' + theme + ' ' + JSON.stringify(state) + ' ' + error.message);
  } finally {
    await context.close();
  }
}

async function main() {
  const browser = await chromium.launch({
    args: ['--allow-file-access-from-files'],
    channel: process.env.WALKTHROUGH_CHROME ? 'chrome' : undefined,
  });
  try {
    const group = process.argv[3];
    if (group) {
      assert.match(group, /^(1440|1280)-(light|dark)$/);
      const [width, theme] = group.split('-');
      await walkthrough(browser, Number(width), theme);
      console.log(group + ' 通过 12 段');
      return;
    }
    for (const width of [1440, 1280]) {
      for (const theme of ['light', 'dark']) {
        await walkthrough(browser, width, theme);
      }
    }
    console.log('通过 4 组 × 12 段');
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });

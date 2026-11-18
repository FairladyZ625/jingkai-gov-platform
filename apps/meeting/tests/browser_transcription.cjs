/* 从仓库根目录运行。依赖 tests/demo 中已安装的 Playwright。 */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('../../../tests/demo/node_modules/playwright');

async function verify(base, output) {
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ colorScheme: 'light', locale: 'zh-CN',
      viewport: { width: 1440, height: 900 } });
    const login = await context.request.post(base + '/api/v1/auth/login', {
      data: { username: 'meeting-writer', password: 'test-meet' },
    });
    assert.equal(login.status(), 200);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(base + '/api/apps/meeting/transcription');
    await page.getByLabel('会议名称').fill('园区服务例会');
    await page.getByLabel('录音文件').setInputFiles(path.join(__dirname, '../samples/demo.webm'));
    const upload = page.waitForResponse(r => r.request().method() === 'POST'
      && r.url().endsWith('/api/apps/meeting/meetings'));
    await page.getByRole('button', { name: '上传并转写' }).click();
    assert.equal((await upload).status(), 201);

    await page.getByRole('status').getByText('转写第 2 片失败', { exact: true }).waitFor();
    const retry = page.waitForResponse(r => r.request().method() === 'POST'
      && r.url().endsWith('/retry?app=meeting'));
    await page.getByRole('button', { name: '重试', exact: true }).click();
    assert.equal((await retry).status(), 202);

    await page.getByRole('heading', { name: '逐字稿' }).waitFor();
    assert.equal(await page.locator('#percent').textContent(), '100%');
    assert.equal(await page.locator('#lines li').count(), 2);
    await page.reload();
    await page.getByRole('heading', { name: '逐字稿' }).waitFor();
    assert.equal(await page.getByRole('heading', { name: '园区服务例会' }).count(), 1);
    await page.getByText('我们先核对园区服务清单。请把本周收集的问题按主题归类。').waitFor();
    await page.waitForFunction(() => {
      const audio = document.querySelector('#sample-audio');
      return audio.duration > 10 && audio.duration < 12;
    });
    assert.deepEqual(errors, []);

    await fs.mkdir(output, { recursive: true });
    for (const width of [1440, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await page.screenshot({ path: path.join(output, `transcription-${width}.png`) });
    }
    console.log('浏览器验证通过：上传 201，第二片失败，重试 202，进度 100%，刷新后仍显示 2 段逐字稿。截图 1440×900、1280×900。');
  } finally {
    await browser.close();
  }
}

const [base = 'http://127.0.0.1:18036', output = 'apps/meeting/tests/screenshots'] = process.argv.slice(2);
verify(base, output).catch(error => {
  console.error(error);
  process.exitCode = 1;
});

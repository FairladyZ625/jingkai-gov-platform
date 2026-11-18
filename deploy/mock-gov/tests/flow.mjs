import assert from 'node:assert/strict';
import { chromium } from 'playwright-core';
import { join } from 'node:path';

const origin = process.argv[2];
const browser = await chromium.launch({ channel: 'chrome' });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const requests = [];
  const errors = [];
  page.on('request', req => requests.push([req.method(), new URL(req.url()).origin]));
  page.on('pageerror', error => errors.push(error.message));
  const op = name => page.locator(`[data-op="${name}"]`);
  const click = name => op(name).click();
  const visible = async id => assert(await page.locator('#' + id).isVisible());
  const screenshot = async width => {
    if (process.env.MOCK_GOV_SCREENSHOTS) {
      await page.setViewportSize({ width, height: 900 });
      await page.screenshot({ path: join(process.env.MOCK_GOV_SCREENSHOTS, width + '.png') });
    }
  };
  await page.goto(origin);
  await visible('login');
  assert.match(await page.locator('header').innerText(), /模拟系统，不收集真实信息/);
  const anchors = await page.locator('a,button,input,select,textarea').evaluateAll(
    nodes => nodes.map(node => node.dataset.op)
  );
  assert(anchors.every(Boolean));
  assert.equal(new Set(anchors).size, anchors.length);
  console.log('data-op 缺失 0、重复 0');
  const initialRequests = requests.length;
  await screenshot(1440);
  await click('login');
  await visible('apply');
  assert(await op('apply-next').isDisabled());
  await op('service').selectOption({ label: '模拟企业备案' });
  await click('apply-next');
  await visible('upload');
  assert(await op('upload-next').isDisabled());
  await click('upload-back');
  await click('apply-next');
  await click('upload');
  await click('upload-next');
  await visible('captcha');
  await click('captcha-back');
  await click('upload-next');
  await op('captcha').fill('0000');
  await click('verify');
  assert.match(await page.getByRole('alert').innerText(), /不正确/);
  await op('captcha').fill('2468');
  await click('verify');
  await visible('confirm');
  await click('confirm-back');
  await op('service').selectOption({ label: '模拟信息变更' });
  await click('apply-next');
  await click('upload-next');
  assert.equal(await op('captcha').inputValue(), '');
  await op('captcha').fill('2468');
  await click('verify');
  assert.equal(await page.locator('#summary').innerText(), '模拟信息变更');
  assert.match(await page.locator('#confirm').innerText(), /模拟系统，不收集真实信息/);
  assert.equal(await page.locator('#receipt').textContent(), '');
  await screenshot(1280);
  await click('submit');
  await visible('done');
  assert.match(await page.locator('#receipt').innerText(), /^SIM-[0-9A-F]{8}$/);
  assert.equal(requests.length, initialRequests);
  await click('restart');
  await visible('login');
  assert.equal(await page.locator('#receipt').textContent(), '');
  assert.equal(await op('service').inputValue(), '');
  assert(requests.every(([method, host]) => method === 'GET' && host === origin));
  assert.deepEqual(errors, []);
  console.log('五步演练、回退修改、错误码拦截、提交回执、重置及零外部请求验证通过');
} finally {
  await browser.close();
}

const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: '.',
  testMatch: 'http-smoke.spec.cjs',
  reporter: 'list',
  outputDir: '../node_modules/.cache/playwright-http',
  use: { channel: 'chromium', viewport: { width: 1440, height: 900 } },
});

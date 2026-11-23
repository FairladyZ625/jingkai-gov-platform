const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: '.',
  testMatch: 'http-smoke.spec.cjs',
  reporter: 'list',
  outputDir: '../node_modules/.cache/playwright-http',
  use: {
    ...(process.env.PLAYWRIGHT_CHROME_PATH
      ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROME_PATH } }
      : { channel: 'chromium' }),
    viewport: { width: 1440, height: 900 },
  },
});

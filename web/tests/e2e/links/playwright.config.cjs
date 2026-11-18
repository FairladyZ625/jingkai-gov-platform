const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: '.',
  testMatch: '*.spec.cjs',
  outputDir: '../../../node_modules/.cache/playwright-links',
  reporter: 'list',
  workers: 1,
  timeout: 60_000,
  use: {
    baseURL: process.env.T41_BASE_URL,
    channel: 'chromium',
    viewport: { width: 1440, height: 900 },
  },
});

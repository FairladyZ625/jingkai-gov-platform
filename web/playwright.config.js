const path = require('node:path');
const { defineConfig } = require('@playwright/test');

const py = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

module.exports = defineConfig({
  testDir: './tests',
  testMatch: ['smoke.js', 'e2e.js'],
  outputDir: './node_modules/.cache/playwright',
  reporter: 'list',
  workers: 4,
  timeout: 60_000,
  use: {
    ...(process.env.PLAYWRIGHT_CHROME_PATH
      ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROME_PATH } }
      : { channel: 'chromium' }),
    viewport: { width: 1440, height: 900 },
  },
  webServer: [
    {
      command: `${py} -m http.server -d web 8080 --bind 127.0.0.1`,
      cwd: path.resolve(__dirname, '..'),
      stderr: 'ignore',
      url: 'http://localhost:8080/',
    },
    {
      command: `${py} tests/serve-subpath.py`,
      stderr: 'ignore',
      url: 'http://127.0.0.1:8081/v4/',
    },
  ],
});

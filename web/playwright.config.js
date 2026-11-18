const path = require('node:path');
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests',
  testMatch: ['smoke.js', 'e2e.js'],
  outputDir: './node_modules/.cache/playwright',
  reporter: 'list',
  workers: 4,
  timeout: 60_000,
  use: { channel: 'chromium', viewport: { width: 1440, height: 900 } },
  webServer: [
    {
      command: 'python3 -m http.server -d web 8080 --bind 127.0.0.1',
      cwd: path.resolve(__dirname, '..'),
      stderr: 'ignore',
      url: 'http://localhost:8080/',
    },
    {
      command: 'python3 tests/serve-subpath.py',
      stderr: 'ignore',
      url: 'http://127.0.0.1:8081/v4/',
    },
  ],
});

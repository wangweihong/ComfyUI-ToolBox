import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/media_library/e2e', workers: 1, timeout: 45000,
  use: {baseURL: 'http://127.0.0.1:8919', viewport: {width: 1440, height: 1000}, launchOptions: {args: ['--no-sandbox']}},
  webServer: {
    command: `${process.env.MEDIA_LIBRARY_TEST_PYTHON || 'python3'} tests/media_library/serve_fixture.py --port 8919`,
    url: 'http://127.0.0.1:8919/toolbox/media-library/gallery', reuseExistingServer: false, timeout: 30000,
  },
});

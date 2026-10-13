import { defineConfig, devices } from '@playwright/test';
import { guardedDevWebServer, resolveLegacyEnv } from './src/testing/legacyGuard';

// Fail-closed loopback guard: throws at config-load time on any non-loopback /
// production target. The legacy suite is loopback-only (no allow-list).
const { baseUrl: BASE_URL, apiUrl: API_URL } = resolveLegacyEnv();

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  timeout: 900_000,
  expect: { timeout: 30_000 },
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report-e2e', open: 'never' }],
  ],
  use: {
    baseURL: BASE_URL,
    headless: false,
    slowMo: 3000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
  },
  webServer: guardedDevWebServer(BASE_URL, {
    apiUrl: API_URL,
    reuseExistingServer: true,
    timeout: 120_000,
  }),
  projects: [
    {
      name: 'e2e-clean',
      testMatch: /e2e-clean-workflow\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: 'e2e-positive-path',
      testMatch: /positive-path-e2e\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
});

export { BASE_URL, API_URL };

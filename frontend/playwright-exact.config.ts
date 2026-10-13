// Dedicated config for the exact-business-workflow specs (no stale setup).
import { defineConfig, devices } from '@playwright/test';
import { assertOptionalLoopback, guardedDevWebServer, resolveLegacyEnv } from './src/testing/legacyGuard';

// Fail-closed loopback guard: throws at config-load time on any non-loopback /
// production target. The exact specs read E2E_API_URL directly — validate it too.
const { baseUrl: BASE_URL, apiUrl: API_URL } = resolveLegacyEnv();
assertOptionalLoopback('E2E_API_URL', process.env.E2E_API_URL);

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  timeout: 900_000,
  expect: { timeout: 30_000 },
  reporter: [['list']],
  use: {
    baseURL: BASE_URL,
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
  },
  webServer: guardedDevWebServer(BASE_URL, {
    apiUrl: API_URL,
    reuseExistingServer: true,
    timeout: 180_000,
  }),
  projects: [
    {
      name: 'exact-flow',
      testMatch: /exact-business-flow\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'exact-grant',
      testMatch: /exact-grant-verify\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'exact-negatives',
      testMatch: /exact-negatives\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'exact-mobile',
      testMatch: /exact-mobile\.spec\.ts/,
      use: { ...devices['iPhone 13'] },
    },
  ],
});

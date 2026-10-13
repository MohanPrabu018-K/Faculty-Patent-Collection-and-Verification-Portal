/**
 * Dedicated Playwright project for the AUTHENTICATED STAGING rule matrix.
 *
 * IMPORTANT design decisions:
 *   * NO `webServer` — the operator starts the staging (or local) stack
 *     explicitly. This project can never silently boot a server against the
 *     wrong database.
 *   * Refuses to load unless `resolveStagingEnv()` accepts the environment
 *     (see tests-staging/guard.ts). Production URLs / unconfirmed env abort.
 *   * Serial, single worker: the scenarios create and mutate real rows
 *     (associations, grants), so determinism matters.
 *
 * Run (after provisioning + starting the stack):
 *   $env:STAGING_CONFIRM='1'
 *   $env:STAGING_FRONTEND_URL='http://localhost:5173'
 *   $env:STAGING_API_URL='http://localhost:8000'
 *   npx playwright test -c playwright-staging.config.ts
 */
import { defineConfig, devices } from '@playwright/test';
import { resolveStagingEnv } from './tests-staging/guard';

// Throws (and aborts the run) on any unconfirmed/production target.
const env = resolveStagingEnv();

export default defineConfig({
  testDir: './tests-staging',
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report-staging', open: 'never' }],
  ],
  metadata: {
    staging_frontend_url: env.frontendUrl,
    staging_api_url: env.apiUrl,
    suite: 'authenticated-staging-rules-A-F',
  },
  use: {
    baseURL: env.frontendUrl,
    headless: true,
    ignoreHTTPSErrors: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: 'staging-chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],
});

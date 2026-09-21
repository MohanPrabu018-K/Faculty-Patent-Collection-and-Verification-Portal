import { defineConfig, devices } from '@playwright/test';

const BASE_URL = process.env.FRONTEND_URL || 'http://localhost:5173';
const API_URL = process.env.API_URL || 'http://localhost:8000';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 3,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  use: {
    baseURL: BASE_URL,
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  webServer: {
    command: 'npm run dev',
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'setup',
      testMatch: /auth\.setup\.ts/,
      use: { trace: 'off' },
    },
    // General regression projects — exclude real-production-flow (has dedicated serial projects below)
    {
      name: 'chromium-desktop',
      dependencies: ['setup'],
      testIgnore: /real-production-flow\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'chromium-laptop',
      dependencies: ['setup'],
      testIgnore: /real-production-flow\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 720 } },
    },
    {
      name: 'chromium-tablet',
      dependencies: ['setup'],
      testIgnore: /real-production-flow\.spec\.ts/,
      use: { ...devices['iPad (gen 7)'], viewport: { width: 768, height: 1024 } },
    },
    {
      name: 'chromium-mobile',
      dependencies: ['setup'],
      testIgnore: /real-production-flow\.spec\.ts/,
      use: { ...devices['iPhone 13'], viewport: { width: 390, height: 844 } },
    },
    // Real-production-flow acceptance — shared Neon DB + shared Faculty A/B accounts;
    // four viewport projects MUST NOT run Test A concurrently (creates duplicate association
    // race where one run's PENDING request shadows another's ACCEPTED history). Serialized
    // via dependencies; other suites remain parallel (workers=3).
    {
      name: 'acceptance-desktop',
      dependencies: ['setup'],
      testMatch: /real-production-flow\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'acceptance-laptop',
      dependencies: ['acceptance-desktop'],
      testMatch: /real-production-flow\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 720 } },
    },
    {
      name: 'acceptance-tablet',
      dependencies: ['acceptance-laptop'],
      testMatch: /real-production-flow\.spec\.ts/,
      use: { ...devices['iPad (gen 7)'], viewport: { width: 768, height: 1024 } },
    },
    {
      name: 'acceptance-mobile',
      dependencies: ['acceptance-tablet'],
      testMatch: /real-production-flow\.spec\.ts/,
      use: { ...devices['iPhone 13'], viewport: { width: 390, height: 844 } },
    },
  ],
});

export { BASE_URL, API_URL };

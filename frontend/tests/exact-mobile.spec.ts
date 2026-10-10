// Mobile-viewport smoke in a real browser (Chromium).
// Env: E2E_CREDS_FILE.
import { test, expect, type Page } from '@playwright/test';
import fs from 'node:fs';

const CREDS = JSON.parse(fs.readFileSync(process.env.E2E_CREDS_FILE!, 'utf-8'));
const U = CREDS.users as Record<string, { id: string; email: string; full_name: string }>;
const PASSWORD: string = CREDS.password;

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

async function loginAs(page: Page, key: string, home: RegExp) {
  await page.waitForTimeout(8000);
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Email').fill(U[key].email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Login' }).click();
  await page.waitForURL(home, { timeout: 60_000 });
}

test('mobile: login, dashboard and record render without horizontal overflow', async ({ page }) => {
  await loginAs(page, 'FACB', /\/faculty\/dashboard/);
  await expect(page.getByText('Alice PwOne').first().or(page.getByText('Dashboard').first())).toBeVisible({ timeout: 30_000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.goto('/faculty/associations');
  await expect(page.getByText('Association Requests')).toBeVisible({ timeout: 30_000 });
  const overflow2 = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow2).toBeLessThanOrEqual(1);
});

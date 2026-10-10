// Post-grant verification in a real browser (Chromium).
// Runs AFTER pw_grant.py. Env: E2E_CREDS_FILE, E2E_API_URL, E2E_RECORD_ID.
import { test, expect, type Page } from '@playwright/test';
import fs from 'node:fs';

const CREDS = JSON.parse(fs.readFileSync(process.env.E2E_CREDS_FILE!, 'utf-8'));
const U = CREDS.users as Record<string, { id: string; email: string; full_name: string }>;
const PASSWORD: string = CREDS.password;
const RECORD_ID = process.env.E2E_RECORD_ID!;
const MAIN_TITLE = 'Playwright Main Widget';

test.describe.configure({ mode: 'serial' });

async function loginAs(page: Page, key: string, home: RegExp) {
  await page.waitForTimeout(8000);
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Email').fill(U[key].email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Login' }).click();
  await page.waitForURL(home, { timeout: 60_000 });
}

test('faculty dashboard shows the granted patent with date-only grant date', async ({ page }) => {
  await loginAs(page, 'FACB', /\/faculty\/dashboard/);
  await page.goto('/faculty/my-records?per_page=50');
  await expect(page.getByText('Playwright Main Widget')).toBeVisible({ timeout: 60_000 });
  await page.goto(`/faculty/records/${RECORD_ID}`);
  await expect(page.getByText('GRANTED')).toBeVisible({ timeout: 30_000 });
  // Grant date DD/MM/YYYY (12/09/2024), never an ISO timestamp.
  await expect(page.getByText('12/09/2024')).toBeVisible();
  await expect(page.getByText(/T00:00:00/)).toHaveCount(0);
});

test('HOD documents show the granted patent', async ({ page }) => {
  await loginAs(page, 'HOD_CSE', /\/hod\/dashboard/);
  await page.goto('/hod/documents');
  await expect(page.getByText('TEST-PW-MAIN-001')).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText('12/09/2024')).toBeVisible();
});

test('no raw JSON errors anywhere on key pages', async ({ page }) => {
  await loginAs(page, 'FACA', /\/faculty\/dashboard/);
  for (const path of ['/faculty/dashboard', `/faculty/records/${RECORD_ID}`, '/faculty/associations']) {
    await page.goto(path);
    await page.waitForLoadState('networkidle');
    await expect(page.getByText(/"error"/)).toHaveCount(0);
  }
});

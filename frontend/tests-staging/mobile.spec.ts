/**
 * Mobile-viewport validation (real Chromium, phone viewport).
 *
 * Genuine 390x844 touch viewport. Exercises login, dashboards, records,
 * HOD documents, upload form and notifications with layout assertions and
 * the shared NetProbe network/console rules. Read-only.
 */
import { test, expect, type Browser, type Page } from '@playwright/test';
import { account, record } from './fixtures';
import { resolveStagingEnv } from './guard';
import { NetProbe, newProbedPage } from './netprobe';

test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

const env = resolveStagingEnv();
const MOBILE_CTX = { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true };

function expectClean(probe: NetProbe) {
  const v = probe.verdict();
  // eslint-disable-next-line no-console
  if (!v.ok) console.log(`[mobile-probe] unexpected:\n${v.lines.join('\n')}`);
  expect(v.lines, JSON.stringify(v.lines.slice(0, 6))).toEqual([]);
}

async function overflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

async function loginAs(page: Page, probe: NetProbe, key: string, home: RegExp) {
  const acc = account(key);
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Email').fill(acc.email);
  await page.getByLabel('Password').fill(acc.password);
  await page.getByRole('button', { name: 'Login' }).click();
  await page.waitForURL(home, { timeout: 60_000 });
  probe.markLoggedIn();
}

test('M1: mobile login + faculty dashboard usable', async ({ browser }) => {
  const { page, probe } = await newProbedPage(browser, MOBILE_CTX);
  await loginAs(page, probe, 'faculty01', /\/faculty\/dashboard/);
  // Stable dashboard copy (the word "Dashboard" also exists in hidden nav
  // duplicates on narrow viewports, so assert the main heading instead).
  await expect(page.getByText('Faculty submission overview')).toBeVisible({ timeout: 30_000 });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  // Narrow viewports hide the sidebar by design; the bottom mobile-nav
  // takes over navigation (see AppShell + styles.css breakpoints).
  await expect(page.locator('.mobile-nav').first()).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(1500);
  expectClean(probe);
  await page.context().close();
});

test('M2: mobile records list + detail usable', async ({ browser }) => {
  const { page, probe } = await newProbedPage(browser, MOBILE_CTX);
  await loginAs(page, probe, 'faculty01', /\/faculty\/dashboard/);
  await page.goto('/faculty/records');
  // "My Records" also names a hidden sidebar entry on narrow viewports;
  // assert the page's own section heading instead.
  await expect(page.getByText('Search and filter your submissions.')).toBeVisible({ timeout: 30_000 });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.goto(`/faculty/records/${record('a1')}`);
  await expect(page.getByText(/Extracted Information|Document Information/).first()).toBeVisible({ timeout: 30_000 });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.waitForTimeout(1500);
  expectClean(probe);
  await page.context().close();
});

test('M3: mobile upload form + associations usable', async ({ browser }) => {
  const { page, probe } = await newProbedPage(browser, MOBILE_CTX);
  await loginAs(page, probe, 'faculty01', /\/faculty\/dashboard/);
  await page.goto('/faculty/upload');
  const fileInput = page.locator('input[type="file"]').first();
  await expect(fileInput).toBeAttached({ timeout: 30_000 });
  const box = await fileInput.boundingBox();
  expect(box, 'file input must be laid out in the viewport').not.toBeNull();
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.goto('/faculty/associations');
  await expect(page.getByText('Requests to link you')).toBeVisible({ timeout: 30_000 });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.waitForTimeout(1500);
  expectClean(probe);
  await page.context().close();
});

test('M4: mobile HOD documents usable', async ({ browser }) => {
  const { page, probe } = await newProbedPage(browser, MOBILE_CTX);
  await loginAs(page, probe, 'hodA', /\/hod\/dashboard/);
  await page.goto('/hod/documents');
  await page.waitForLoadState('networkidle', { timeout: 30_000 });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.waitForTimeout(1500);
  expectClean(probe);
  await page.context().close();
});

test('M5: mobile notifications usable', async ({ browser }) => {
  const { page, probe } = await newProbedPage(browser, MOBILE_CTX);
  await loginAs(page, probe, 'faculty01', /\/faculty\/dashboard/);
  await page.goto('/notifications');
  await page.waitForLoadState('networkidle', { timeout: 30_000 });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.waitForTimeout(1500);
  expectClean(probe);
  await page.context().close();
});

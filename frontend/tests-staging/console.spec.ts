/**
 * Browser console + network validation (desktop Chromium).
 *
 * Real browser against the live staging stack, judged by the documented
 * NetProbe rules (see netprobe.ts): pageerrors/5xx/post-login errors always
 * fail; the pre-login /auth/me session probe and recovered aborts are
 * classified, never blanket-suppressed.
 *
 * Read-only: no uploads are submitted, no grants confirmed, no emails sent.
 */
import { test, expect, type Page } from '@playwright/test';
import { account, record } from './fixtures';
import { resolveStagingEnv } from './guard';
import { NetProbe, newProbedPage } from './netprobe';

test.describe.configure({ mode: 'serial' });

const env = resolveStagingEnv();

function expectClean(probe: NetProbe) {
  const v = probe.verdict();
  // eslint-disable-next-line no-console
  if (!v.ok) console.log(`[console-probe] unexpected:\n${v.lines.join('\n')}`);
  expect(v.lines, JSON.stringify(v.lines.slice(0, 6))).toEqual([]);
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

test('C1: faculty login + dashboard render cleanly', async ({ browser }) => {
  const { page, probe } = await newProbedPage(browser);
  await loginAs(page, probe, 'faculty01', /\/faculty\/dashboard/);
  await expect(page.getByText('Dashboard').first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(2000);
  expectClean(probe);
  await page.context().close();
});

test('C2: records list + detail + refresh render cleanly', async ({ browser }) => {
  const { page, probe } = await newProbedPage(browser);
  await loginAs(page, probe, 'faculty01', /\/faculty\/dashboard/);
  await page.goto('/faculty/records');
  await expect(page.getByText(/Record|Patent|Design|No records/i).first()).toBeVisible({ timeout: 30_000 });
  await page.goto(`/faculty/records/${record('a1')}`);
  await expect(page.getByText(/Extracted Information|Document Information/).first()).toBeVisible({ timeout: 30_000 });
  await page.reload();
  await expect(page.getByText(/Extracted Information|Document Information/).first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1500);
  expectClean(probe);
  await page.context().close();
});

test('C3: upload + associations pages render (no submission)', async ({ browser }) => {
  const { page, probe } = await newProbedPage(browser);
  await loginAs(page, probe, 'faculty01', /\/faculty\/dashboard/);
  await page.goto('/faculty/upload');
  await expect(page.locator('input[type="file"]').first()).toBeAttached({ timeout: 30_000 });
  await page.goto('/faculty/associations');
  await expect(page.getByText(/Association/i).first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1500);
  expectClean(probe);
  await page.context().close();
});

test('C4: HOD read-only pages render cleanly', async ({ browser }) => {
  const { page, probe } = await newProbedPage(browser);
  await loginAs(page, probe, 'hodA', /\/hod\/dashboard/);
  for (const path of ['/hod/dashboard', '/hod/documents', '/hod/duplicates', '/hod/conflicts']) {
    await page.goto(path);
    await page.waitForLoadState('networkidle', { timeout: 30_000 });
  }
  await page.waitForTimeout(1500);
  expectClean(probe);
  await page.context().close();
});

test('C5: super-admin pages render cleanly', async ({ browser }) => {
  const { page, probe } = await newProbedPage(browser);
  await loginAs(page, probe, 'superAdmin', /\/admin\/dashboard/);
  for (const path of ['/admin/dashboard', '/admin/granted-patents', '/admin/audit', '/admin/settings']) {
    await page.goto(path);
    await page.waitForLoadState('networkidle', { timeout: 30_000 });
  }
  await page.waitForTimeout(1500);
  expectClean(probe);
  await page.context().close();
});

test('C6: reset page renders without sending any email', async ({ browser }) => {
  const { page, probe } = await newProbedPage(browser);
  await page.goto('/reset?token=definitely-bogus-token-for-console-probe');
  await page.waitForLoadState('networkidle', { timeout: 30_000 });
  await expect(page.getByText(/Reset|Password/i).first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1500);
  expectClean(probe);
  await page.context().close();
});

test('C7: notifications + search render cleanly', async ({ browser }) => {
  const { page, probe } = await newProbedPage(browser);
  await loginAs(page, probe, 'faculty01', /\/faculty\/dashboard/);
  await page.goto('/notifications');
  await page.waitForLoadState('networkidle', { timeout: 30_000 });
  await page.goto('/search');
  await page.waitForLoadState('networkidle', { timeout: 30_000 });
  await page.waitForTimeout(1500);
  expectClean(probe);
  await page.context().close();
});

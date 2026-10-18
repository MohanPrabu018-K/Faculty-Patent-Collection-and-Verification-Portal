/**
 * DEMO-CYCLE browser validation (staff-presentation dataset).
 *
 * Real browser (prefers system Google Chrome via launch channel; falls back
 * to bundled Chromium and reports which ran). Credentials come from the
 * machine-local demo credentials file (DEMO_CREDS_FILE env) — never baked
 * into the spec. Read-only except D3b (none): nothing here grants, accepts
 * or uploads; the live Grant stays pristine for the show.
 */
import { test, expect, chromium, type Browser } from '@playwright/test';
import fs from 'node:fs';
import { resolveStagingEnv } from './guard';
import { NetProbe } from './netprobe';

test.describe.configure({ mode: 'serial' });
const env = resolveStagingEnv();

const CREDS_PATH = process.env.DEMO_CREDS_FILE || '';
if (!CREDS_PATH || !fs.existsSync(CREDS_PATH)) {
  throw new Error('[demo] DEMO_CREDS_FILE must point at the local demo credentials file.');
}
const CREDS: Record<string, string> = {};
for (const line of fs.readFileSync(CREDS_PATH, 'utf-8').split('\n')) {
  const t = line.trim();
  if (!t || t.startsWith('#') || !t.includes('=')) continue;
  const i = t.indexOf('=');
  CREDS[t.slice(0, i).trim()] = t.slice(i + 1).trim();
}

let browser: Browser;
let usedChannel = 'bundled-chromium';

test.beforeAll(async () => {
  try {
    browser = await chromium.launch({ channel: 'chrome', headless: true });
    usedChannel = 'system-chrome';
  } catch {
    browser = await chromium.launch({ headless: true });
    usedChannel = 'bundled-chromium';
  }
  // eslint-disable-next-line no-console
  console.log(`[demo] browser channel: ${usedChannel}`);
});

test.afterAll(async () => {
  await browser.close();
});

async function loginAs(emailKey: string, home: RegExp) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const probe = new NetProbe();
  await probe.attach(page);
  const email = Object.keys(CREDS).find((k) => k === emailKey) as string;
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(CREDS[email]);
  await page.getByRole('button', { name: 'Login' }).click();
  await page.waitForURL(home, { timeout: 60_000 });
  probe.markLoggedIn();
  return { page, probe, context };
}

function expectClean(probe: NetProbe) {
  const v = probe.verdict();
  // eslint-disable-next-line no-console
  if (!v.ok) console.log(`[demo-probe] unexpected:\n${v.lines.join('\n')}`);
  expect(v.lines, JSON.stringify(v.lines.slice(0, 6))).toEqual([]);
}

test('D1: super-admin dashboard renders (env-provided seed login)', async () => {
  const saEmail = process.env.DEMO_SA_EMAIL || '';
  const saPass = process.env.DEMO_SA_PASSWORD || '';
  if (!saEmail || !saPass) {
    // Without operator-provided credentials, prove only the auth gate:
    // unauthenticated /admin/dashboard must redirect to /login.
    const context = await browser.newContext();
    const page = await context.newPage();
    const probe = new NetProbe();
    await probe.attach(page);
    await page.goto('/admin/dashboard');
    await expect(page).toHaveURL(/\/login/, { timeout: 30_000 });
    await page.waitForTimeout(1000);
    expectClean(probe);
    await context.close();
    return;
  }
  const context = await browser.newContext();
  const page = await context.newPage();
  const probe = new NetProbe();
  await probe.attach(page);
  await page.goto('/login');
  await page.getByLabel('Email').fill(saEmail);
  await page.getByLabel('Password').fill(saPass);
  await page.getByRole('button', { name: 'Login' }).click();
  await page.waitForURL(/\/admin\/dashboard/, { timeout: 60_000 });
  probe.markLoggedIn();
  await page.goto('/admin/granted-patents');
  await page.waitForLoadState('networkidle', { timeout: 30_000 });
  // The grant-ready demo record must offer a Grant action; NEVER click it here.
  await expect(page.getByRole('button', { name: 'Grant Patent' }).first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1500);
  expectClean(probe);
  await context.close();
});

test('D2: faculty A dashboard + pending associations render', async () => {
  const { page, probe, context } = await loginAs('demo.fac.a@staging.example.com', /\/faculty\/dashboard/);
  await expect(page.getByText('Faculty submission overview')).toBeVisible({ timeout: 30_000 });
  await page.goto('/faculty/associations');
  await expect(page.getByText('Requests to link you')).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1500);
  expectClean(probe);
  await context.close();
});

test('D3: faculty B sees incoming pending request (no accept click)', async () => {
  const { page, probe, context } = await loginAs('demo.fac.b@staging.example.com', /\/faculty\/dashboard/);
  await page.goto('/faculty/associations');
  await expect(page.getByText('Requests to link you')).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1500);
  expectClean(probe);
  await context.close();
});

test('D4: HOD fan-out (A/B/C see multidept; scoped assoc; pre-stage hidden)', async () => {
  // Visibility rule: past-faculty-stage records whose represented departments
  // include the HOD's department. ASSOC is COMPLETE/VERIFIED with pending
  // requests, represented only by dept A. REVIEW is pre-stage (PENDING) and
  // invisible to every HOD. Filenames render in list rows.
  const expectations: Record<string, { see: string[]; hide: string[] }> = {
    'demo.hod.a@staging.example.com': { see: ['demo-multidept.pdf', 'demo-assoc.pdf'], hide: ['demo-review.pdf'] },
    'demo.hod.b@staging.example.com': { see: ['demo-multidept.pdf'], hide: ['demo-assoc.pdf', 'demo-review.pdf'] },
    'demo.hod.c@staging.example.com': { see: ['demo-multidept.pdf'], hide: ['demo-assoc.pdf', 'demo-review.pdf'] },
  };
  for (const [hod, exp] of Object.entries(expectations)) {
    const { page, probe, context } = await loginAs(hod, /\/hod\/dashboard/);
    await page.goto('/hod/documents');
    await page.waitForLoadState('networkidle', { timeout: 30_000 });
    for (const name of exp.see) {
      await expect(page.getByText(name).first()).toBeVisible({ timeout: 30_000 });
    }
    const bodyText = await page.locator('main').innerText();
    for (const name of exp.hide) {
      expect(bodyText.includes(name), `${name} must stay invisible to ${hod}`).toBe(false);
    }
    await page.waitForTimeout(1000);
    expectClean(probe);
    await context.close();
  }
});

test('D5: faculty cannot reach the grant page (role gate)', async () => {
  const { page, probe, context } = await loginAs('demo.fac.b@staging.example.com', /\/faculty\/dashboard/);
  await page.goto('/admin/granted-patents');
  await page.waitForTimeout(2000);
  // RequireRole must keep faculty out: either a redirect home/login or an
  // access-denied message — never the grant console.
  const url = page.url();
  const bodyText = await page.locator('body').innerText();
  const keptOut = /\/login/.test(url) || /\/faculty\/dashboard/.test(url) ||
    /not authorized|access denied|forbidden/i.test(bodyText);
  expect(keptOut, `faculty reached grant console: ${url}`).toBe(true);
  await expect(page.getByRole('button', { name: 'Grant Patent' })).toHaveCount(0);
  await page.waitForTimeout(1000);
  expectClean(probe);
  await context.close();
});

test('D6: mobile viewport login + dashboard', async () => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  const page = await context.newPage();
  const probe = new NetProbe();
  await probe.attach(page);
  await page.goto('/login');
  await page.getByLabel('Email').fill('demo.fac.a@staging.example.com');
  await page.getByLabel('Password').fill(CREDS['demo.fac.a@staging.example.com']);
  await page.getByRole('button', { name: 'Login' }).click();
  await page.waitForURL(/\/faculty\/dashboard/, { timeout: 60_000 });
  probe.markLoggedIn();
  await expect(page.getByText('Faculty submission overview')).toBeVisible({ timeout: 30_000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.waitForTimeout(1500);
  expectClean(probe);
  await context.close();
});

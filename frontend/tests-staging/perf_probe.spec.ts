/**
 * Performance probe (local measurement tooling, NOT a pass/fail suite).
 * For each page: request count + duplicate same-method+URL fetches,
 * navigation timing, FCP/LCP/CLS/longtasks via the Performance API.
 * Prints a compact table to stdout. Read-only (no submissions/grants).
 */
import { test, type Page } from '@playwright/test';
import fs from 'node:fs';
import { resolveStagingEnv } from './guard';

resolveStagingEnv();

const CREDS_PATH = process.env.DEMO_CREDS_FILE || '';
const CREDS: Record<string, string> = {};
if (CREDS_PATH && fs.existsSync(CREDS_PATH)) {
  for (const line of fs.readFileSync(CREDS_PATH, 'utf-8').split('\n')) {
    const t = line.trim();
    if (!t || t.startsWith('#') || !t.includes('=')) continue;
    const i = t.indexOf('=');
    CREDS[t.slice(0, i).trim()] = t.slice(i + 1).trim();
  }
}
const MANIFEST = 'C:\\Users\\mohan\\AppData\\Local\\Temp\\opencode\\fpp-demo\\demo_manifest.json';
const MAN = JSON.parse(fs.readFileSync(MANIFEST, 'utf-8'));
const REC = MAN.records['DEMO-MULTIDEPT-001'] as string;

async function loginAs(page: Page, email: string, home: RegExp) {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(CREDS[email]);
  await page.getByRole('button', { name: 'Login' }).click();
  await page.waitForURL(home, { timeout: 60_000 });
}

test('perf probe pages', async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  const reqs: { method: string; url: string; status: number }[] = [];
  page.on('response', (res) => {
    const url = res.url();
    if (url.includes('/api/v1/')) reqs.push({ method: res.request().method(), url: url.split('?')[0], status: res.status() });
  });

  async function measure(label: string, email: string, home: RegExp, gotoPath: string | null) {
    reqs.length = 0;
    if (email) await loginAs(page, email, home);
    if (gotoPath) await page.goto(gotoPath);
    await page.waitForLoadState('networkidle', { timeout: 30_000 });
    await page.waitForTimeout(1500);
    const metrics = await page.evaluate(() => {
      const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
      const paints: Record<string, number> = {};
      for (const p of performance.getEntriesByType('paint')) paints[p.name] = Math.round(p.startTime);
      let cls = 0;
      for (const e of performance.getEntriesByType('layout-shift') as (PerformanceEntry & { value: number; hadRecentInput: boolean })[]) {
        if (!e.hadRecentInput) cls += e.value;
      }
      const lcpList = performance.getEntriesByType('largest-contentful-paint') as (PerformanceEntry & { startTime: number })[];
      const lcp = lcpList.length ? Math.round(lcpList[lcpList.length - 1].startTime) : -1;
      const longtasks = performance.getEntriesByType('longtask').length;
      return {
        domContentLoaded: nav ? Math.round(nav.domContentLoadedEventEnd) : -1,
        load: nav ? Math.round(nav.loadEventEnd) : -1,
        fcp: paints['first-contentful-paint'] ?? -1,
        lcp,
        cls: Math.round(cls * 1000) / 1000,
        longtasks,
      };
    });
    const seen = new Map<string, number>();
    for (const r of reqs) seen.set(`${r.method} ${r.url}`, (seen.get(`${r.method} ${r.url}`) || 0) + 1);
    const dupes = [...seen.entries()].filter(([, n]) => n > 1);
    // eslint-disable-next-line no-console
    console.log(`[perf] ${label}: api_calls=${reqs.length} dupes=${dupes.length}${dupes.length ? ' ' + JSON.stringify(dupes) : ''} dcl=${metrics.domContentLoaded}ms load=${metrics.load}ms fcp=${metrics.fcp}ms lcp=${metrics.lcp}ms cls=${metrics.cls} longtasks=${metrics.longtasks}`);
  }

  await measure('faculty-dashboard', 'demo.fac.a@staging.example.com', /\/faculty\/dashboard/, null);
  await measure('faculty-records', '', /./, '/faculty/records');
  await measure('record-detail', '', /./, `/faculty/records/${REC}`);
  await measure('faculty-associations', '', /./, '/faculty/associations');
  await context.close();

  const context2 = await browser.newContext();
  const page2 = await context2.newPage();
  page2.on('response', (res) => {
    const url = res.url();
    if (url.includes('/api/v1/')) reqs.push({ method: res.request().method(), url: url.split('?')[0], status: res.status() });
  });
  const patch = async (label: string, email: string, home: RegExp, gotoPath: string | null) => {
    reqs.length = 0;
    await loginAs(page2, email, home);
    if (gotoPath) await page2.goto(gotoPath);
    await page2.waitForLoadState('networkidle', { timeout: 30_000 });
    await page2.waitForTimeout(1500);
    const m = await page2.evaluate(() => {
      const lcpList = performance.getEntriesByType('largest-contentful-paint') as (PerformanceEntry & { startTime: number })[];
      let cls = 0;
      for (const e of performance.getEntriesByType('layout-shift') as (PerformanceEntry & { value: number; hadRecentInput: boolean })[]) {
        if (!e.hadRecentInput) cls += e.value;
      }
      return { lcp: lcpList.length ? Math.round(lcpList[lcpList.length - 1].startTime) : -1, cls: Math.round(cls * 1000) / 1000 };
    });
    const seen = new Map<string, number>();
    for (const r of reqs) seen.set(`${r.method} ${r.url}`, (seen.get(`${r.method} ${r.url}`) || 0) + 1);
    const dupes = [...seen.entries()].filter(([, n]) => n > 1);
    // eslint-disable-next-line no-console
    console.log(`[perf] ${label}: api_calls=${reqs.length} dupes=${dupes.length}${dupes.length ? ' ' + JSON.stringify(dupes) : ''} lcp=${m.lcp}ms cls=${m.cls}`);
  };
  await patch('hod-documents', 'demo.hod.a@staging.example.com', /\/hod\/dashboard/, '/hod/documents');
  await context2.close();
});

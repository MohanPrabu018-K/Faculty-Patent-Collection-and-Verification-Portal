import { test, expect, type Page } from '@playwright/test';
import fs from 'fs';

export const BASE = 'http://localhost:5173';
export const API = 'http://127.0.0.1:8000';
export const RECORD_A = '7be9f118-ba87-462a-8d72-c98b688c6aa4';
export const RECORD_B = '76e50dba-6195-47b1-83a5-dde08b527854';
export const SDIR = 'tests/hardening-screenshots';
if (!fs.existsSync(SDIR)) fs.mkdirSync(SDIR, { recursive: true });

export const U = {
  fac: { e: 'test@faculty.edu', p: 'TestPass123!' },
  nag: { e: 'nagasai.boppana@faculty.edu', p: 'TestPass123!' },
  hod: { e: 'mv-hod@faculty.edu', p: 'TestPass123!' },
  admin: { e: 'admin@faculty.edu', p: 'AdminPass123!' },
};

export const PHASE_RESULTS: Array<{ phase: string; status: string; detail: string }> = [];
export const CONSOLE_ERRORS: Array<{ text: string; phase: string }> = [];
export const NETWORK_ERRORS: Array<{ url: string; status: number; phase: string }> = [];
export let currentPhase = 'init';
export function setPhase(p: string) { currentPhase = p; }

export function log(phase: string, status: 'PASS' | 'FAIL' | 'INFO', detail: string) {
  PHASE_RESULTS.push({ phase, status, detail });
  console.log(`  ${status} [${phase}] ${detail}`);
}

/**
 * Records a FAIL entry for any test that does not reach its `log()` call
 * (i.e. an `expect` throws first). Each spec file must call this once at
 * top level so its per-file summary - and the final verdict - can never
 * print PASS while a test in that file actually failed.
 */
export function installFailTracker() {
  test.afterEach(async ({}, testInfo) => {
    if (testInfo.status !== testInfo.expectedStatus) {
      const firstLine = testInfo.error?.message?.split('\n')[0] ?? String(testInfo.status);
      PHASE_RESULTS.push({ phase: currentPhase, status: 'FAIL', detail: `${testInfo.title} :: ${firstLine}` });
      console.log(`  FAIL [${currentPhase}] ${testInfo.title} :: ${firstLine}`);
    }
  });
}

export async function loginApi(page: Page, email: string, password: string): Promise<string> {
  // The login endpoint is rate-limited (10/IP/60s in prod, 1000/IP in E2E).
  // Retry transient 429/5xx with backoff; the final expect(200) still holds.
  let res = await page.request.post(`${API}/api/v1/auth/login`, { data: { email, password }, timeout: 60000 });
  for (const wait of [3000, 6000, 12000]) {
    if (res.status() === 200 || (res.status() < 429 && res.status() < 500)) break;
    await page.waitForTimeout(wait);
    res = await page.request.post(`${API}/api/v1/auth/login`, { data: { email, password }, timeout: 60000 });
  }
  expect(res.status(), `API login failed for ${email}`).toBe(200);
  const body = await res.json();
  const csrfToken = body.csrf_token ?? '';
  const setCookie = res.headers()['set-cookie'];
  if (setCookie) {
    const cookieHeader = Array.isArray(setCookie) ? setCookie : [setCookie];
    for (const cookie of cookieHeader) {
      const [pair] = cookie.split(';');
      const [name, ...valueParts] = pair.split('=');
      const value = valueParts.join('=');
      const isHttpOnly = cookie.toLowerCase().includes('httponly');
      await page.context().addCookies([
        { name, value, domain: '127.0.0.1', path: '/', httpOnly: isHttpOnly },
        { name, value, domain: 'localhost', path: '/', httpOnly: isHttpOnly },
      ]);
    }
  }
  return csrfToken;
}

export async function loginUi(page: Page, email: string, password: string) {
  // Rate-limit tolerant: on 429 the app stays on /login with an error alert.
  // Retry the submit (same project convention as tests/auth.setup.ts).
  // Guard against page/context closure during retries.
  // Use 'load' instead of 'networkidle' to avoid hangs from background requests.
  // waitForURL timeout is 30s to accommodate slowMo=3000 + workers=3 contention.
  // Use force:true on Login click to handle small viewports where button may be
  // partially outside the viewport due to slowMo scroll behavior.
  let lastErr: unknown = null;
  for (let attempt = 1; attempt <= 3; attempt++) {
    if (page.isClosed()) throw new Error(`Page closed during loginUi attempt ${attempt}`);
    await page.goto(`${BASE}/login`);
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Password').fill(password);
    await page.getByRole('button', { name: 'Login' }).click({ force: true });
    await page.waitForLoadState('load');
    try {
      await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 30000 });
      return;
    } catch (e) {
      lastErr = e;
      if (attempt < 3) {
        if (page.isClosed()) throw new Error('Page closed during loginUi retry wait');
        await page.waitForTimeout(5000);
      }
    }
  }
  throw lastErr;
}

export async function logoutUi(page: Page) {
  const btn = page.getByRole('button', { name: 'Logout' });
  if (await btn.count() > 0) {
    await btn.click();
    await page.waitForURL((u) => u.pathname.includes('/login'), { timeout: 15000 }).catch(() => {});
    await page.waitForLoadState('load');
  }
}

export async function ss(page: Page, name: string) {
  await page.screenshot({ path: `${SDIR}/${name}.png`, fullPage: false });
}

export async function verifyBackendHealth(): Promise<{ ok: boolean; latencyMs: number; detail: string }> {
  const start = Date.now();
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 5000);
    const res = await fetch(`${API}/healthz`, { signal: ctrl.signal });
    clearTimeout(timer);
    const latencyMs = Date.now() - start;
    const body = await res.json();
    return { ok: res.status === 200 && body.status === 'ok', latencyMs, detail: JSON.stringify(body) };
  } catch (e) {
    return { ok: false, latencyMs: Date.now() - start, detail: String(e) };
  }
}

export function attachConsole(page: Page) {
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      CONSOLE_ERRORS.push({ text: msg.text(), phase: currentPhase });
    }
  });
  page.on('pageerror', (err) => {
    CONSOLE_ERRORS.push({ text: `[pageerror] ${err.message}`, phase: currentPhase });
  });
}

export function attachNetwork(page: Page) {
  page.on('response', (res) => {
    const url = res.url();
    if (url.includes('/api/') && res.status() >= 400) {
      const status = res.status();
      const isExpected = [401, 403, 404, 409, 422].includes(status);
      if (!isExpected) {
        NETWORK_ERRORS.push({ url, status, phase: currentPhase });
      }
    }
  });
  page.on('requestfailed', (req) => {
    NETWORK_ERRORS.push({ url: req.url(), status: 0, phase: currentPhase });
  });
}

export function printSummary() {
  console.log('\n=== HARDENING E2E FINAL SUMMARY ===');
  const passed = PHASE_RESULTS.filter(r => r.status === 'PASS').length;
  const failed = PHASE_RESULTS.filter(r => r.status === 'FAIL').length;
  const info = PHASE_RESULTS.filter(r => r.status === 'INFO').length;
  for (const r of PHASE_RESULTS) {
    console.log(`  ${r.status} [${r.phase}] ${r.detail}`);
  }
  console.log(`\n  Total: ${passed} PASS / ${failed} FAIL / ${info} INFO`);
  console.log(`  Console errors captured: ${CONSOLE_ERRORS.length}`);
  console.log(`  Network errors captured: ${NETWORK_ERRORS.length}`);
  if (CONSOLE_ERRORS.length > 0) {
    console.log('  Unexpected console errors:');
    for (const e of CONSOLE_ERRORS) {
      console.log(`    [${e.phase}] ${e.text.substring(0, 120)}`);
    }
  }
  if (NETWORK_ERRORS.length > 0) {
    console.log('  Unexpected network errors:');
    for (const e of NETWORK_ERRORS) {
      console.log(`    [${e.phase}] ${e.status} ${e.url.substring(0, 100)}`);
    }
  }
}

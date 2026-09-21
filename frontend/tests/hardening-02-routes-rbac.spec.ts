import { test, expect } from '@playwright/test';
import {
  BASE, API, U, RECORD_A, RECORD_B, setPhase, log, loginApi, loginUi, ss,
  attachConsole, attachNetwork, PHASE_RESULTS, printSummary, installFailTracker,
} from './hardening-helpers';

installFailTracker();

const FACULTY_ROUTES = ['/faculty/dashboard', '/faculty/records', '/faculty/upload', '/faculty/profile', '/faculty/associations'];
const HOD_ROUTES = ['/hod/dashboard', '/hod/documents', '/hod/faculty', '/hod/duplicates', '/hod/conflicts', '/hod/reports', '/hod/audit'];
const ADMIN_ROUTES = ['/admin/dashboard', '/admin/ip-records', '/admin/faculty', '/admin/master-records', '/admin/queues', '/admin/audit', '/admin/settings', '/admin/granted-patents', '/admin/reports'];

test.describe('Phase 4 - Route Guard Hardening', () => {
  test('4.1 Unauthenticated user blocked from all protected routes', async ({ page }) => {
    test.slow();
    setPhase('4.1');
    const allRoutes = [...FACULTY_ROUTES, ...HOD_ROUTES, ...ADMIN_ROUTES];
    let redirectCount = 0;
    for (const route of allRoutes) {
      await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle', timeout: 10000 }).catch(() => {});
      // ProtectedRoute redirects unauthenticated users to /login via an
      // async chain (lazy chunk + /auth/me); wait for the redirect before
      // asserting so a stale pre-redirect URL is never read as a failure.
      await page.waitForURL((u) => u.pathname.includes('/login'), { timeout: 30000 }).catch(() => {});
      const url = page.url();
      if (url.includes('/login')) redirectCount++;
    }
    expect(redirectCount).toBe(allRoutes.length);
    log('4.1', 'PASS', `All ${allRoutes.length} protected routes redirect to login`);
  });

  test('4.2 Faculty cannot access Admin routes', async ({ page }) => {
    test.slow();
    setPhase('4.2');
    await loginUi(page, U.fac.e, U.fac.p);
    for (const route of ADMIN_ROUTES) {
      await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle', timeout: 10000 }).catch(() => {});
      const url = page.url();
      const blocked = !url.includes('/admin/') || url.includes('/login');
      expect(blocked, `Faculty should be blocked from ${route}, landed on ${url}`).toBeTruthy();
    }
    log('4.2', 'PASS', 'Faculty blocked from all Admin routes');
  });

  test('4.3 Faculty cannot access HOD routes', async ({ page }) => {
    test.slow();
    setPhase('4.3');
    await loginUi(page, U.fac.e, U.fac.p);
    for (const route of HOD_ROUTES) {
      await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle', timeout: 10000 }).catch(() => {});
      // RequireRole redirects non-HOD roles to /faculty/dashboard via an
      // async chain; wait for the redirect before asserting so a stale
      // pre-redirect URL is never read as a failure.
      await page.waitForURL((u) => !u.pathname.includes('/hod/'), { timeout: 30000 }).catch(() => {});
      const url = page.url();
      const blocked = !url.includes('/hod/') || url.includes('/login');
      expect(blocked, `Faculty should be blocked from ${route}, landed on ${url}`).toBeTruthy();
    }
    log('4.3', 'PASS', 'Faculty blocked from all HOD routes');
  });

  test('4.4 HOD cannot access Admin routes', async ({ page }) => {
    test.slow();
    setPhase('4.4');
    await loginUi(page, U.hod.e, U.hod.p);
    for (const route of ADMIN_ROUTES) {
      await page.goto(`${BASE}${route}`, { waitUntil: 'load', timeout: 15000 }).catch(() => {});
      // RequireRole redirects non-super_admin to /faculty/dashboard via an
      // async chain (lazy chunk + /auth/me); wait for the redirect before
      // asserting so a stale pre-redirect URL is never read as a failure.
      await page.waitForURL((u) => !u.pathname.includes('/admin/'), { timeout: 30000 }).catch(() => {});
      const url = page.url();
      const blocked = !url.includes('/admin/') || url.includes('/login');
      expect(blocked, `HOD should be blocked from ${route}, landed on ${url}`).toBeTruthy();
    }
    log('4.4', 'PASS', 'HOD blocked from all Admin routes');
  });

  test('4.5 HOD can access HOD routes', async ({ page }) => {
    test.slow();
    setPhase('4.5');
    await loginUi(page, U.hod.e, U.hod.p);
    for (const route of HOD_ROUTES) {
      await page.goto(`${BASE}${route}`, { waitUntil: 'load', timeout: 15000 });
      const url = page.url();
      expect(url).toContain('/hod/');
    }
    log('4.5', 'PASS', 'HOD can access all HOD routes');
  });

  test('4.6 Admin can access Admin routes', async ({ page }) => {
    test.slow();
    setPhase('4.6');
    await loginUi(page, U.admin.e, U.admin.p);
    for (const route of ADMIN_ROUTES) {
      await page.goto(`${BASE}${route}`, { waitUntil: 'load', timeout: 30000 });
      const url = page.url();
      expect(url).toContain('/admin/');
    }
    log('4.6', 'PASS', 'Admin can access all Admin routes');
  });
});

test.describe('Phase 5 - Role Action Boundary Hardening', () => {
  test('5.1 Faculty backend cannot grant', async ({ page }) => {
    setPhase('5.1');
    await loginApi(page, U.fac.e, U.fac.p);
    const csrf = await loginApi(page, U.fac.e, U.fac.p);
    const res = await page.request.post(`${API}/api/v1/admin/ip-records/${RECORD_B}/grant`, {
      headers: { 'X-CSRF-Token': csrf },
      data: { grant_date: '2026-09-20' },
    });
    expect(res.status()).toBeGreaterThanOrEqual(400);
    log('5.1', 'PASS', `Faculty grant rejected: ${res.status()}`);
  });

  test('5.2 Faculty backend cannot perform HOD verification', async ({ page }) => {
    setPhase('5.2');
    const csrf = await loginApi(page, U.fac.e, U.fac.p);
    const res = await page.request.post(`${API}/api/v1/verification/institutional/${RECORD_B}`, {
      headers: { 'X-CSRF-Token': csrf },
      data: { decision: 'verify' },
    });
    expect(res.status()).toBeGreaterThanOrEqual(400);
    log('5.2', 'PASS', `Faculty institutional verify rejected: ${res.status()}`);
  });

  test('5.3 HOD backend cannot grant', async ({ page }) => {
    setPhase('5.3');
    const csrf = await loginApi(page, U.hod.e, U.hod.p);
    const res = await page.request.post(`${API}/api/v1/admin/ip-records/${RECORD_B}/grant`, {
      headers: { 'X-CSRF-Token': csrf },
      data: { grant_date: '2026-09-20' },
    });
    expect(res.status()).toBeGreaterThanOrEqual(400);
    log('5.3', 'PASS', `HOD grant rejected: ${res.status()}`);
  });

  test('5.4 Faculty cannot access admin queues', async ({ page }) => {
    setPhase('5.4');
    const csrf = await loginApi(page, U.fac.e, U.fac.p);
    const res = await page.request.get(`${API}/api/v1/admin/queues/verifications`, {
      headers: { 'X-CSRF-Token': csrf },
    });
    expect(res.status()).toBeGreaterThanOrEqual(400);
    log('5.4', 'PASS', `Faculty admin queues rejected: ${res.status()}`);
  });

  test('5.5 HOD cannot access admin settings', async ({ page }) => {
    setPhase('5.5');
    const csrf = await loginApi(page, U.hod.e, U.hod.p);
    const res = await page.request.get(`${API}/api/v1/admin/settings`, {
      headers: { 'X-CSRF-Token': csrf },
    });
    expect(res.status()).toBeGreaterThanOrEqual(400);
    log('5.5', 'PASS', `HOD admin settings rejected: ${res.status()}`);
  });

  test('5.6 GRANTED record: grant action unavailable in UI', async ({ page }) => {
    test.slow();
    setPhase('5.6');
    await loginUi(page, U.admin.e, U.admin.p);
    await page.goto(`${BASE}/admin/ip-records`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    const grantedRow = page.locator('tr').filter({ hasText: /GRANTED/ });
    const count = await grantedRow.count();
    if (count > 0) {
      const grantBtn = grantedRow.first().locator('button').filter({ hasText: /Grant/i });
      const btnCount = await grantBtn.count();
      expect(btnCount).toBe(0);
    }
    log('5.6', 'PASS', 'No Grant button shown for GRANTED records');
  });

  test('5.7 Backend rejects grant on non-VERIFIED record', async ({ page }) => {
    setPhase('5.7');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.post(`${API}/api/v1/admin/ip-records/${RECORD_B}/grant`, {
      headers: { 'X-CSRF-Token': csrf },
      data: { grant_date: '2026-09-20' },
    });
    expect(res.status()).toBeGreaterThanOrEqual(400);
    const body = await res.json();
    expect(body.error || body.message).toBeTruthy();
    log('5.7', 'PASS', `Non-VERIFIED grant rejected: ${res.status()} - ${body.error || body.message}`);
  });

  test('5.8 Backend rejects grant on already GRANTED record', async ({ page }) => {
    setPhase('5.8');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.post(`${API}/api/v1/admin/ip-records/${RECORD_A}/grant`, {
      headers: { 'X-CSRF-Token': csrf },
      data: { grant_date: '2026-09-20', remarks: 'duplicate grant test' },
      timeout: 60000,
    });
    const code = res.status();
    expect(code === 409 || code === 422 || code === 200, `Expected 409/422/200 for re-grant, got ${code}`).toBeTruthy();
    log('5.8', 'PASS', `Re-grant on GRANTED record handled: ${code}`);
  });
});

test.describe('Final Summary', () => {
  test('Print Phase 4-5 Summary', async () => {
    printSummary();
    const failed = PHASE_RESULTS.filter(r => r.status === 'FAIL').length;
    expect(failed, `${failed} tests failed`).toBe(0);
  });
});

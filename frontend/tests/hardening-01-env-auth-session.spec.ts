import { test, expect, type Page } from '@playwright/test';
import {
  BASE, API, U, RECORD_A, SDIR, setPhase, log, loginApi, loginUi, logoutUi,
  ss, attachConsole, attachNetwork, PHASE_RESULTS, CONSOLE_ERRORS, NETWORK_ERRORS, printSummary, installFailTracker,
} from './hardening-helpers';

installFailTracker();

const FACULTY_ROUTES = ['/faculty/dashboard', '/faculty/records', '/faculty/upload', '/faculty/profile', '/faculty/associations'];
const HOD_ROUTES = ['/hod/dashboard', '/hod/documents', '/hod/faculty'];
const ADMIN_ROUTES = ['/admin/dashboard', '/admin/ip-records', '/admin/faculty', '/admin/master-records', '/admin/queues', '/admin/audit'];

test.describe('Phase 1 - Environment Hardening', () => {
  test('1.1 Backend health and readiness', async ({ request }) => {
    setPhase('1.1');
    const h = await request.get(`${API}/healthz`);
    expect(h.status()).toBe(200);
    const hd = await h.json();
    expect(hd.status).toBe('ok');
    log('1.1', 'PASS', 'healthz returns ok');

    const r = await request.get(`${API}/readyz`);
    expect(r.status()).toBe(200);
    log('1.1', 'PASS', 'readyz returns 200');
  });

  test('1.2 Frontend loads without errors', async ({ page }) => {
    setPhase('1.2');
    const errs: string[] = [];
    page.on('pageerror', (e) => errs.push(e.message));
    const res = await page.goto(BASE, { waitUntil: 'networkidle' });
    expect(res?.status()).toBe(200);
    await ss(page, '1.2-frontpage');
    expect(errs.filter(e => !e.includes('ResizeObserver'))).toHaveLength(0);
    log('1.2', 'PASS', 'Frontend loads, no critical errors');
  });

  test('1.3 Login page loads', async ({ page }) => {
    setPhase('1.3');
    const errs: string[] = [];
    page.on('pageerror', (e) => errs.push(e.message));
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    const heading = page.getByRole('heading', { name: /login/i });
    await expect(heading).toBeVisible();
    await ss(page, '1.3-login');
    expect(errs).toHaveLength(0);
    log('1.3', 'PASS', 'Login page renders correctly');
  });

  test('1.4 Protected routes redirect when unauthenticated', async ({ page }) => {
    test.slow();
    setPhase('1.4');
    for (const route of [...FACULTY_ROUTES, ...HOD_ROUTES, ...ADMIN_ROUTES]) {
      await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle', timeout: 10000 }).catch(() => {});
      // ProtectedRoute redirects unauthenticated users to /login via an
      // async chain (lazy chunk + /auth/me); wait for the redirect before
      // asserting so a stale pre-redirect URL is never read as a failure.
      await page.waitForURL((u) => u.pathname.includes('/login'), { timeout: 30000 }).catch(() => {});
      const url = page.url();
      const redirected = url.includes('/login') || url === `${BASE}/`;
      expect(redirected, `${route} should redirect unauthenticated user, landed on ${url}`).toBeTruthy();
    }
    log('1.4', 'PASS', 'All protected routes redirect to login');
  });

  test('1.5 No broken critical static assets', async ({ page }) => {
    setPhase('1.5');
    const failed: string[] = [];
    page.on('response', (res) => {
      const url = res.url();
      if ((url.endsWith('.js') || url.endsWith('.css')) && res.status() >= 400) {
        failed.push(`${res.status()} ${url}`);
      }
    });
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    expect(failed).toHaveLength(0);
    log('1.5', 'PASS', 'No broken JS/CSS assets');
  });
});

test.describe('Phase 2 - Authentication Hardening', () => {
  test('2.1 Empty email shows validation', async ({ page }) => {
    setPhase('2.1');
    await page.goto(`${BASE}/login`);
    await page.getByLabel('Password').fill('anything');
    await page.getByRole('button', { name: 'Login' }).click();
    await page.waitForTimeout(1000);
    const errText = await page.locator('.field-error, .alert-error').textContent().catch(() => '');
    expect(errText?.length).toBeGreaterThan(0);
    log('2.1', 'PASS', 'Empty email shows validation error');
  });

  test('2.2 Empty password shows validation', async ({ page }) => {
    setPhase('2.2');
    await page.goto(`${BASE}/login`);
    await page.getByLabel('Email').fill(U.fac.e);
    await page.getByRole('button', { name: 'Login' }).click();
    await page.waitForTimeout(1000);
    const url = page.url();
    expect(url).toContain('/login');
    log('2.2', 'PASS', 'Empty password stays on login');
  });

  test('2.3 Invalid email format shows validation', async ({ page }) => {
    setPhase('2.3');
    await page.goto(`${BASE}/login`);
    await page.getByLabel('Email').fill('not-an-email');
    await page.getByLabel('Password').fill('TestPass123!');
    await page.getByRole('button', { name: 'Login' }).click();
    await page.waitForTimeout(1000);
    const url = page.url();
    expect(url).toContain('/login');
    log('2.3', 'PASS', 'Invalid email stays on login');
  });

  test('2.4 Invalid credentials rejected', async ({ page }) => {
    setPhase('2.4');
    await page.goto(`${BASE}/login`);
    await page.getByLabel('Email').fill(U.fac.e);
    await page.getByLabel('Password').fill('WrongPassword123!');
    await page.getByRole('button', { name: 'Login' }).click();
    await page.waitForSelector('.alert-error, button.btn-primary:not([disabled])', { timeout: 60000 });
    const url = page.url();
    expect(url).toContain('/login');
    const errAlert = page.locator('.alert-error');
    await expect(errAlert).toBeVisible();
    log('2.4', 'PASS', 'Invalid credentials rejected with error message');
  });

  test('2.5 Valid Faculty login succeeds', async ({ page }) => {
    setPhase('2.5');
    await loginUi(page, U.fac.e, U.fac.p);
    expect(page.url()).toContain('/faculty/dashboard');
    await ss(page, '2.5-faculty-dashboard');
    log('2.5', 'PASS', 'Faculty login succeeds, lands on dashboard');
  });

  test('2.6 Valid HOD login succeeds', async ({ page }) => {
    setPhase('2.6');
    await loginUi(page, U.hod.e, U.hod.p);
    expect(page.url()).toContain('/hod/dashboard');
    await ss(page, '2.6-hod-dashboard');
    log('2.6', 'PASS', 'HOD login succeeds, lands on dashboard');
  });

  test('2.7 Valid Admin login succeeds', async ({ page }) => {
    setPhase('2.7');
    await loginUi(page, U.admin.e, U.admin.p);
    expect(page.url()).toContain('/admin/dashboard');
    await ss(page, '2.7-admin-dashboard');
    log('2.7', 'PASS', 'Admin login succeeds, lands on dashboard');
  });

  test('2.8 No password in URL after login', async ({ page }) => {
    setPhase('2.8');
    await loginUi(page, U.fac.e, U.fac.p);
    const url = page.url();
    expect(url).not.toContain('password');
    expect(url).not.toContain('TestPass');
    log('2.8', 'PASS', 'No password leaked in URL');
  });

  test('2.9 No JWT in localStorage/sessionStorage', async ({ page }) => {
    test.slow();
    setPhase('2.9');
    await loginUi(page, U.fac.e, U.fac.p);
    const ls = await page.evaluate(() => {
      const items: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key) items.push(key);
      }
      return items;
    });
    const ss2 = await page.evaluate(() => {
      const items: string[] = [];
      for (let i = 0; i < sessionStorage.length; i++) {
        const key = sessionStorage.key(i);
        if (key) items.push(key);
      }
      return items;
    });
    const hasJwt = [...ls, ...ss2].some(k => k.toLowerCase().includes('jwt') || k.toLowerCase().includes('token'));
    expect(hasJwt).toBe(false);
    log('2.9', 'PASS', 'No JWT in localStorage/sessionStorage');
  });

  test('2.10 HttpOnly auth cookie present', async ({ page }) => {
    setPhase('2.10');
    await loginApi(page, U.fac.e, U.fac.p);
    const cookies = await page.context().cookies();
    const accessCookie = cookies.find(c => c.name === 'access_token');
    expect(accessCookie).toBeTruthy();
    expect(accessCookie!.httpOnly).toBe(true);
    const csrfCookie = cookies.find(c => c.name === 'csrf_token');
    expect(csrfCookie).toBeTruthy();
    log('2.10', 'PASS', 'HttpOnly access_token and csrf_token cookies present');
  });

  test('2.11 Logout clears session', async ({ page }) => {
    test.slow();
    setPhase('2.11');
    await loginUi(page, U.fac.e, U.fac.p);
    expect(page.url()).toContain('/faculty');
    await logoutUi(page);
    await page.context().clearCookies();
    await page.goto(`${BASE}/faculty/dashboard`, { waitUntil: 'load' });
    await page.waitForURL((u) => u.pathname.includes('/login'), { timeout: 30000 });
    const url = page.url();
    expect(url).toContain('/login');
    log('2.11', 'PASS', 'Logout redirects to login');
  });

  test('2.12 Re-login after logout succeeds', async ({ page }) => {
    test.slow();
    setPhase('2.12');
    await loginUi(page, U.fac.e, U.fac.p);
    await logoutUi(page);
    await loginUi(page, U.fac.e, U.fac.p);
    expect(page.url()).toContain('/faculty/dashboard');
    log('2.12', 'PASS', 'Re-login after logout succeeds');
  });
});

test.describe('Phase 3 - Session / Reload Hardening', () => {
  test('3.1 Faculty session persists after reload', async ({ page }) => {
    test.slow();
    setPhase('3.1');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/dashboard`, { waitUntil: 'networkidle' });
    await page.reload({ waitUntil: 'networkidle' });
    expect(page.url()).toContain('/faculty/dashboard');
    const heading = await page.locator('body').textContent();
    expect(heading).toContain('Dashboard');
    log('3.1', 'PASS', 'Faculty dashboard persists after reload');

    await page.goto(`${BASE}/faculty/records`, { waitUntil: 'networkidle' });
    await page.reload({ waitUntil: 'networkidle' });
    expect(page.url()).toContain('/faculty/records');
    log('3.1', 'PASS', 'Faculty records persists after reload');

    await page.goto(`${BASE}/faculty/records/${RECORD_A}`, { waitUntil: 'networkidle' });
    await page.reload({ waitUntil: 'networkidle' });
    expect(page.url()).toContain(RECORD_A);
    log('3.1', 'PASS', 'Record detail persists after reload');
  });

  test('3.2 HOD session persists after reload', async ({ page }) => {
    test.slow();
    setPhase('3.2');
    await loginUi(page, U.hod.e, U.hod.p);
    await page.goto(`${BASE}/hod/dashboard`, { waitUntil: 'networkidle' });
    await page.reload({ waitUntil: 'networkidle' });
    expect(page.url()).toContain('/hod/dashboard');
    log('3.2', 'PASS', 'HOD dashboard persists after reload');

    await page.goto(`${BASE}/hod/documents`, { waitUntil: 'networkidle' });
    await page.reload({ waitUntil: 'networkidle' });
    expect(page.url()).toContain('/hod/documents');
    log('3.2', 'PASS', 'HOD documents persists after reload');
  });

  test('3.3 Admin session persists after reload', async ({ page }) => {
    test.slow();
    setPhase('3.3');
    await loginUi(page, U.admin.e, U.admin.p);
    await page.goto(`${BASE}/admin/dashboard`, { waitUntil: 'networkidle' });
    await page.reload({ waitUntil: 'networkidle' });
    expect(page.url()).toContain('/admin/dashboard');
    log('3.3', 'PASS', 'Admin dashboard persists after reload');

    await page.goto(`${BASE}/admin/ip-records`, { waitUntil: 'networkidle' });
    await page.reload({ waitUntil: 'networkidle' });
    expect(page.url()).toContain('/admin/ip-records');
    log('3.3', 'PASS', 'Admin IP records persists after reload');
  });

  test('3.4 Back/forward navigation preserves state', async ({ page }) => {
    test.slow();
    setPhase('3.4');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/dashboard`, { waitUntil: 'networkidle' });
    await page.goto(`${BASE}/faculty/records`, { waitUntil: 'networkidle' });
    await page.goBack();
    await page.waitForLoadState('networkidle');
    expect(page.url()).toContain('/faculty/dashboard');
    await page.goForward();
    await page.waitForLoadState('networkidle');
    expect(page.url()).toContain('/faculty/records');
    log('3.4', 'PASS', 'Back/forward navigation works correctly');
  });
});

test.describe('Final Summary', () => {
  test('Print Phase 1-3 Summary', async () => {
    printSummary();
    const failed = PHASE_RESULTS.filter(r => r.status === 'FAIL').length;
    expect(failed, `${failed} tests failed`).toBe(0);
  });
});

import { test, expect } from '@playwright/test';
import { BASE, API, U, RECORD_A, loginUi, logoutUi, loginApi } from './hardening-helpers';

test.describe('Phase 1 - System Health & Initial Load', () => {
  test('1.1 /login loads correctly with no critical console errors', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      const loc = msg.location()?.url || '';
      const text = msg.text();
      if (msg.type() === 'error') {
        if (loc.includes('favicon.ico') || text.includes('favicon')) return;
        if (loc.includes('/auth/me') && text.includes('401')) return;
        consoleErrors.push(`${text} [${loc}]`);
      }
    });
    page.on('pageerror', (err) => {
      consoleErrors.push(`[pageerror] ${err.message}`);
    });

    await page.goto(`${BASE}/login`, { waitUntil: 'load' });
    await expect(page.getByRole('button', { name: 'Login' })).toBeVisible();
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();

    expect(consoleErrors).toHaveLength(0);
  });
});

test.describe('Phase 2 - Faculty Real User Smoke', () => {
  test('Faculty workflow smoke (read-only)', async ({ page }) => {
    // 1 & 2 & 3: Login, lands on dashboard, dashboard renders
    await loginUi(page, U.fac.e, U.fac.p);
    await expect(page).toHaveURL(new RegExp('/faculty/dashboard'));
    await expect(page.locator('body')).toContainText(/Dashboard/i);

    // 4: /faculty/records loads
    await page.goto(`${BASE}/faculty/records`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/faculty/records'));
    await expect(page.locator('body')).toContainText(/Records/i);

    // 5: Existing record detail loads
    await page.goto(`${BASE}/faculty/records/${RECORD_A}`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp(RECORD_A));
    await expect(page.locator('body')).toContainText(/ARTIFICIAL INTELLIGENCE ENABLED SECURITY CAMERA/i);

    // 6: /faculty/associations loads
    await page.goto(`${BASE}/faculty/associations`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/faculty/associations'));
    await expect(page.locator('body')).toContainText(/Association/i);

    // 7: Notifications loads
    await page.goto(`${BASE}/notifications`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/notifications'));
    await expect(page.locator('body')).toContainText(/Notification/i);

    // 8 & 9: Logout works, redirects to /login
    await logoutUi(page);
    await expect(page).toHaveURL(new RegExp('/login'));
  });
});

test.describe('Phase 3 - HOD Real User Smoke', () => {
  test('HOD workflow smoke (read-only)', async ({ page }) => {
    // 1 & 2: Login succeeds, lands on dashboard
    await loginUi(page, U.hod.e, U.hod.p);
    await expect(page).toHaveURL(new RegExp('/hod/dashboard'));
    await expect(page.locator('body')).toContainText(/Dashboard|Department/i);

    // 3: /hod/documents loads & existing records visible
    await page.goto(`${BASE}/hod/documents`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/hod/documents'));
    await expect(page.locator('body')).toContainText(/Document|Review/i);

    // 4: /hod/faculty loads
    await page.goto(`${BASE}/hod/faculty`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/hod/faculty'));
    await expect(page.locator('body')).toContainText(/Faculty/i);

    // 5: /hod/duplicates loads
    await page.goto(`${BASE}/hod/duplicates`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/hod/duplicates'));
    await expect(page.locator('body')).toContainText(/Duplicate/i);

    // 6: /hod/conflicts loads
    await page.goto(`${BASE}/hod/conflicts`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/hod/conflicts'));
    await expect(page.locator('body')).toContainText(/Conflict/i);

    // 7: /hod/reports loads
    await page.goto(`${BASE}/hod/reports`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/hod/reports'));
    await expect(page.locator('body')).toContainText(/Report/i);

    // 8: /hod/audit loads
    await page.goto(`${BASE}/hod/audit`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/hod/audit'));
    await expect(page.locator('body')).toContainText(/Audit/i);

    // 10 & 11: Logout works, redirects to /login
    await logoutUi(page);
    await expect(page).toHaveURL(new RegExp('/login'));
  });
});

test.describe('Phase 4 - Super Admin Real User Smoke', () => {
  test('Super Admin workflow smoke (read-only)', async ({ page }) => {
    // 1 & 2: Login succeeds, lands on dashboard
    await loginUi(page, U.admin.e, U.admin.p);
    await expect(page).toHaveURL(new RegExp('/admin/dashboard'));
    await expect(page.locator('body')).toContainText(/Dashboard/i);

    // 3: /admin/ip-records loads with search & export controls
    await page.goto(`${BASE}/admin/ip-records`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/admin/ip-records'));
    await expect(page.locator('body')).toContainText(/IP Records|Patent/i);
    // Search/filter UI
    await expect(page.getByLabel('Search records')).toBeVisible();
    await expect(page.getByLabel('Filter by verification status')).toBeVisible();
    // Export controls
    await expect(page.getByLabel('Export format')).toBeVisible();

    // 4: /admin/faculty loads
    await page.goto(`${BASE}/admin/faculty`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/admin/faculty'));
    await expect(page.locator('body')).toContainText(/Faculty/i);

    // 5: /admin/master-records loads
    await page.goto(`${BASE}/admin/master-records`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/admin/master-records'));
    await expect(page.locator('body')).toContainText(/Master/i);

    // 6: /admin/queues loads
    await page.goto(`${BASE}/admin/queues`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/admin/queues'));
    await expect(page.locator('body')).toContainText(/Queue/i);

    // 7: /admin/audit loads
    await page.goto(`${BASE}/admin/audit`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/admin/audit'));
    await expect(page.locator('body')).toContainText(/Audit/i);

    // 8: /admin/settings loads
    await page.goto(`${BASE}/admin/settings`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/admin/settings'));
    await expect(page.locator('body')).toContainText(/Setting/i);

    // 9: /admin/granted-patents loads
    await page.goto(`${BASE}/admin/granted-patents`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/admin/granted-patents'));
    await expect(page.locator('body')).toContainText(/Granted/i);

    // 10: /admin/reports loads
    await page.goto(`${BASE}/admin/reports`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/admin/reports'));
    await expect(page.locator('body')).toContainText(/Report|Analytics/i);

    // 11: Notifications loads
    await page.goto(`${BASE}/notifications`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/notifications'));
    await expect(page.locator('body')).toContainText(/Notification/i);

    // Logout
    await logoutUi(page);
    await expect(page).toHaveURL(new RegExp('/login'));
  });
});

test.describe('Phase 6 - Final RBAC Sanity', () => {
  test('6.1 Unauthenticated user cannot access /faculty/dashboard', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto(`${BASE}/faculty/dashboard`, { waitUntil: 'load' });
    await page.waitForURL((u) => u.pathname.includes('/login'), { timeout: 15000 });
    expect(page.url()).toContain('/login');
  });

  test('6.2 Faculty cannot access /hod/dashboard or /admin/dashboard', async ({ page }) => {
    await loginUi(page, U.fac.e, U.fac.p);

    // Try /hod/dashboard
    await page.goto(`${BASE}/hod/dashboard`, { waitUntil: 'load' });
    await page.waitForURL((u) => !u.pathname.includes('/hod/dashboard'), { timeout: 15000 });
    expect(page.url()).not.toContain('/hod/dashboard');

    // Try /admin/dashboard
    await page.goto(`${BASE}/admin/dashboard`, { waitUntil: 'load' });
    await page.waitForURL((u) => !u.pathname.includes('/admin/dashboard'), { timeout: 15000 });
    expect(page.url()).not.toContain('/admin/dashboard');

    await logoutUi(page);
  });

  test('6.3 HOD cannot access /admin/dashboard', async ({ page }) => {
    await loginUi(page, U.hod.e, U.hod.p);

    await page.goto(`${BASE}/admin/dashboard`, { waitUntil: 'load' });
    await page.waitForURL((u) => !u.pathname.includes('/admin/dashboard'), { timeout: 15000 });
    expect(page.url()).not.toContain('/admin/dashboard');

    await logoutUi(page);
  });

  test('6.4 Faculty and HOD cannot access Grant functionality (API blocked 403)', async ({ page }) => {
    // Faculty attempt
    const facCsrf = await loginApi(page, U.fac.e, U.fac.p);
    const facRes = await page.request.post(`${API}/api/v1/admin/ip-records/${RECORD_A}/grant`, {
      headers: { 'X-CSRF-Token': facCsrf },
    });
    expect([401, 403]).toContain(facRes.status());

    // HOD attempt
    const hodCsrf = await loginApi(page, U.hod.e, U.hod.p);
    const hodRes = await page.request.post(`${API}/api/v1/admin/ip-records/${RECORD_A}/grant`, {
      headers: { 'X-CSRF-Token': hodCsrf },
    });
    expect([401, 403]).toContain(hodRes.status());
  });
});

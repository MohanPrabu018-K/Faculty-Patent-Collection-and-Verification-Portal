import { test, expect } from '@playwright/test';
import { BASE, U, loginUi, logoutUi } from './hardening-helpers';

test.describe('Task 4 - Role Smoke Validation', () => {
  test('Faculty smoke: login -> dashboard -> records -> associations -> logout', async ({ page }) => {
    // 1. Login
    await loginUi(page, U.fac.e, U.fac.p);
    await expect(page).toHaveURL(new RegExp('/faculty/dashboard'));
    await expect(page.locator('body')).toContainText(/Dashboard/i);

    // 2. Records
    await page.goto(`${BASE}/faculty/records`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/faculty/records'));
    await expect(page.locator('body')).toContainText(/Records/i);

    // 3. Associations
    await page.goto(`${BASE}/faculty/associations`, { waitUntil: 'load' });
    await expect(page).toHaveURL(new RegExp('/faculty/associations'));
    await expect(page.locator('body')).toContainText(/Association/i);

    // 4. Logout
    await logoutUi(page);
    await expect(page).toHaveURL(new RegExp('/login'));
  });

  test('HOD smoke: login -> dashboard -> HOD routes -> logout', async ({ page }) => {
    // 1. Login
    await loginUi(page, U.hod.e, U.hod.p);
    await expect(page).toHaveURL(new RegExp('/hod/dashboard'));
    await expect(page.locator('body')).toContainText(/Dashboard/i);

    // 2. HOD routes
    const hodRoutes = [
      '/hod/documents',
      '/hod/faculty',
      '/hod/duplicates',
      '/hod/conflicts',
      '/hod/reports',
      '/hod/audit',
    ];

    for (const route of hodRoutes) {
      await page.goto(`${BASE}${route}`, { waitUntil: 'load', timeout: 15000 });
      await expect(page).toHaveURL(new RegExp(route));
    }

    // 3. Logout
    await logoutUi(page);
    await expect(page).toHaveURL(new RegExp('/login'));
  });

  test('Super Admin smoke: login -> dashboard -> Admin routes -> logout', async ({ page }) => {
    // 1. Login
    await loginUi(page, U.admin.e, U.admin.p);
    await expect(page).toHaveURL(new RegExp('/admin/dashboard'));
    await expect(page.locator('body')).toContainText(/Dashboard/i);

    // 2. Admin routes
    const adminRoutes = [
      '/admin/ip-records',
      '/admin/faculty',
      '/admin/master-records',
      '/admin/queues',
      '/admin/audit',
      '/admin/settings',
      '/admin/granted-patents',
      '/admin/reports',
    ];

    for (const route of adminRoutes) {
      await page.goto(`${BASE}${route}`, { waitUntil: 'load', timeout: 15000 });
      await expect(page).toHaveURL(new RegExp(route));
    }

    // 3. Logout
    await logoutUi(page);
    await expect(page).toHaveURL(new RegExp('/login'));
  });
});

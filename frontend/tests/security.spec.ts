import { test, expect } from '@playwright/test';
import { USERS, API_URL } from './helpers';

test.describe('Unauthenticated sessions', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('unauthenticated user is redirected from protected routes', async ({ page }) => {
    await page.goto('/faculty/dashboard');
    await expect(page).toHaveURL(/\/login/);
    await page.goto('/admin/dashboard');
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe('Faculty sessions', () => {
  test.use({ storageState: 'tests/.auth/faculty.json' });

  test('faculty API token cannot access admin endpoints', async ({ page }) => {
    await page.goto('/faculty/dashboard');
    // page.request shares the browser context's session cookies, so the
    // authorization boundary is exercised through the real cookie auth flow.
    const response = await page.request.get(`${API_URL}/api/v1/admin/dashboard`);
    expect(response.status()).toBe(403);
  });

  test('no password or token appears in page text after login', async ({ page }) => {
    await page.goto('/faculty/dashboard');
    await expect(page).toHaveURL(/\/faculty\/dashboard/);
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).not.toContain(USERS.facultyA.password);
    expect(bodyText).not.toContain('access_token');
    expect(bodyText).not.toContain('eyJ');
  });

  test('auth cookie has HttpOnly attribute', async ({ page }) => {
    await page.goto('/faculty/dashboard');
    const cookies = await page.context().cookies();
    const authCookie = cookies.find((c) => c.name === 'access_token');
    expect(authCookie).toBeTruthy();
    expect(authCookie?.httpOnly).toBe(true);
  });

  test('CSRF token cookie is set after login', async ({ page }) => {
    await page.goto('/faculty/dashboard');
    const cookies = await page.context().cookies();
    const csrf = cookies.find((c) => c.name === 'csrf_token');
    expect(csrf).toBeTruthy();
  });

  test('logout invalidates session cookie', async ({ page }) => {
    await page.goto('/faculty/dashboard');
    await expect(page).toHaveURL(/\/faculty\/dashboard/);
    await page.getByRole('button', { name: 'Logout' }).click();
    await expect(page).toHaveURL(/\/login/);
    const cookies = await page.context().cookies();
    expect(cookies.find((c) => c.name === 'access_token')).toBeUndefined();
  });
});

test.describe('Admin sessions', () => {
  test.use({ storageState: 'tests/.auth/admin.json' });

  test('admin can access admin API endpoints', async ({ page }) => {
    await page.goto('/admin/dashboard');
    const response = await page.request.get(`${API_URL}/api/v1/admin/dashboard`);
    expect(response.status()).toBe(200);
  });
});
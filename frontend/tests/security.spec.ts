import { test, expect } from '@playwright/test';
import { USERS, loginViaUi, API_URL } from './helpers';

test.describe('Security & authorization', () => {
  test('unauthenticated user is redirected from protected routes', async ({ page }) => {
    await page.goto('/faculty/dashboard');
    await expect(page).toHaveURL(/\/login/);
    await page.goto('/admin/dashboard');
    await expect(page).toHaveURL(/\/login/);
  });

  test('faculty API token cannot access admin endpoints', async ({ page }) => {
    await loginViaUi(page, USERS.facultyA.email, USERS.facultyA.password);
    const response = await page.evaluate(async (apiUrl) => {
      const res = await fetch(`${apiUrl}/api/v1/admin/dashboard`, { credentials: 'include' });
      return res.status;
    }, API_URL);
    expect(response).toBe(403);
  });

  test('admin can access admin API endpoints', async ({ page }) => {
    await loginViaUi(page, USERS.admin.email, USERS.admin.password);
    const response = await page.evaluate(async (apiUrl) => {
      const res = await fetch(`${apiUrl}/api/v1/admin/dashboard`, { credentials: 'include' });
      return res.status;
    }, API_URL);
    expect(response).toBe(200);
  });

  test('no password or token appears in page text after login', async ({ page }) => {
    await loginViaUi(page, USERS.facultyA.email, USERS.facultyA.password);
    await expect(page).toHaveURL(/\/faculty\/dashboard/);
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).not.toContain(USERS.facultyA.password);
    expect(bodyText).not.toContain('access_token');
    expect(bodyText).not.toContain('eyJ');
  });

  test('auth cookie has HttpOnly attribute', async ({ page }) => {
    await loginViaUi(page, USERS.facultyA.email, USERS.facultyA.password);
    const cookies = await page.context().cookies();
    const authCookie = cookies.find((c) => c.name === 'access_token');
    expect(authCookie).toBeTruthy();
    expect(authCookie?.httpOnly).toBe(true);
  });

  test('CSRF token cookie is set after login', async ({ page }) => {
    await loginViaUi(page, USERS.facultyA.email, USERS.facultyA.password);
    const cookies = await page.context().cookies();
    const csrf = cookies.find((c) => c.name === 'csrf_token');
    expect(csrf).toBeTruthy();
  });

  test('logout invalidates session cookie', async ({ page }) => {
    await loginViaUi(page, USERS.facultyA.email, USERS.facultyA.password);
    await expect(page).toHaveURL(/\/faculty\/dashboard/);
    await page.getByRole('button', { name: 'Logout' }).click();
    await expect(page).toHaveURL(/\/login/);
    const cookies = await page.context().cookies();
    expect(cookies.find((c) => c.name === 'access_token')).toBeUndefined();
  });
});

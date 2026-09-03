import { expect, type Page } from '@playwright/test';

export const API_URL = process.env.API_URL || 'http://localhost:8000';
export const FRONTEND_URL = process.env.FRONTEND_URL || 'http://localhost:5173';

export const USERS = {
  facultyA: { email: 'test@faculty.edu', password: 'TestPass123!', fullName: 'Test Faculty', role: 'faculty', facultyId: 'FAC001' },
  facultyB: { email: 'faculty2@faculty.edu', password: 'TestPass456!', fullName: 'Faculty Two', role: 'faculty', facultyId: 'FAC002' },
  admin: { email: 'admin@faculty.edu', password: 'AdminPass123!', fullName: 'Admin User', role: 'super_admin' },
} as const;

export async function loginViaApi(page: Page, email: string, password: string) {
  const response = await page.request.post(`${API_URL}/api/v1/auth/login`, {
    data: { email, password },
  });
  expect(response.status()).toBe(200);
  // Playwright's APIRequestContext does not share cookies with the browser context,
  // so mirror the auth cookie into the browser context.
  const setCookie = response.headers()['set-cookie'];
  if (setCookie) {
    const cookieHeader = Array.isArray(setCookie) ? setCookie : [setCookie];
    for (const cookie of cookieHeader) {
      const [pair] = cookie.split(';');
      const [name, ...valueParts] = pair.split('=');
      const value = valueParts.join('=');
      await page.context().addCookies([
        { name, value, domain: '127.0.0.1', path: '/', httpOnly: cookie.includes('HttpOnly') },
      ]);
    }
  }
}

export async function loginViaUi(page: Page, email: string, password: string) {
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Login' }).click();
  // Block until the httpOnly access_token cookie is actually committed to the
  // browser context. Without this, a caller that immediately issues an
  // authenticated request (page.request / in-page fetch) races the login
  // response and reaches the API unauthenticated (the app returns 400 for
  // missing credentials).
  await expect
    .poll(
      async () => (await page.context().cookies()).some((c) => c.name === 'access_token'),
      { timeout: 15_000 },
    )
    .toBe(true);
}

export async function logoutViaUi(page: Page) {
  await page.getByRole('button', { name: 'Logout' }).click();
}

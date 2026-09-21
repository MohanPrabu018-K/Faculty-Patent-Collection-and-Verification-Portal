import { expect, type Page } from '@playwright/test';

export const API_URL = process.env.API_URL || 'http://localhost:8000';
export const FRONTEND_URL = process.env.FRONTEND_URL || 'http://localhost:5173';

export const USERS = {
  facultyA: { email: 'test@faculty.edu', password: 'TestPass123!', fullName: 'Test Faculty', role: 'faculty', facultyId: 'FAC001' },
  facultyB: { email: 'faculty2@faculty.edu', password: 'TestPass456!', fullName: 'Faculty Two', role: 'faculty', facultyId: 'FAC002' },
  admin: { email: 'admin@faculty.edu', password: 'AdminPass123!', fullName: 'Admin User', role: 'super_admin' },
  hod: { email: 'mv-hod@faculty.edu', password: 'TestPass123!', fullName: 'mv-hod-001', role: 'hod_admin' },
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
  // Under concurrent load (e.g. e2e-pipeline saturating Neon DB connections),
  // the browser's fetch() to /api/v1/auth/login can fail. Retry up to 3 times
  // with a delay so the DB pool recovers between attempts.
  for (let attempt = 1; attempt <= 3; attempt++) {
    await page.goto('/login');
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Password').fill(password);
    await page.getByRole('button', { name: 'Login' }).click();
    await page.waitForLoadState('networkidle');

    const hasToken = (await page.context().cookies()).some(
      (c) => c.name === 'access_token',
    );
    if (hasToken) return;
    // Wait longer on retry — the e2e-pipeline's Neon-heavy processing can take
    // ~20 s to complete, so 10 s between attempts gives the pool time to drain.
    if (attempt < 3) await page.waitForTimeout(10_000);
  }
  throw new Error('loginViaUi: login failed after 3 attempts');
}

export async function logoutViaUi(page: Page) {
  await page.getByRole('button', { name: 'Logout' }).click();
}
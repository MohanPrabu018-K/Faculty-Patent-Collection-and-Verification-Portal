import { test, expect } from '@playwright/test';
import { USERS, loginViaUi } from './helpers';

test.describe('Authentication', () => {
  test('login page loads with required fields', async ({ page }) => {
    await page.goto('/login');
    await expect(page).toHaveTitle(/Faculty/);
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Login' })).toBeVisible();
  });

  test('empty email is rejected', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Password').fill('whatever123');
    await page.getByRole('button', { name: 'Login' }).click();
    await expect(page.locator('.field-error').first()).toBeVisible();
  });

  test('empty password is rejected', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Email').fill('test@faculty.edu');
    await page.getByRole('button', { name: 'Login' }).click();
    await expect(page.locator('.field-error').first()).toBeVisible();
  });

  test('invalid email is rejected', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Email').fill('not-an-email');
    await page.getByLabel('Password').fill('TestPass123!');
    // The native HTML5 email input rejects the malformed value before submission.
    const isValid = await page.getByLabel('Email').evaluate((el: HTMLInputElement) => el.validity.valid);
    expect(isValid).toBe(false);
    // Submit does not navigate away.
    await page.getByRole('button', { name: 'Login' }).click();
    await expect(page).toHaveURL(/\/login/);
  });

  test('invalid password is rejected with backend error', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Email').fill(USERS.facultyA.email);
    await page.getByLabel('Password').fill('WrongPassword123!');
    await page.getByRole('button', { name: 'Login' }).click();
    await expect(page.locator('.alert-error')).toBeVisible();
  });

  test('valid faculty login redirects to faculty dashboard', async ({ page }) => {
    await loginViaUi(page, USERS.facultyA.email, USERS.facultyA.password);
    await expect(page).toHaveURL(/\/faculty\/dashboard/);
    await expect(page.getByText(USERS.facultyA.fullName)).toBeVisible();
    await expect(page.getByText('Faculty submission overview')).toBeVisible();
  });

  test('valid admin login redirects to admin dashboard', async ({ page }) => {
    await loginViaUi(page, USERS.admin.email, USERS.admin.password);
    await expect(page).toHaveURL(/\/admin\/dashboard/);
    await expect(page.getByText(USERS.admin.fullName)).toBeVisible();
    // Admin sees the admin navigation link (role-based visibility).
    await expect(page.getByRole('link', { name: 'Review Queues' })).toBeVisible();
  });
});

test.describe('Authenticated session handling', () => {
  test.use({ storageState: 'tests/.auth/faculty.json' });

  test('JWT is not exposed in localStorage/sessionStorage after login', async ({ page }) => {
    await page.goto('/faculty/dashboard');
    await expect(page).toHaveURL(/\/faculty\/dashboard/);
    const storage = await page.evaluate(() => ({
      local: { ...localStorage },
      session: { ...sessionStorage },
    }));
    const localJson = JSON.stringify(storage.local);
    const sessionJson = JSON.stringify(storage.session);
    expect(localJson).not.toContain('access_token');
    expect(sessionJson).not.toContain('access_token');
  });

  test('faculty logout redirects to login and protects dashboard', async ({ page }) => {
    await page.goto('/faculty/dashboard');
    await expect(page).toHaveURL(/\/faculty\/dashboard/);
    await page.getByRole('button', { name: 'Logout' }).click();
    await expect(page).toHaveURL(/\/login/);
    await page.goto('/faculty/dashboard');
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe('Admin session handling', () => {
  test.use({ storageState: 'tests/.auth/admin.json' });

  test('admin logout redirects to login', async ({ page }) => {
    await page.goto('/faculty/dashboard');
    await expect(page).toHaveURL(/\/faculty\/dashboard/);
    await page.getByRole('button', { name: 'Logout' }).click();
    await expect(page).toHaveURL(/\/login/);
  });
});
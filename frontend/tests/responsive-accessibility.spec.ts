import { test, expect } from '@playwright/test';
import { USERS } from './helpers';

test.describe('Responsive layout', () => {
  test('login page has no horizontal overflow across viewports', async ({ page }) => {
    await page.goto('/login');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    expect(overflow).toBe(false);
  });

  test.describe('Logged in', () => {
    test.use({ storageState: 'tests/.auth/faculty.json' });

    test('dashboard renders without horizontal overflow after login', async ({ page }) => {
      await page.goto('/faculty/dashboard');
      await expect(page).toHaveURL(/\/faculty\/dashboard/);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
      expect(overflow).toBe(false);
    });

    test('mobile navigation is visible on small viewport', async ({ page }) => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto('/faculty/dashboard');
      await expect(page).toHaveURL(/\/faculty\/dashboard/);
      await expect(page.locator('.mobile-nav')).toBeVisible();
    });
  });
});

test.describe('Accessibility basics', () => {
  test('login inputs have labels and page has title', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();
    const title = await page.title();
    expect(title.length).toBeGreaterThan(0);
  });

  test.describe('Logged in', () => {
    test.use({ storageState: 'tests/.auth/faculty.json' });

    test('buttons have accessible names on dashboard', async ({ page }) => {
      await page.goto('/faculty/dashboard');
      await expect(page).toHaveURL(/\/faculty\/dashboard/);
      const buttons = page.locator('button');
      const count = await buttons.count();
      for (let i = 0; i < count; i++) {
        const accessibleName = await buttons.nth(i).getAttribute('aria-label');
        const text = (await buttons.nth(i).innerText()).trim();
        expect(Boolean(accessibleName) || Boolean(text)).toBe(true);
      }
    });
  });

  test('keyboard navigation: login via keyboard', async ({ page }) => {
    // Under concurrent load (e2e-pipeline saturating Neon DB), the browser's
    // fetch() to /api/v1/auth/login can fail. Retry the full keyboard-login
    // flow up to 3 times so the DB pool recovers between attempts.
    test.setTimeout(90_000);

    for (let attempt = 1; attempt <= 3; attempt++) {
      await page.goto('/login');
      await page.getByLabel('Email').focus();
      await page.keyboard.type(USERS.facultyA.email);
      await page.getByLabel('Password').focus();
      await page.keyboard.type(USERS.facultyA.password);
      await page.getByRole('button', { name: 'Login' }).focus();
      await page.keyboard.press('Enter');

      try {
        await expect(page).toHaveURL(/\/faculty\/dashboard/, { timeout: 15_000 });
        return;
      } catch {
        if (attempt === 3) throw new Error('keyboard login failed after 3 attempts');
        await page.waitForTimeout(5000);
      }
    }
  });
});
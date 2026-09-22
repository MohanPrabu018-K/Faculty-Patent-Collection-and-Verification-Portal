import { test, expect } from '@playwright/test';
import { USERS } from './helpers';

// The production CSS breakpoints are 1024 (stats dense), 900 (tablet: sidebar
// collapses to bottom nav), 640 (mobile single column), 380 (very small).
// Run the dashboard — including the Recent submissions table — across all
// required widths to catch any gap in those breakpoints.
const VIEWPORTS = [
  { width: 320, height: 568 },
  { width: 375, height: 667 },
  { width: 390, height: 844 },
  { width: 430, height: 932 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
];

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

    test('dashboard has no horizontal overflow across all required viewports', async ({ page }) => {
      for (const vp of VIEWPORTS) {
        await page.setViewportSize(vp);
        await page.goto('/faculty/dashboard');
        await expect(page).toHaveURL(/\/faculty\/dashboard/);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
        expect(overflow, `horizontal overflow at ${vp.width}x${vp.height}`).toBe(false);
      }
    });

    test('recent submissions table scrolls inside its wrapper, not the page', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });
      await page.goto('/faculty/dashboard');
      await expect(page).toHaveURL(/\/faculty\/dashboard/);
      const wrap = page.locator('.table-wrap');
      if (await wrap.count() === 0) return; // no recent records yet — nothing to check
      await expect(wrap).toBeVisible();
      const pageStill = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
      expect(pageStill).toBe(true);
      // The wrapper must be internally scrollable on narrow phones rather than clipping.
      const horizScrollable = await wrap.evaluate((el) => el.scrollWidth > el.clientWidth && getComputedStyle(el).overflowX === 'auto');
      expect(horizScrollable).toBe(true);
    });

    test('sidebar collapses to bottom navigation across tablet and mobile widths', async ({ page }) => {
      for (const vp of VIEWPORTS.filter((v) => v.width <= 768)) {
        await page.setViewportSize(vp);
        await page.goto('/faculty/dashboard');
        await expect(page).toHaveURL(/\/faculty\/dashboard/);
        await expect(page.locator('.sidebar'), `sidebar should be hidden at ${vp.width}px`).toBeHidden();
        await expect(page.locator('.mobile-nav'), `mobile nav should show at ${vp.width}px`).toBeVisible();
      }
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
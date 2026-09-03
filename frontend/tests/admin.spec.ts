import { test, expect } from '@playwright/test';
import { USERS, loginViaUi } from './helpers';

test.describe('Admin pages', () => {
  test.beforeEach(async ({ page }) => {
    await loginViaUi(page, USERS.admin.email, USERS.admin.password);
    await expect(page).toHaveURL(/\/faculty\/dashboard/);
  });

  test('admin dashboard renders statistics', async ({ page }) => {
    await page.goto('/admin/dashboard');
    await expect(page.getByText('Admin Dashboard')).toBeVisible();
    await expect(page.getByText('Total faculty')).toBeVisible();
    await expect(page.getByText('Total IP records')).toBeVisible();
  });

  test('admin faculty page loads with data', async ({ page }) => {
    await page.goto('/admin/faculty');
    await expect(page.getByText('Faculty Management')).toBeVisible();
    await expect(page.locator('.json-box')).toBeVisible();
  });

  test('admin IP records page loads with search and filter', async ({ page }) => {
    await page.goto('/admin/ip-records');
    await expect(page.getByText('IP Records')).toBeVisible();
    await expect(page.getByLabel('Search records')).toBeVisible();
    await expect(page.getByLabel('Filter by verification status')).toBeVisible();
    // selecting a filter should update the result count text
    await page.getByLabel('Filter by verification status').selectOption({ label: 'Verified' });
    await expect(page.getByText(/records shown/)).toBeVisible();
  });

  test('admin queues page loads all four queue sections', async ({ page }) => {
    await page.goto('/admin/queues');
    await expect(page.getByText('Verification Review')).toBeVisible();
    await expect(page.getByText('Duplicate Review')).toBeVisible();
    await expect(page.getByText('Conflict Review')).toBeVisible();
    await expect(page.getByText('Association / Contributor Review')).toBeVisible();
  });

  test('admin navigation links work', async ({ page }) => {
    await page.goto('/admin/dashboard');
    await page.getByRole('link', { name: 'Admin' }).click();
    await expect(page).toHaveURL(/\/admin\/dashboard/);
  });
});

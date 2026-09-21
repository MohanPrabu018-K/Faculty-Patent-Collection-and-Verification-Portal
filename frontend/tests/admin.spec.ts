import { test, expect } from '@playwright/test';

function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@faculty.edu`;
}

test.describe('Admin pages', () => {
  test.use({ storageState: 'tests/.auth/admin.json' });

  test('admin dashboard renders statistics', async ({ page }) => {
    await page.goto('/admin/dashboard');
    await expect(page.getByRole('heading', { name: 'Admin Dashboard' })).toBeVisible();
    await expect(page.getByText('Total faculty')).toBeVisible();
    await expect(page.getByText('Total IP records')).toBeVisible();
  });

  test('admin faculty page loads with data', async ({ page }) => {
    await page.goto('/admin/faculty');
    await expect(page.getByRole('heading', { name: 'Faculty Management' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add faculty' })).toBeVisible();
    await expect(page.locator('.data-table')).toBeVisible();
  });

  test('admin IP records page loads with search and filter', async ({ page }) => {
    await page.goto('/admin/ip-records');
    await expect(page.getByRole('heading', { name: 'IP Records' })).toBeVisible();
    await expect(page.getByLabel('Search records')).toBeVisible();
    await expect(page.getByLabel('Filter by verification status')).toBeVisible();
    // selecting a filter should update the result count text (format: "N total Â· M on page")
    await page.getByLabel('Filter by verification status').selectOption({ label: 'Verified' });
    await expect(page.getByText(/\d+ total/)).toBeVisible({ timeout: 15_000 });
  });

  test('admin queues page loads all four queue sections', async ({ page }) => {
    await page.goto('/admin/queues');
    await expect(page.getByRole('heading', { name: 'Verification Review' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Duplicate Review' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Conflict Review' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Association / Contributor Review' })).toBeVisible();
  });

  test('admin navigation links work', async ({ page }) => {
    await page.goto('/admin/dashboard');
    await page.getByRole('link', { name: 'Review Queues' }).click();
    await expect(page).toHaveURL(/\/admin\/queues/);
  });

  test('blank create password shows generated temporary password once', async ({ page }) => {
    const email = uniqueEmail('tmpgen');
    await page.goto('/admin/faculty');
    await page.getByRole('button', { name: 'Add faculty' }).click();
    await page.getByLabel(/Full name/).fill(`TMP ${email}`);
    await page.getByLabel(/Email/).fill(email);
    await page.getByRole('button', { name: 'Create' }).click();
    await page.waitForTimeout(5_000);
    await expect(page.getByText(/temporary password was generated/i)).toBeVisible();
    await expect(page.locator('code.toolbar-input')).toBeVisible();
    const password = (await page.locator('code.toolbar-input').textContent()) ?? '';
    expect(password.length).toBeGreaterThanOrEqual(16);
    expect(password).not.toBe('ChangeMe123!');
    await page.getByRole('button', { name: 'Done' }).click();
    await expect(page.getByText(/temporary password was generated/i)).toHaveCount(0);
  });
});

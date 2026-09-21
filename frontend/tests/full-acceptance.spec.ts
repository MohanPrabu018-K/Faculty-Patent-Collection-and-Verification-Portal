import { test, expect } from '@playwright/test';

test.describe('SUPER ADMIN full acceptance', () => {
  test.use({ storageState: 'tests/.auth/admin.json' });

  test('dashboard renders KPIs and activity', async ({ page }) => {
    await page.goto('/admin/dashboard');
    await expect(page.getByRole('heading', { name: 'Admin Dashboard' })).toBeVisible();
    await expect(page.getByText('Total faculty')).toBeVisible();
    await expect(page.getByText('Total IP records')).toBeVisible();
    await expect(page.getByText('Pending verifications')).toBeVisible();
  });

  test('faculty page loads with table', async ({ page }) => {
    await page.goto('/admin/faculty');
    await expect(page.getByRole('heading', { name: 'Faculty Management' })).toBeVisible();
    await expect(page.locator('.data-table')).toBeVisible();
  });

  test('IP records page loads with status filter and search', async ({ page }) => {
    await page.goto('/admin/ip-records');
    await expect(page.getByRole('heading', { name: 'IP Records' })).toBeVisible();
    await expect(page.getByLabel('Search records')).toBeVisible();
    await expect(page.getByLabel('Filter by verification status')).toBeVisible();
    await page.getByLabel('Filter by verification status').selectOption({ label: 'Verified' });
    await expect(page.getByText(/\d+ total/)).toBeVisible({ timeout: 15_000 });
  });

  test('IP records COMPLETED_WITH_ERRORS processing status filter', async ({ page }) => {
    await page.goto('/admin/ip-records');
    await expect(page.getByLabel('Filter by processing status')).toBeVisible();
    await page.getByLabel('Filter by processing status').selectOption({ label: 'Completed with errors' });
    await expect(page.getByText(/\d+ total/)).toBeVisible({ timeout: 15_000 });
  });

  test('IP records search works', async ({ page }) => {
    await page.goto('/admin/ip-records');
    await page.getByLabel('Search records').fill('US101');
    await expect(page.getByText(/\d+ total/)).toBeVisible({ timeout: 15_000 });
  });

  test('master records page loads', async ({ page }) => {
    await page.goto('/admin/master-records');
    await expect(page.getByRole('heading', { name: /Master/ })).toBeVisible({ timeout: 10_000 });
  });

  test('queues page loads all four sections', async ({ page }) => {
    await page.goto('/admin/queues');
    await expect(page.getByRole('heading', { name: 'Verification Review' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Duplicate Review' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Conflict Review' })).toBeVisible();
    await expect(page.getByRole('heading', { name: /Association/ })).toBeVisible();
  });

  test('reports page loads', async ({ page }) => {
    await page.goto('/admin/reports');
    await expect(page.getByRole('heading', { name: /Institution Overview/ })).toBeVisible({ timeout: 10_000 });
  });

  test('search page loads', async ({ page }) => {
    await page.goto('/search');
    await expect(page.getByRole('heading', { name: /Search/ })).toBeVisible({ timeout: 15_000 });
    await page.getByPlaceholder(/search/i).fill('patent');
    await expect(page.locator('.data-table, .muted, table')).toBeVisible({ timeout: 15_000 });
  });

  test('notifications page loads', async ({ page }) => {
    await page.goto('/notifications');
    await expect(page.locator('h1').first()).toBeVisible({ timeout: 15_000 });
  });

  test('granted patents page loads', async ({ page }) => {
    await page.goto('/admin/granted-patents');
    await expect(page.getByRole('heading', { name: /Granted|Patents/ })).toBeVisible({ timeout: 10_000 });
  });

  test('navigation links work', async ({ page }) => {
    await page.goto('/admin/dashboard');
    await page.getByRole('link', { name: 'Review Queues' }).click();
    await expect(page).toHaveURL(/\/admin\/queues/);
  });

  test('admin logout', async ({ page }) => {
    await page.goto('/admin/dashboard');
    await page.getByRole('button', { name: /logout|sign out/i }).click();
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe('FACULTY full acceptance', () => {
  test.use({ storageState: 'tests/.auth/faculty.json' });

  test('dashboard renders stats and navigation', async ({ page }) => {
    await page.goto('/faculty/dashboard');
    await expect(page.getByRole('heading', { name: /Faculty submission overview/ })).toBeVisible();
    await expect(page.getByText('Summary')).toBeVisible();
  });

  test('records page loads with search and status filter', async ({ page }) => {
    await page.goto('/faculty/records');
    await expect(page.getByRole('heading', { name: /Records|My Records/ })).toBeVisible();
    await expect(page.locator('.data-table')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByLabel(/status/i)).toBeVisible();
  });

  test('upload page shows file picker', async ({ page }) => {
    await page.goto('/faculty/upload');
    await expect(page.getByRole('heading', { name: /Upload/ })).toBeVisible();
    await expect(page.locator('input[type="file"]')).toBeVisible();
  });

  test('search page loads', async ({ page }) => {
    await page.goto('/search');
    await expect(page.getByRole('heading', { name: /Search/ })).toBeVisible({ timeout: 10_000 });
  });

  test('faculty cannot access admin routes', async ({ page }) => {
    await page.goto('/admin/dashboard');
    await expect(page).not.toHaveURL(/\/admin\/dashboard/);
  });

  test('faculty cannot access hod routes', async ({ page }) => {
    await page.goto('/hod/dashboard');
    await expect(page).not.toHaveURL(/\/hod\/dashboard/);
  });

  test('notifications page loads', async ({ page }) => {
    await page.goto('/notifications');
    await expect(page.locator('h1').first()).toBeVisible({ timeout: 15_000 });
  });

  test('faculty logout', async ({ page }) => {
    await page.goto('/faculty/dashboard');
    await page.getByRole('button', { name: /logout|sign out/i }).click();
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe('HOD full acceptance', () => {
  test.use({ storageState: 'tests/.auth/hod.json' });

  test('HOD dashboard renders dept-scoped stats', async ({ page }) => {
    await page.goto('/hod/dashboard');
    await expect(page.getByRole('heading', { name: /Department Dashboard/ })).toBeVisible({ timeout: 15_000 });
  });

  test('HOD documents page loads dept-scoped records', async ({ page }) => {
    await page.goto('/hod/documents');
    await expect(page.getByRole('heading', { name: /Documents|Records/ })).toBeVisible({ timeout: 10_000 });
  });

  test('HOD faculty page loads', async ({ page }) => {
    await page.goto('/hod/faculty');
    await expect(page.getByRole('heading', { name: /Faculty/ })).toBeVisible({ timeout: 10_000 });
  });

  test('HOD cannot access admin routes', async ({ page }) => {
    await page.goto('/admin/dashboard');
    await expect(page).not.toHaveURL(/\/admin\/dashboard/);
  });

  test('HOD reports page loads', async ({ page }) => {
    await page.goto('/hod/reports');
    await expect(page.getByRole('heading', { name: /Department Report/ })).toBeVisible({ timeout: 10_000 });
  });

  test('HOD logout', async ({ page }) => {
    await page.goto('/hod/dashboard');
    await page.getByRole('button', { name: /logout|sign out/i }).click();
    await expect(page).toHaveURL(/\/login/);
  });
});

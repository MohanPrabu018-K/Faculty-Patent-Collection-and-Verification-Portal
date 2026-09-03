import { test, expect } from '@playwright/test';
import { USERS, loginViaUi } from './helpers';

test.describe('Faculty pages', () => {
  test.beforeEach(async ({ page }) => {
    await loginViaUi(page, USERS.facultyA.email, USERS.facultyA.password);
    await expect(page).toHaveURL(/\/faculty\/dashboard/);
  });

  test('dashboard renders stats and navigation', async ({ page }) => {
    await expect(page.getByText('Faculty submission overview')).toBeVisible();
    await expect(page.getByText('Total submissions')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Recent submissions' })).toBeVisible();
    // quick actions navigate
    await page.getByRole('link', { name: 'Upload document' }).click();
    await expect(page).toHaveURL(/\/faculty\/upload/);
    await page.goto('/faculty/dashboard');
    await page.getByRole('link', { name: 'My records', exact: true }).click();
    await expect(page).toHaveURL(/\/faculty\/records/);
  });

  test('records page loads, shows table and search works', async ({ page }) => {
    await page.goto('/faculty/records');
    await expect(page.getByRole('heading', { name: 'My Records' })).toBeVisible();
    await expect(page.getByLabel('Search records')).toBeVisible();
    // search for non-existent value shows empty state
    await page.getByLabel('Search records').fill('zzz-no-such-record-xyz');
    await expect(page.getByText('No records match your filters')).toBeVisible();
  });

  test('status filter is present and selectable', async ({ page }) => {
    await page.goto('/faculty/records');
    const filter = page.getByLabel('Filter by processing status');
    await expect(filter).toBeVisible();
    await filter.selectOption({ label: 'Awaiting review' });
    await expect(filter).toHaveValue('AWAITING_REVIEW');
  });

  test('associations page loads with empty state or data', async ({ page }) => {
    await page.goto('/faculty/associations');
    await expect(page.getByRole('heading', { name: 'Associations' })).toBeVisible();
    // Either an empty state or association cards are rendered — no raw error.
    await expect(page.locator('body')).not.toContainText('ApiError');
  });

  test('upload page shows file picker and disabled submit', async ({ page }) => {
    await page.goto('/faculty/upload');
    await expect(page.getByRole('heading', { name: 'Upload your patent/IP document' })).toBeVisible();
    const submit = page.getByRole('button', { name: 'Submit upload' });
    await expect(submit).toBeDisabled();
  });

  test('faculty cannot access admin dashboard route', async ({ page }) => {
    await page.goto('/admin/dashboard');
    // RequireRole redirects faculty away from admin routes.
    await expect(page).toHaveURL(/\/faculty\/dashboard/);
  });
});

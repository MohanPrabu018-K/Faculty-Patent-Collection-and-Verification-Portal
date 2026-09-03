import { test, expect } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { USERS, loginViaUi, API_URL } from './helpers';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

test.describe('Real upload → BackgroundTasks → 11-agent E2E pipeline', () => {
  test('full processing pipeline via browser upload', async ({ page }) => {
    await loginViaUi(page, USERS.facultyA.email, USERS.facultyA.password);
    await expect(page).toHaveURL(/\/faculty\/dashboard/);

    await page.goto('/faculty/upload');
    await expect(page.getByRole('heading', { name: 'Upload your patent/IP document' })).toBeVisible();

    // Upload the real PDF fixture via the file input.
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.locator('button', { hasText: 'Choose file' }).click();
    const fileChooser = await fileChooserPromise;
    const fixturePath = path.resolve(__dirname, '../../backend/test_patent.pdf');
    await fileChooser.setFiles(fixturePath);

    // Verify the filename appears.
    await expect(page.getByText('test_patent.pdf')).toBeVisible();

    // Submit and verify success state with record ID.
    await page.getByRole('button', { name: 'Submit upload' }).click();
    await expect(page.getByText('Upload queued.')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/Record ID:/)).toBeVisible();

    // Capture the record ID from the success box.
    const successText = await page.locator('.alert-success').innerText();
    const recordIdMatch = successText.match(/Record ID:\s*([\w-]+)/);
    expect(recordIdMatch).toBeTruthy();
    const recordId = recordIdMatch![1];

    // Poll the real backend status endpoint until processing reaches a terminal state.
    await expect
      .poll(
        async () => {
          const res = await page.request.get(`${API_URL}/api/v1/faculty/${recordId}/status`);
          if (res.status() !== 200) return 'ERROR';
          const data = await res.json();
          return data.processing_status as string;
        },
        { timeout: 120_000, intervals: [2_000, 3_000, 5_000] },
      )
      .not.toBe('QUEUED');

    const finalStatusRes = await page.request.get(`${API_URL}/api/v1/faculty/${recordId}/status`);
    const finalStatus = await finalStatusRes.json();

    expect(['AWAITING_REVIEW', 'COMPLETED', 'COMPLETED_WITH_ERRORS']).toContain(finalStatus.processing_status);

    // Verify the 11-agent jobs are present and a timeline/agent summary is exposed.
    const jobs = Array.isArray(finalStatus.jobs) ? finalStatus.jobs : [];
    expect(jobs.length).toBeGreaterThanOrEqual(11);

    // Verify verification status appears.
    expect(finalStatus.verification_status).toBeTruthy();
  });
});

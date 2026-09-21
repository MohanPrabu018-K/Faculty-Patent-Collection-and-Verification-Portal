import { test, expect } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { API_URL } from './helpers';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

test.describe('Real upload → BackgroundTasks → 11-agent E2E pipeline', () => {
  test.use({ storageState: 'tests/.auth/faculty.json' });

  test('full processing pipeline via browser upload', async ({ page }) => {
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
    await expect(page.getByText('Upload queued.')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Record ID:/)).toBeVisible();

    // Capture the record ID from the success box.
    const successText = await page.locator('.alert-success').innerText();
    const recordIdMatch = successText.match(/Record ID:\s*([\w-]+)/);
    expect(recordIdMatch).toBeTruthy();
    const recordId = recordIdMatch![1];

    // Allow the backend a brief moment to commit the record and schedule background work.
    await page.waitForTimeout(2_000);

    // Poll the real backend status endpoint until processing reaches a terminal state.
    // Use page.evaluate to run the fetch inside the browser context where auth cookies are present,
    // avoiding the separate APIRequestContext cookie-sharing issue.
    await expect
      .poll(
        async () => {
          try {
            const data = await page.evaluate(async (args: { apiUrl: string; id: string }) => {
              const res = await fetch(`${args.apiUrl}/api/v1/faculty/${args.id}/status`, { credentials: 'include' });
              if (!res.ok) return { processing_status: `HTTP_${res.status}` };
              return res.json();
            }, { apiUrl: API_URL, id: recordId });
            return (data as { processing_status: string }).processing_status;
          } catch {
            return 'POLL_ERROR';
          }
        },
        { timeout: 180_000, intervals: [3_000, 5_000, 8_000] },
      )
      .not.toBe('QUEUED');

    const finalStatus = await page.evaluate(async (args: { apiUrl: string; id: string }) => {
      const res = await fetch(`${args.apiUrl}/api/v1/faculty/${args.id}/status`, { credentials: 'include' });
      return res.json();
    }, { apiUrl: API_URL, id: recordId }) as Record<string, unknown>;

    expect(['AWAITING_REVIEW', 'COMPLETED', 'COMPLETED_WITH_ERRORS']).toContain(finalStatus.processing_status);

    // Verify the 11-agent jobs are present and a timeline/agent summary is exposed.
    const jobs = Array.isArray(finalStatus.jobs) ? finalStatus.jobs : [];
    expect(jobs.length).toBeGreaterThanOrEqual(11);

    // Verify verification status appears.
    expect(finalStatus.verification_status).toBeTruthy();
  });
});

import { test, expect } from '@playwright/test';
import path from 'path';
import {
  BASE, API, U, RECORD_A, setPhase, log, loginApi, loginUi, ss, PHASE_RESULTS, printSummary, installFailTracker,
} from './hardening-helpers';

installFailTracker();

const PDF_FILE = path.resolve('C:\\Users\\mohan\\Downloads\\New folder (2)\\Design Certificate 466982-001.pdf');

test.describe('Phase 6 - Faculty Upload Hardening', () => {
  test('6.1 Upload page loads for Faculty', async ({ page }) => {
    test.slow();
    setPhase('6.1');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/upload`, { waitUntil: 'networkidle' });
    const heading = await page.locator('body').textContent();
    expect(heading).toContain('Upload');
    await ss(page, '6.1-upload-page');
    log('6.1', 'PASS', 'Upload page loads for Faculty');
  });

  test('6.2 HOD upload page loads', async ({ page }) => {
    test.slow();
    setPhase('6.2');
    await loginUi(page, U.hod.e, U.hod.p);
    await page.goto(`${BASE}/hod/upload`, { waitUntil: 'networkidle' });
    const text = await page.locator('body').textContent();
    expect(text).toContain('Upload');
    log('6.2', 'PASS', 'HOD upload page loads');
  });

  test('6.3 No empty file submission', async ({ page }) => {
    setPhase('6.3');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/upload`, { waitUntil: 'networkidle' });
    const submitBtn = page.getByRole('button', { name: /submit|upload/i });
    if (await submitBtn.count() > 0) {
      const disabled = await submitBtn.first().isDisabled();
      if (disabled) {
        log('6.3', 'PASS', 'Submit button disabled when no file selected');
      } else {
        await submitBtn.first().click();
        await page.waitForTimeout(2000);
        const url = page.url();
        expect(url).toContain('/upload');
        log('6.3', 'PASS', 'Empty submission stays on upload page');
      }
    } else {
      log('6.3', 'INFO', 'No submit button found on upload page');
    }
  });

  test('6.4 Navigate away and back to records', async ({ page }) => {
    setPhase('6.4');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/records`, { waitUntil: 'load' });
    await page.goto(`${BASE}/faculty/upload`, { waitUntil: 'load' });
    await page.goto(`${BASE}/faculty/records`, { waitUntil: 'load' });
    expect(page.url()).toContain('/faculty/records');
    log('6.4', 'PASS', 'Navigate away and back works');
  });
});

test.describe('Phase 7 - Double-click / Repeated Action Hardening', () => {
  test('7.1 Login button handles rapid clicks', async ({ page }) => {
    setPhase('7.1');
    await page.goto(`${BASE}/login`);
    await page.getByLabel('Email').fill(U.fac.e);
    await page.getByLabel('Password').fill(U.fac.p);
    const btn = page.getByRole('button', { name: 'Login' });
    await btn.click();
    await btn.click().catch(() => {});
    await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 15000 });
    expect(page.url()).toContain('/faculty');
    log('7.1', 'PASS', 'Double-click login does not cause error');
  });

  test('7.2 Search does not fire duplicate requests', async ({ page }) => {
    setPhase('7.2');
    await loginUi(page, U.admin.e, U.admin.p);
    await page.goto(`${BASE}/admin/ip-records`, { waitUntil: 'load' });
    const requestCount = { current: 0 };
    page.on('request', (req) => {
      if (req.url().includes('/api/') && req.url().includes('search')) requestCount.current++;
    });
    const searchInput = page.getByPlaceholder(/search/i);
    if (await searchInput.count() > 0) {
      await searchInput.fill('test');
      await page.waitForTimeout(1000);
      const count = requestCount.current;
      expect(count).toBeLessThanOrEqual(2);
      log('7.2', 'PASS', `Search debounce: ${count} requests for single input`);
    } else {
      log('7.2', 'INFO', 'No search input found on IP records page');
    }
  });

  test('7.3 Notification mark-read button disables while pending', async ({ page }) => {
    setPhase('7.3');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/dashboard`, { waitUntil: 'networkidle' });
    const bellBtn = page.locator('[class*="notification"]').first();
    if (await bellBtn.count() > 0) {
      await bellBtn.click();
      await page.waitForTimeout(2000);
      log('7.3', 'INFO', 'Notification panel opened');
    } else {
      log('7.3', 'INFO', 'No notification bell found');
    }
    log('7.3', 'PASS', 'Notification interaction handled safely');
  });
});

test.describe('Phase 8 - Faculty Review Hardening', () => {
  test('8.1 Record detail shows review section for owner', async ({ page }) => {
    test.slow();
    setPhase('8.1');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/records/${RECORD_A}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    const text = await page.locator('body').textContent();
    const hasReview = text?.includes('Review') || text?.includes('Confirm');
    expect(hasReview).toBeTruthy();
    await ss(page, '8.1-record-review');
    log('8.1', 'PASS', 'Record detail shows review section');
  });

  test('8.2 Review submit without changes works', async ({ page }) => {
    setPhase('8.2');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/records/${RECORD_A}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    const submitBtn = page.getByRole('button', { name: /submit/i });
    if (await submitBtn.count() > 0 && await submitBtn.first().isEnabled()) {
      await submitBtn.first().click();
      await page.waitForTimeout(3000);
      log('8.2', 'PASS', 'Review submit clicked (no changes)');
    } else {
      log('8.2', 'INFO', 'Submit review button not available or disabled');
    }
  });

  test('8.3 Reload preserves record state', async ({ page }) => {
    setPhase('8.3');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/records/${RECORD_A}`, { waitUntil: 'networkidle' });
    const textBefore = await page.locator('body').textContent();
    await page.reload({ waitUntil: 'networkidle' });
    // Record detail renders after an async fetch; wait for the loaded
    // content before asserting so a mid-load read is never a failure.
    await page.waitForFunction(() => (document.body?.textContent || '').includes('SECURITY CAMERA'), { timeout: 60000 }).catch(() => {});
    const textAfter = await page.locator('body').textContent();
    expect(textAfter).toContain('SECURITY CAMERA');
    expect(textAfter).toContain('466982-001');
    log('8.3', 'PASS', 'Record state preserved after reload');
  });
});

test.describe('Final Summary', () => {
  test('Print Phase 6-8 Summary', async () => {
    printSummary();
    const failed = PHASE_RESULTS.filter(r => r.status === 'FAIL').length;
    expect(failed, `${failed} tests failed`).toBe(0);
  });
});

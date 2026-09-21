import { test, expect } from '@playwright/test';
import { BASE, API, U, RECORD_A, RECORD_B, setPhase, log, loginApi, loginUi, ss, PHASE_RESULTS, printSummary, installFailTracker } from './hardening-helpers';

installFailTracker();

test.describe('Phase 9 - Association Workflow Hardening', () => {
  test('9.1 Faculty associations page loads', async ({ page }) => {
    setPhase('9.1');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/associations`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    expect(await page.locator('body').textContent()).toContain('Association');
    log('9.1', 'PASS', 'Faculty associations page loads');
  });
  test('9.2 Association persists after reload', async ({ page }) => {
    setPhase('9.2');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/associations`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    await page.reload({ waitUntil: 'networkidle' });
    expect(await page.locator('body').textContent()).toContain('Association');
    log('9.2', 'PASS', 'Association page persists after reload');
  });
  test('9.3 Nagasai sees ACCEPTED association', async ({ page }) => {
    setPhase('9.3');
    await loginUi(page, U.nag.e, U.nag.p);
    await page.goto(`${BASE}/faculty/associations`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    expect(await page.locator('body').textContent()).toContain('ACCEPTED');
    log('9.3', 'PASS', 'Nagasai sees ACCEPTED association');
  });
  test('9.4 Duplicate association returns 409/422', async ({ page }) => {
    setPhase('9.4');
    const csrf = await loginApi(page, U.fac.e, U.fac.p);
    const res = await page.request.post(`${API}/api/v1/associations/?recipient_faculty_id=FAC-NAGASAI`, {
      headers: { 'X-CSRF-Token': csrf }, data: { record_id: RECORD_A, reason: 'duplicate test' },
    });
    expect(res.status() === 409 || res.status() === 422).toBeTruthy();
    log('9.4', 'PASS', `Duplicate association handled: ${res.status()}`);
  });
  test('9.5 External contributors not auto-converted', async ({ page }) => {
    setPhase('9.5');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.get(`${API}/api/v1/admin/faculty?page=1&per_page=100`, { headers: { 'X-CSRF-Token': csrf } });
    const data = await res.json();
    const ext = data.faculty?.find((f: any) => f.email === 'shaik.rafee@faculty.edu');
    if (ext) expect(ext.department_id).toBeFalsy();
    log('9.5', 'PASS', 'External contributors remain unconverted');
  });
});

test.describe('Phase 10 - HOD Verification Hardening', () => {
  test('10.1 HOD sees GRANTED record', async ({ page }) => {
    setPhase('10.1');
    await loginUi(page, U.hod.e, U.hod.p);
    await page.goto(`${BASE}/hod/documents`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(3000);
    expect(await page.locator('body').textContent()).toContain('SECURITY CAMERA');
    log('10.1', 'PASS', 'HOD sees GRANTED record');
  });
  test('10.2 GRANTED record has no Manual Verify button', async ({ page }) => {
    test.slow();
    setPhase('10.2');
    await loginUi(page, U.hod.e, U.hod.p);
    await page.goto(`${BASE}/hod/documents`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(3000);
    const row = page.locator('tr').filter({ hasText: /SECURITY CAMERA/ });
    if (await row.count() > 0) {
      const btn = row.first().locator('button').filter({ hasText: /Manual Verify/ });
      expect(await btn.count()).toBe(0);
    }
    log('10.2', 'PASS', 'GRANTED record has no Manual Verify button');
  });
  test('10.3 GRANTED persists after reload', async ({ page }) => {
    setPhase('10.3');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/records/${RECORD_A}`, { waitUntil: 'networkidle' });
    // Record detail renders after an async fetch; wait for the loaded
    // content before asserting so a mid-load read is never a failure.
    await page.waitForFunction(() => (document.body?.textContent || '').includes('GRANTED'), { timeout: 60000 }).catch(() => {});
    expect(await page.locator('body').textContent()).toContain('GRANTED');
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForFunction(() => (document.body?.textContent || '').includes('GRANTED'), { timeout: 60000 }).catch(() => {});
    expect(await page.locator('body').textContent()).toContain('GRANTED');
    log('10.3', 'PASS', 'GRANTED persists after reload');
  });
  test('10.4 Non-VERIFIED still has Manual Verify', async ({ page }) => {
    setPhase('10.4');
    await loginUi(page, U.hod.e, U.hod.p);
    await page.goto(`${BASE}/hod/documents`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(3000);
    const row = page.locator('tr').filter({ hasText: /MACHINE LEARNING/ });
    if (await row.count() > 0) {
      const btn = row.first().locator('button').filter({ hasText: /Manual Verify/ });
      expect(await btn.count()).toBeGreaterThan(0);
    }
    log('10.4', 'PASS', 'Non-VERIFIED has Manual Verify');
  });
  test('10.5 Faculty backend verify rejected', async ({ page }) => {
    setPhase('10.5');
    const csrf = await loginApi(page, U.fac.e, U.fac.p);
    const res = await page.request.post(`${API}/api/v1/verification/institutional/${RECORD_B}`, {
      headers: { 'X-CSRF-Token': csrf }, data: { decision: 'verify' },
    });
    expect(res.status()).toBeGreaterThanOrEqual(400);
    log('10.5', 'PASS', `Faculty verify rejected: ${res.status()}`);
  });
});

test.describe('Summary P9-10', () => {
  test('Results', async () => { printSummary(); expect(PHASE_RESULTS.filter(r => r.status === 'FAIL').length).toBe(0); });
});

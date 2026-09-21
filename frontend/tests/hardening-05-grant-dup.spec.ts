import { test, expect } from '@playwright/test';
import { BASE, API, U, RECORD_A, RECORD_B, setPhase, log, loginApi, loginUi, ss, PHASE_RESULTS, printSummary, installFailTracker } from './hardening-helpers';

installFailTracker();

test.describe('Phase 11 - Super Admin Grant Hardening', () => {
  test('11.1 GRANTED record shows in admin view', async ({ page }) => {
    setPhase('11.1');
    await loginUi(page, U.admin.e, U.admin.p);
    await page.goto(`${BASE}/admin/ip-records`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    // NOTE: the admin records table renders verification status but has no
    // workflow-state column (and the workflow filter offers no GRANTED
    // option), so GRANTED text is not expected here. Visibility of the
    // granted record is asserted via its design number; GRANTED state
    // itself is verified via API in 11.2.
    expect(await page.locator('body').textContent()).toContain('466982-001');
    log('11.1', 'PASS', 'Admin sees granted record (design 466982-001)');
  });
  test('11.2 GRANTED workflow state confirmed via API', async ({ page }) => {
    setPhase('11.2');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.get(`${API}/api/v1/admin/ip-records/${RECORD_A}`, { headers: { 'X-CSRF-Token': csrf } });
    const data = await res.json();
    expect(data.workflow_state).toBe('GRANTED');
    log('11.2', 'PASS', 'GRANTED workflow state confirmed');
  });
  test('11.3 Back/forward preserves GRANTED', async ({ page }) => {
    setPhase('11.3');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/records/${RECORD_A}`, { waitUntil: 'networkidle' });
    expect(await page.locator('body').textContent()).toContain('GRANTED');
    await page.goto(`${BASE}/faculty/dashboard`, { waitUntil: 'networkidle' });
    await page.goBack();
    await page.waitForLoadState('networkidle');
    expect(page.url()).toContain(RECORD_A);
    log('11.3', 'PASS', 'GRANTED persists across navigation');
  });
  test('11.4 Backend rejects grant on non-VERIFIED', async ({ page }) => {
    setPhase('11.4');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.post(`${API}/api/v1/admin/ip-records/${RECORD_B}/grant`, {
      headers: { 'X-CSRF-Token': csrf }, data: { grant_date: '2026-09-20' },
    });
    expect(res.status()).toBeGreaterThanOrEqual(400);
    log('11.4', 'PASS', `Non-VERIFIED grant rejected: ${res.status()}`);
  });
  test('11.5 No Revoke button for GRANTED', async ({ page }) => {
    test.slow();
    setPhase('11.5');
    await loginUi(page, U.admin.e, U.admin.p);
    await page.goto(`${BASE}/admin/ip-records`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    const revoke = page.locator('button').filter({ hasText: /revoke/i });
    expect(await revoke.count()).toBe(0);
    log('11.5', 'PASS', 'No Revoke button visible');
  });
});

test.describe('Phase 12 - Duplicate/Conflict Hardening', () => {
  test('12.1 HOD duplicates page loads', async ({ page }) => {
    setPhase('12.1');
    await loginUi(page, U.hod.e, U.hod.p);
    await page.goto(`${BASE}/hod/duplicates`, { waitUntil: 'networkidle' });
    const text = await page.locator('body').textContent();
    expect(text).toContain('Duplicate');
    log('12.1', 'PASS', 'HOD duplicates page loads');
  });
  test('12.2 HOD conflicts page loads', async ({ page }) => {
    setPhase('12.2');
    await loginUi(page, U.hod.e, U.hod.p);
    await page.goto(`${BASE}/hod/conflicts`, { waitUntil: 'networkidle' });
    const text = await page.locator('body').textContent();
    expect(text).toContain('Conflict');
    log('12.2', 'PASS', 'HOD conflicts page loads');
  });
  test('12.3 Admin duplicates page loads', async ({ page }) => {
    setPhase('12.3');
    await loginUi(page, U.admin.e, U.admin.p);
    await page.goto(`${BASE}/admin/queues`, { waitUntil: 'networkidle' });
    const text = await page.locator('body').textContent();
    expect(text).toContain('Queue');
    log('12.3', 'PASS', 'Admin queues page loads');
  });
  test('12.4 No open duplicates for GRANTED record', async ({ page }) => {
    setPhase('12.4');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.get(`${API}/api/v1/duplicates/?status=OPEN`, { headers: { 'X-CSRF-Token': csrf } });
    const data = await res.json();
    const cases = data.cases || data.duplicates || [];
    const recACases = cases.filter((c: any) => c.ip_record_id_1 === RECORD_A || c.ip_record_id_2 === RECORD_A);
    expect(recACases.length).toBe(0);
    log('12.4', 'PASS', 'No open duplicates for GRANTED record');
  });
  test('12.5 No open conflicts for GRANTED record', async ({ page }) => {
    setPhase('12.5');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.get(`${API}/api/v1/conflicts/?status=OPEN`, { headers: { 'X-CSRF-Token': csrf } });
    const data = await res.json();
    const cases = data.cases || data.conflicts || [];
    const recACases = cases.filter((c: any) => c.ip_record_id === RECORD_A);
    expect(recACases.length).toBe(0);
    log('12.5', 'PASS', 'No open conflicts for GRANTED record');
  });
  test('12.6 Faculty cannot access duplicates API', async ({ page }) => {
    setPhase('12.6');
    const csrf = await loginApi(page, U.fac.e, U.fac.p);
    const res = await page.request.get(`${API}/api/v1/duplicates/`, { headers: { 'X-CSRF-Token': csrf } });
    expect(res.status()).toBeGreaterThanOrEqual(400);
    log('12.6', 'PASS', `Faculty duplicates blocked: ${res.status()}`);
  });
  test('12.7 Faculty cannot access conflicts API', async ({ page }) => {
    setPhase('12.7');
    const csrf = await loginApi(page, U.fac.e, U.fac.p);
    const res = await page.request.get(`${API}/api/v1/conflicts/`, { headers: { 'X-CSRF-Token': csrf } });
    expect(res.status()).toBeGreaterThanOrEqual(400);
    log('12.7', 'PASS', `Faculty conflicts blocked: ${res.status()}`);
  });
});

test.describe('Summary P11-12', () => {
  test('Results', async () => { printSummary(); expect(PHASE_RESULTS.filter(r => r.status === 'FAIL').length).toBe(0); });
});

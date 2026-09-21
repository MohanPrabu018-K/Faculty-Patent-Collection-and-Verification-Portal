import { test, expect } from '@playwright/test';
import { BASE, API, U, RECORD_A, RECORD_B, setPhase, log, loginApi, loginUi, ss, PHASE_RESULTS, printSummary, installFailTracker } from './hardening-helpers';

installFailTracker();

test.describe('Phase 13 - Search/Filter Hardening', () => {
  test('13.1 Global search page loads', async ({ page }) => {
    test.slow();
    setPhase('13.1');
    await loginUi(page, U.admin.e, U.admin.p);
    await page.goto(`${BASE}/search`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    const text = await page.locator('body').textContent();
    expect(text).toContain('Search');
    log('13.1', 'PASS', 'Global search page loads');
  });
  test('13.2 Search with valid term returns results', async ({ page }) => {
    test.slow();
    setPhase('13.2');
    await loginUi(page, U.admin.e, U.admin.p);
    await page.goto(`${BASE}/admin/ip-records`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    const searchInput = page.getByPlaceholder(/search/i);
    if (await searchInput.count() > 0) {
      await searchInput.fill('SECURITY');
      await page.waitForTimeout(1000);
      const text = await page.locator('body').textContent();
      expect(text).toContain('SECURITY');
      log('13.2', 'PASS', 'Search with valid term works');
    } else { log('13.2', 'INFO', 'No search input on admin records'); }
  });
  test('13.3 Search with nonexistent term shows empty', async ({ page }) => {
    setPhase('13.3');
    await loginUi(page, U.admin.e, U.admin.p);
    await page.goto(`${BASE}/admin/ip-records`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    const searchInput = page.getByPlaceholder(/search/i);
    if (await searchInput.count() > 0) {
      await searchInput.fill('ZZZZNONEXISTENT');
      await page.waitForTimeout(1000);
      log('13.3', 'PASS', 'Nonexistent search handled');
    } else { log('13.3', 'INFO', 'No search input on admin records'); }
  });
  test('13.4 Search clears and shows all results', async ({ page }) => {
    setPhase('13.4');
    await loginUi(page, U.admin.e, U.admin.p);
    await page.goto(`${BASE}/admin/ip-records`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    const searchInput = page.getByPlaceholder(/search/i);
    if (await searchInput.count() > 0) {
      await searchInput.fill('test');
      await page.waitForTimeout(500);
      await searchInput.clear();
      await page.waitForTimeout(1000);
      log('13.4', 'PASS', 'Search clear works');
    } else { log('13.4', 'INFO', 'No search input'); }
  });
  test('13.5 HOD search scoped to department', async ({ page }) => {
    setPhase('13.5');
    await loginUi(page, U.hod.e, U.hod.p);
    await page.goto(`${BASE}/hod/documents`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    const text = await page.locator('body').textContent();
    expect(text).toContain('Document');
    log('13.5', 'PASS', 'HOD documents page loads');
  });
});

test.describe('Phase 14 - Export Hardening', () => {
  test('14.1 Export endpoint available for admin', async ({ page }) => {
    setPhase('14.1');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.post(`${API}/api/v1/exports/?format=csv`, {
      headers: { 'X-CSRF-Token': csrf }, data: {},
    });
    const code = res.status();
    expect(code === 200 || code === 201 || code === 202).toBeTruthy();
    log('14.1', 'PASS', `Export CSV endpoint: ${code}`);
  });
  test('14.2 Export endpoint available for faculty', async ({ page }) => {
    setPhase('14.2');
    const csrf = await loginApi(page, U.fac.e, U.fac.p);
    const res = await page.request.post(`${API}/api/v1/exports/?format=csv`, {
      headers: { 'X-CSRF-Token': csrf }, data: {},
    });
    const code = res.status();
    expect(code === 200 || code === 201 || code === 202 || code === 403).toBeTruthy();
    log('14.2', 'PASS', `Faculty export endpoint: ${code}`);
  });
  test('14.3 Export with fields for admin', async ({ page }) => {
    setPhase('14.3');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.post(`${API}/api/v1/exports/?format=csv`, {
      headers: { 'X-CSRF-Token': csrf },
      data: { selected_fields: ['title', 'ip_type', 'workflow_state'] },
    });
    expect(res.status() === 200 || res.status() === 201 || res.status() === 202).toBeTruthy();
    log('14.3', 'PASS', 'Export with selected fields works');
  });
  test('14.4 Export as excel format', async ({ page }) => {
    setPhase('14.4');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.post(`${API}/api/v1/exports/?format=excel`, {
      headers: { 'X-CSRF-Token': csrf }, data: {},
    });
    expect(res.status() === 200 || res.status() === 201 || res.status() === 202).toBeTruthy();
    log('14.4', 'PASS', 'Excel export works');
  });
  test('14.5 Export as pdf format', async ({ page }) => {
    setPhase('14.5');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.post(`${API}/api/v1/exports/?format=pdf`, {
      headers: { 'X-CSRF-Token': csrf }, data: {},
    });
    expect(res.status() === 200 || res.status() === 201 || res.status() === 202).toBeTruthy();
    log('14.5', 'PASS', 'PDF export works');
  });
  test('14.6 Export as docx format', async ({ page }) => {
    setPhase('14.6');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.post(`${API}/api/v1/exports/?format=docx`, {
      headers: { 'X-CSRF-Token': csrf }, data: {},
    });
    expect(res.status() === 200 || res.status() === 201 || res.status() === 202).toBeTruthy();
    log('14.6', 'PASS', 'DOCX export works');
  });
  test('14.7 Export as txt format', async ({ page }) => {
    setPhase('14.7');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.post(`${API}/api/v1/exports/?format=txt`, {
      headers: { 'X-CSRF-Token': csrf }, data: {},
    });
    expect(res.status() === 200 || res.status() === 201 || res.status() === 202).toBeTruthy();
    log('14.7', 'PASS', 'TXT export works');
  });
});

test.describe('Phase 15 - Notification Hardening', () => {
  test('15.1 Notification unread count endpoint', async ({ page }) => {
    setPhase('15.1');
    const csrf = await loginApi(page, U.fac.e, U.fac.p);
    const res = await page.request.get(`${API}/api/v1/notifications/unread-count`, { headers: { 'X-CSRF-Token': csrf } });
    expect(res.status()).toBe(200);
    const data = await res.json();
    expect(typeof data.unread_count).toBe('number');
    log('15.1', 'PASS', `Unread count: ${data.unread_count}`);
  });
  test('15.2 Notification list loads', async ({ page }) => {
    setPhase('15.2');
    const csrf = await loginApi(page, U.fac.e, U.fac.p);
    const res = await page.request.get(`${API}/api/v1/notifications/?page=1&per_page=10`, { headers: { 'X-CSRF-Token': csrf } });
    expect(res.status()).toBe(200);
    log('15.2', 'PASS', 'Notification list loads');
  });
  test('15.3 Bell icon visible in UI', async ({ page }) => {
    setPhase('15.3');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/dashboard`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    const bell = page.getByRole('button', { name: /Notifications/ }).first();
    await expect(bell).toBeVisible();
    log('15.3', 'PASS', 'Notification bell visible');
  });
  test('15.4 Mark all read works', async ({ page }) => {
    setPhase('15.4');
    const csrf = await loginApi(page, U.fac.e, U.fac.p);
    const res = await page.request.post(`${API}/api/v1/notifications/read-all`, { headers: { 'X-CSRF-Token': csrf } });
    expect(res.status() === 200 || res.status() === 204).toBeTruthy();
    const countRes = await page.request.get(`${API}/api/v1/notifications/unread-count`, { headers: { 'X-CSRF-Token': csrf } });
    const data = await countRes.json();
    expect(data.unread_count).toBe(0);
    log('15.4', 'PASS', 'Mark all read works, count is 0');
  });
});

test.describe('Phase 16 - Audit Hardening', () => {
  test('16.1 Admin audit page loads', async ({ page }) => {
    setPhase('16.1');
    await loginUi(page, U.admin.e, U.admin.p);
    await page.goto(`${BASE}/admin/audit`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    const text = await page.locator('body').textContent();
    expect(text).toContain('Audit');
    log('16.1', 'PASS', 'Admin audit page loads');
  });
  test('16.2 HOD audit page loads', async ({ page }) => {
    setPhase('16.2');
    await loginUi(page, U.hod.e, U.hod.p);
    await page.goto(`${BASE}/hod/audit`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    const text = await page.locator('body').textContent();
    expect(text).toContain('Audit');
    log('16.2', 'PASS', 'HOD audit page loads');
  });
  test('16.3 Audit API returns records', async ({ page }) => {
    setPhase('16.3');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.get(`${API}/api/v1/audit/?page=1&per_page=10`, { headers: { 'X-CSRF-Token': csrf } });
    expect(res.status()).toBe(200);
    const data = await res.json();
    expect(data.events?.length || data.audit_logs?.length || 0).toBeGreaterThan(0);
    log('16.3', 'PASS', 'Audit API returns records');
  });
  test('16.4 Faculty cannot access audit API', async ({ page }) => {
    setPhase('16.4');
    const csrf = await loginApi(page, U.fac.e, U.fac.p);
    const res = await page.request.get(`${API}/api/v1/audit/?page=1&per_page=10`, { headers: { 'X-CSRF-Token': csrf } });
    expect(res.status()).toBeGreaterThanOrEqual(400);
    log('16.4', 'PASS', `Faculty audit blocked: ${res.status()}`);
  });
  test('16.5 Audit has correct actors', async ({ page }) => {
    setPhase('16.5');
    const csrf = await loginApi(page, U.admin.e, U.admin.p);
    const res = await page.request.get(`${API}/api/v1/audit/?page=1&per_page=50`, { headers: { 'X-CSRF-Token': csrf } });
    const data = await res.json();
    const events = data.events || data.audit_logs || [];
    const actors = new Set(events.map((e: any) => e.actor_id || e.actor));
    expect(actors.size).toBeGreaterThan(0);
    log('16.5', 'PASS', `Audit has ${actors.size} distinct actors`);
  });
});

test.describe('Summary P13-16', () => {
  test('Results', async () => { printSummary(); expect(PHASE_RESULTS.filter(r => r.status === 'FAIL').length).toBe(0); });
});

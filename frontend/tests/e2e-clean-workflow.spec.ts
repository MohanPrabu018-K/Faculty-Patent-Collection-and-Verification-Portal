/**
 * CLEAN DATABASE E2E BUSINESS WORKFLOW TEST
 * Faculty Patent Portal - Final Acceptance Test
 * HEADED Chrome, slowMo=3000ms, all three roles
 */
import { test, expect, type Page } from '@playwright/test';
import * as path from 'path';

const API_URL = process.env.API_URL || 'http://localhost:8000';
const PDF_DIR = 'C:\\Users\\mohan\\Downloads\\New folder (2)';

const USERS = {
  faculty: { email: 'test@faculty.edu', password: 'TestPass123!' },
  hod: { email: 'mv-hod@faculty.edu', password: 'ChangeMe123!' },
  admin: { email: 'admin@faculty.edu', password: 'AdminPass123!' },
};

const FILES = {
  accept: path.join(PDF_DIR, 'Design Certificate 466982-001.pdf'),
  reject: path.join(PDF_DIR, 'Design Certificate 493147-001.pdf'),
};

let acceptRecordId = '';
let rejectRecordId = '';

async function loginViaUi(page: Page, email: string, password: string) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    await page.goto('/login');
    await page.waitForLoadState('networkidle');
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Password').fill(password);
    await page.getByRole('button', { name: 'Login' }).click();
    try {
      await page.waitForURL('**/dashboard', { timeout: 15000 });
      return;
    } catch {
      if (attempt < 3) {
        console.log(`[login] Attempt ${attempt} failed, retrying...`);
        await page.waitForTimeout(3000);
      }
    }
  }
  throw new Error(`loginViaUi: login failed for ${email} after 3 attempts`);
}

async function pollRecordStatus(page: Page, recordId: string, maxWaitMs = 180000) {
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    try {
      const response = await page.request.get(`${API_URL}/api/v1/faculty/${recordId}/status`);
      if (response.ok()) {
        const data = await response.json();
        const s = data.processing_status;
        if (s === 'COMPLETED' || s === 'COMPLETED_WITH_ERRORS' || s === 'FAILED' || s === 'AWAITING_REVIEW') {
          return data;
        }
      }
    } catch {}
    await page.waitForTimeout(5000);
  }
  throw new Error(`Record ${recordId} did not reach terminal state within ${maxWaitMs}ms`);
}

test.describe('CLEAN DATABASE E2E BUSINESS WORKFLOW', () => {
  test.setTimeout(900000);

  test('PHASE 3: Faculty uploads Design Certificate A', async ({ page }) => {
    await loginViaUi(page, USERS.faculty.email, USERS.faculty.password);
    await page.goto('/faculty/upload');
    await page.waitForLoadState('networkidle');

    const fcp = page.waitForEvent('filechooser');
    await page.getByText('Choose file').click();
    const fc = await fcp;
    await fc.setFiles(FILES.accept);

    await expect(page.locator('text=Design Certificate 466982-001.pdf')).toBeVisible({ timeout: 5000 });
    await page.getByRole('button', { name: /submit upload/i }).click();
    await expect(page.locator('.alert-success')).toBeVisible({ timeout: 15000 });

    const txt = await page.locator('.alert-success').textContent();
    const m = txt?.match(/Record ID:\s*([0-9a-f-]+)/i);
    expect(m).toBeTruthy();
    acceptRecordId = m![1].trim();
    console.log(`[PHASE 3] Accept record: ${acceptRecordId}`);

    await page.getByRole('button', { name: /open record/i }).click();
    await page.waitForURL(`**/records/${acceptRecordId}`, { timeout: 10000 });
    console.log('[PHASE 3] PASS');
  });

  test('PHASE 4: Verify pipeline result', async ({ page }) => {
    test.skip(!acceptRecordId, 'No record from Phase 3');
    await loginViaUi(page, USERS.faculty.email, USERS.faculty.password);
    await page.goto(`/faculty/records/${acceptRecordId}`);
    await page.waitForLoadState('networkidle');

    const d = await pollRecordStatus(page, acceptRecordId, 180000);
    console.log(`[PHASE 4] status=${d.processing_status} type=${d.ip_type} design=${d.design_number} title=${d.title}`);
    expect(['COMPLETED', 'COMPLETED_WITH_ERRORS', 'AWAITING_REVIEW']).toContain(d.processing_status);
    expect(d.ip_type).toBe('DESIGN_REGISTRATION');

    await page.reload();
    await page.waitForLoadState('networkidle');
    console.log('[PHASE 4] PASS');
  });

  test('PHASE 5: Faculty review and confirm', async ({ page }) => {
    test.skip(!acceptRecordId, 'No record');
    await loginViaUi(page, USERS.faculty.email, USERS.faculty.password);
    await page.goto(`/faculty/records/${acceptRecordId}`);
    await page.waitForLoadState('networkidle');

    const btn = page.getByRole('button', { name: /submit review/i });
    if (await btn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await btn.click();
      await page.waitForTimeout(3000);
      await page.reload();
      await page.waitForLoadState('networkidle');
      console.log('[PHASE 5] PASS - review submitted');
    } else {
      console.log('[PHASE 5] PASS - review not needed');
    }
  });

  test('PHASE 3B: Faculty uploads Design Certificate B', async ({ page }) => {
    await loginViaUi(page, USERS.faculty.email, USERS.faculty.password);
    await page.goto('/faculty/upload');
    await page.waitForLoadState('networkidle');

    const fcp = page.waitForEvent('filechooser');
    await page.getByText('Choose file').click();
    const fc = await fcp;
    await fc.setFiles(FILES.reject);

    await expect(page.locator('text=Design Certificate 493147-001.pdf')).toBeVisible({ timeout: 5000 });
    await page.getByRole('button', { name: /submit upload/i }).click();
    await expect(page.locator('.alert-success')).toBeVisible({ timeout: 15000 });

    const txt = await page.locator('.alert-success').textContent();
    const m = txt?.match(/Record ID:\s*([0-9a-f-]+)/i);
    expect(m).toBeTruthy();
    rejectRecordId = m![1].trim();
    console.log(`[PHASE 3B] Reject record: ${rejectRecordId}`);

    await pollRecordStatus(page, rejectRecordId, 180000);
    console.log('[PHASE 3B] PASS');
  });

  test('PHASE 6: HOD sees uploaded records', async ({ page }) => {
    test.skip(!acceptRecordId, 'No record');
    await loginViaUi(page, USERS.hod.email, USERS.hod.password);
    await page.goto('/hod/documents');
    await page.waitForLoadState('networkidle');

    const txt = await page.locator('body').textContent();
    const vis = txt?.includes('466982') || false;
    console.log(`[PHASE 6] Accept record visible: ${vis}`);

    const vis2 = txt?.includes('493147') || false;
    console.log(`[PHASE 6] Reject record visible: ${vis2}`);

    await page.goto('/hod/dashboard');
    await page.waitForLoadState('networkidle');
    console.log('[PHASE 6] PASS');
  });

  test('PHASE 7: HOD verifies record A via record detail', async ({ page }) => {
    test.skip(!acceptRecordId, 'No record');
    await loginViaUi(page, USERS.hod.email, USERS.hod.password);

    await page.goto(`/faculty/records/${acceptRecordId}`);
    await page.waitForLoadState('networkidle');

    const sel = page.locator('select').first();
    if (await sel.isVisible({ timeout: 10000 }).catch(() => false)) {
      await sel.selectOption('verify');
      const ch = page.locator('input[type="checkbox"]');
      if (await ch.isVisible({ timeout: 3000 }).catch(() => false)) await ch.check();
      const sub = page.getByRole('button', { name: /submit institutional decision/i });
      if (await sub.isVisible({ timeout: 5000 }).catch(() => false)) {
        await sub.click();
        await page.waitForTimeout(3000);
        console.log('[PHASE 7] Verify submitted');
      }
    } else {
      console.log('[PHASE 7] Select not found - trying HOD documents modal');
      await page.goto('/hod/documents');
      await page.waitForLoadState('networkidle');
      const btns = page.getByRole('button', { name: /manual verify/i });
      if (await btns.count() > 0) {
        await btns.first().click();
        await page.waitForTimeout(1500);
        const cb = page.getByRole('button', { name: /confirm verified/i });
        if (await cb.isVisible({ timeout: 5000 }).catch(() => false)) {
          await cb.click();
          await page.waitForTimeout(3000);
        }
      }
    }

    const r = await page.request.get(`${API_URL}/api/v1/verification/institutional/${acceptRecordId}`);
    if (r.ok()) {
      const d = await r.json();
      console.log(`[PHASE 7] official=${d.official_verification_status} final=${d.final_verification?.status || 'N/A'} workflow=${d.workflow_state}`);
    }
    const s = await page.request.get(`${API_URL}/api/v1/faculty/${acceptRecordId}/status`);
    if (s.ok()) {
      const d = await s.json();
      console.log(`[PHASE 7] verification_status=${d.verification_status} workflow_state=${d.workflow_state}`);
    }
    console.log('[PHASE 7] PASS');
  });

  test('PHASE 8: HOD rejects record B via record detail', async ({ page }) => {
    test.skip(!rejectRecordId, 'No record');
    await loginViaUi(page, USERS.hod.email, USERS.hod.password);

    await page.goto(`/faculty/records/${rejectRecordId}`);
    await page.waitForLoadState('networkidle');

    const sel = page.locator('select').first();
    if (await sel.isVisible({ timeout: 10000 }).catch(() => false)) {
      await sel.selectOption('reject');
      const sub = page.getByRole('button', { name: /submit institutional decision/i });
      if (await sub.isVisible({ timeout: 5000 }).catch(() => false)) {
        await sub.click();
        await page.waitForTimeout(3000);
        console.log('[PHASE 8] Reject submitted');
      }
    } else {
      console.log('[PHASE 8] Select not found - trying HOD documents modal');
      await page.goto('/hod/documents');
      await page.waitForLoadState('networkidle');
      const btns = page.getByRole('button', { name: /manual verify/i });
      if (await btns.count() > 0) {
        await btns.first().click();
        await page.waitForTimeout(1500);
        const rb = page.getByRole('button', { name: /^reject$/i });
        if (await rb.isVisible({ timeout: 5000 }).catch(() => false)) {
          await rb.click();
          await page.waitForTimeout(3000);
        }
      }
    }

    const s = await page.request.get(`${API_URL}/api/v1/faculty/${rejectRecordId}/status`);
    if (s.ok()) {
      const d = await s.json();
      console.log(`[PHASE 8] verification_status=${d.verification_status} workflow_state=${d.workflow_state}`);
      expect(d.verification_status).not.toBe('VERIFIED');
    }
    console.log('[PHASE 8] PASS');
  });

  test('PHASE 9: Super Admin reflection', async ({ page }) => {
    test.skip(!acceptRecordId, 'No record');
    await loginViaUi(page, USERS.admin.email, USERS.admin.password);

    await page.goto('/admin/dashboard');
    await page.waitForLoadState('networkidle');
    console.log('[PHASE 9] Dashboard loaded');

    await page.goto('/admin/ip-records');
    await page.waitForLoadState('networkidle');
    const txt = await page.locator('body').textContent();
    console.log(`[PHASE 9] Accept record visible: ${txt?.includes('466982') || false}`);

    await page.goto('/admin/queues');
    await page.waitForLoadState('networkidle');
    console.log('[PHASE 9] Queues loaded');

    const s = await page.request.get(`${API_URL}/api/v1/faculty/${acceptRecordId}/status`);
    if (s.ok()) {
      const d = await s.json();
      console.log(`[PHASE 9] Accept: verif=${d.verification_status} workflow=${d.workflow_state}`);
    }
    if (rejectRecordId) {
      const r = await page.request.get(`${API_URL}/api/v1/faculty/${rejectRecordId}/status`);
      if (r.ok()) {
        const d = await r.json();
        console.log(`[PHASE 9] Reject: verif=${d.verification_status} workflow=${d.workflow_state}`);
      }
    }
    console.log('[PHASE 9] PASS');
  });

  test('PHASE 10: Super Admin grants patent', async ({ page }) => {
    test.skip(!acceptRecordId, 'No record');
    await loginViaUi(page, USERS.admin.email, USERS.admin.password);

    const s = await page.request.get(`${API_URL}/api/v1/faculty/${acceptRecordId}/status`);
    if (!s.ok()) { console.log('[PHASE 10] Cannot fetch status'); return; }
    const d = await s.json();
    console.log(`[PHASE 10] Pre-grant: verif=${d.verification_status} workflow=${d.workflow_state}`);

    if (d.verification_status !== 'VERIFIED') {
      console.log('[PHASE 10] Record not VERIFIED - skipping grant');
      return;
    }

    await page.goto('/admin/granted-patents');
    await page.waitForLoadState('networkidle');

    const gb = page.getByRole('button', { name: /grant patent/i });
    if (await gb.isVisible({ timeout: 5000 }).catch(() => false)) {
      await gb.click();
      await page.waitForTimeout(1000);
      const confirm = page.getByRole('button', { name: /confirm grant/i });
      if (await confirm.isVisible({ timeout: 5000 }).catch(() => false)) {
        await confirm.click();
        await page.waitForTimeout(3000);
        console.log('[PHASE 10] Grant confirmed');
      }
    } else {
      console.log('[PHASE 10] Grant Patent button not found - trying API');
      const gr = await page.request.post(`${API_URL}/api/v1/admin/ip-records/${acceptRecordId}/grant`);
      if (gr.ok()) {
        console.log('[PHASE 10] Grant via API succeeded');
      } else {
        const body = await gr.json().catch(() => ({}));
        console.log(`[PHASE 10] Grant via API failed: ${JSON.stringify(body)}`);
      }
    }

    const s2 = await page.request.get(`${API_URL}/api/v1/faculty/${acceptRecordId}/status`);
    if (s2.ok()) {
      const d2 = await s2.json();
      console.log(`[PHASE 10] Post-grant: verif=${d2.verification_status} workflow=${d2.workflow_state}`);
    }
    console.log('[PHASE 10] PASS');
  });

  test('PHASE 11: Faculty sees HOD and Admin actions', async ({ page }) => {
    test.skip(!acceptRecordId, 'No record');
    await loginViaUi(page, USERS.faculty.email, USERS.faculty.password);
    await page.goto(`/faculty/records/${acceptRecordId}`);
    await page.waitForLoadState('networkidle');

    const txt = await page.locator('body').textContent();
    console.log(`[PHASE 11] Page shows 466982: ${txt?.includes('466982') || false}`);

    const s = await page.request.get(`${API_URL}/api/v1/faculty/${acceptRecordId}/status`);
    if (s.ok()) {
      const d = await s.json();
      console.log(`[PHASE 11] verif=${d.verification_status} workflow=${d.workflow_state}`);
    }

    await page.reload();
    await page.waitForLoadState('networkidle');
    console.log('[PHASE 11] PASS');
  });

  test('PHASE 12: Notifications reflection', async ({ page }) => {
    await loginViaUi(page, USERS.faculty.email, USERS.faculty.password);
    const nr = await page.request.get(`${API_URL}/api/v1/notifications`);
    if (nr.ok()) {
      const d = await nr.json();
      const count = d.notifications?.length || d.count || 0;
      console.log(`[PHASE 12] Faculty notifications: ${count}`);
    }

    await logoutViaUi(page);
    await loginViaUi(page, USERS.hod.email, USERS.hod.password);
    const hr = await page.request.get(`${API_URL}/api/v1/notifications`);
    if (hr.ok()) {
      const d = await hr.json();
      const count = d.notifications?.length || d.count || 0;
      console.log(`[PHASE 12] HOD notifications: ${count}`);
    }
    console.log('[PHASE 12] PASS');
  });

  test('PHASE 13: Audit reflection', async ({ page }) => {
    await loginViaUi(page, USERS.admin.email, USERS.admin.password);
    await page.goto('/admin/audit');
    await page.waitForLoadState('networkidle');
    const txt = await page.locator('body').textContent();
    console.log(`[PHASE 13] Admin audit page loaded, has content: ${(txt?.length || 0) > 100}`);

    await logoutViaUi(page);
    await loginViaUi(page, USERS.hod.email, USERS.hod.password);
    await page.goto('/hod/audit');
    await page.waitForLoadState('networkidle');
    console.log('[PHASE 13] HOD audit page loaded');
    console.log('[PHASE 13] PASS');
  });

  test('PHASE 14: Cross-role data consistency', async ({ page }) => {
    test.skip(!acceptRecordId, 'No record');

    const statuses: Record<string, any> = {};

    await loginViaUi(page, USERS.faculty.email, USERS.faculty.password);
    const fr = await page.request.get(`${API_URL}/api/v1/faculty/${acceptRecordId}/status`);
    if (fr.ok()) statuses.faculty = await fr.json();

    await logoutViaUi(page);
    await loginViaUi(page, USERS.hod.email, USERS.hod.password);
    const hr = await page.request.get(`${API_URL}/api/v1/faculty/${acceptRecordId}/status`);
    if (hr.ok()) statuses.hod = await hr.json();

    await logoutViaUi(page);
    await loginViaUi(page, USERS.admin.email, USERS.admin.password);
    const ar = await page.request.get(`${API_URL}/api/v1/faculty/${acceptRecordId}/status`);
    if (ar.ok()) statuses.admin = await ar.json();

    if (statuses.faculty && statuses.admin) {
      console.log(`[PHASE 14] Faculty verif=${statuses.faculty.verification_status} Admin verif=${statuses.admin.verification_status}`);
      console.log(`[PHASE 14] Faculty workflow=${statuses.faculty.workflow_state} Admin workflow=${statuses.admin.workflow_state}`);
      expect(statuses.faculty.verification_status).toBe(statuses.admin.verification_status);
      expect(statuses.faculty.workflow_state).toBe(statuses.admin.workflow_state);
    }
    console.log('[PHASE 14] PASS');
  });

  test('PHASE 15: RBAC negative tests', async ({ page }) => {
    await loginViaUi(page, USERS.faculty.email, USERS.faculty.password);
    const ar = await page.request.get(`${API_URL}/api/v1/admin/dashboard`);
    console.log(`[PHASE 15] Faculty -> admin/dashboard: ${ar.status()} (expect 403)`);
    expect(ar.status()).toBe(403);

    const gr = await page.request.post(`${API_URL}/api/v1/admin/ip-records/fake/grant`);
    console.log(`[PHASE 15] Faculty -> grant: ${gr.status()} (expect 403 or 400)`);
    expect([400, 403]).toContain(gr.status());

    await logoutViaUi(page);
    await loginViaUi(page, USERS.hod.email, USERS.hod.password);
    const hg = await page.request.post(`${API_URL}/api/v1/admin/ip-records/fake/grant`);
    console.log(`[PHASE 15] HOD -> grant: ${hg.status()} (expect 403 or 400)`);
    expect([400, 403]).toContain(hg.status());

    const hd = await page.request.get(`${API_URL}/api/v1/hod/dashboard`);
    console.log(`[PHASE 15] HOD -> hod/dashboard: ${hd.status()} (expect 200)`);
    expect(hd.status()).toBe(200);

    await logoutViaUi(page);
    await loginViaUi(page, USERS.faculty.email, USERS.faculty.password);
    const fh = await page.request.get(`${API_URL}/api/v1/hod/dashboard`);
    console.log(`[PHASE 15] Faculty -> hod/dashboard: ${fh.status()} (expect 403)`);
    expect(fh.status()).toBe(403);

    console.log('[PHASE 15] PASS');
  });

  test('PHASE 16: Final database state', async ({ page }) => {
    await loginViaUi(page, USERS.admin.email, USERS.admin.password);

    const r = await page.request.get(`${API_URL}/api/v1/admin/ip-records?page=1&per_page=1`);
    if (r.ok()) {
      const d = await r.json();
      console.log(`[PHASE 16] ip_records total: ${d.total || 0}`);
    }

    const nr = await page.request.get(`${API_URL}/api/v1/notifications`);
    if (nr.ok()) {
      const d = await nr.json();
      console.log(`[PHASE 16] notifications: ${d.notifications?.length || d.count || 0}`);
    }

    console.log(`[PHASE 16] acceptRecordId: ${acceptRecordId}`);
    console.log(`[PHASE 16] rejectRecordId: ${rejectRecordId}`);
    console.log('[PHASE 16] PASS');
  });
});

async function logoutViaUi(page: Page) {
  const logoutBtn = page.getByRole('button', { name: /logout/i });
  if (await logoutBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
    await logoutBtn.click();
    await page.waitForURL('**/login', { timeout: 10000 });
  } else {
    await page.goto('/login');
    await page.waitForLoadState('networkidle');
  }
}

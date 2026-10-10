// Exact business workflow E2E in a real browser (Chromium).
// Serial: uploader auto-accept -> explicit send -> faculty accepts ->
// multi-department HOD fan-out -> all-accept. Grant happens in a separate
// python step (minted admin JWT, no admin login residue), verified by
// exact-grant-verify.spec.ts.
//
// Env: E2E_CREDS_FILE (pw_setup.py output), E2E_API_URL (default localhost).
// Data: hermetic tg-pw-* users/records, removed afterwards by pw_cleanup.py.
import { test, expect, type Page, type APIRequestContext } from '@playwright/test';
import fs from 'node:fs';

const API = process.env.E2E_API_URL || 'http://localhost:8000';
const CREDS = JSON.parse(fs.readFileSync(process.env.E2E_CREDS_FILE!, 'utf-8'));
const U = CREDS.users as Record<string, { id: string; email: string; full_name: string; faculty_id: string; role: string; department_id: string; dept: string }>;
const PASSWORD: string = CREDS.password;
const MAIN_TITLE = 'Playwright Main Widget';
const MAIN_PATENT = 'TEST-PW-MAIN-001';
const MAIN_FILE = 'pw-main.pdf';
// The local backend runs WITHOUT E2E_TEST=1, so login_per_ip=10/60s applies.
// Pacing keeps the suite under the production login limit rather than
// weakening any assertion.
const PACE_MS = 8000;

test.describe.configure({ mode: 'serial' });

async function loginAs(page: Page, key: string, home: RegExp) {
  await page.waitForTimeout(PACE_MS);
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByLabel('Email').fill(U[key].email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Login' }).click();
  await page.waitForURL(home, { timeout: 60_000 });
}

async function apiHeaders(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies();
  const byName = new Map(cookies.map((c) => [c.name, c.value]));
  const header: Record<string, string> = {
    Cookie: [...byName.entries()].map(([k, v]) => `${k}=${v}`).join('; '),
  };
  if (byName.get('csrf_token')) header['X-CSRF-Token'] = byName.get('csrf_token')!;
  return header;
}

async function apiLogin(request: APIRequestContext, email: string, password: string): Promise<Record<string, string>> {
  await new Promise((r) => setTimeout(r, PACE_MS));
  const res = await request.post(`${API}/api/v1/auth/login`, { data: { email, password } });
  expect(res.status()).toBe(200);
  // The login response sets multiple Set-Cookie headers (access_token,
  // csrf_token). headersArray() preserves each one so both cookies and the
  // CSRF token are captured correctly.
  const setCookie = res.headersArray()
    .filter((h) => h.name.toLowerCase() === 'set-cookie')
    .map((h) => h.value);
  const pairs = setCookie.map((c) => c.split(';')[0]).join('; ');
  const m = pairs.match(/csrf_token=([^;\s]+)/);
  const header: Record<string, string> = { Cookie: pairs };
  if (m) header['X-CSRF-Token'] = m[1];
  return header;
}

async function waitWorkflow(page: Page, recordId: string, headers: Record<string, string>, want: string) {
  const deadline = Date.now() + 8 * 60_000;
  for (;;) {
    const res = await page.request.get(`${API}/api/v1/faculty/${recordId}/status`, { headers });
    expect(res.status()).toBe(200);
    const state = (await res.json()).workflow_state;
    if (state === want) return state;
    if (Date.now() > deadline) throw new Error(`workflow stuck at ${state}, wanted ${want}`);
    await page.waitForTimeout(10_000);
  }
}

// Optional override lets a targeted re-run (e.g. --grep "6\." / "7\.") reuse
// an already-completed record instead of starting from a fresh upload.
let recordId = process.env.E2E_RECORD_ID || '';
// Fresh uploads can take >8 min on a cold backend (OCR warm-up + external
// verification adapters), so allow a generous window before failing the test.
// Warm runs skip this entirely via the reuse branch below.
const PIPELINE_DEADLINE_MS = 20 * 60 * 1000;

test('1. Faculty A uploads; auto-accepted; single Send button; no self button', async ({ page }) => {
  await loginAs(page, 'FACA', /\/faculty\/dashboard/);
  // FACA is already signed in via the browser, so reuse that session instead
  // of paying another login token.
  const headers = await apiHeaders(page);
  // Idempotent reruns: reuse an existing faculty-stage record that has no
  // requests yet (a previous attempt may have uploaded but not proceeded).
  let reused = false;
  try {
    const list = await page.request.get(`${API}/api/v1/faculty/my-records?per_page=50`, { headers });
    if (list.status() === 200) {
      const rows = ((await list.json()).records as Array<{ id: string; patent_number: string }>)
        .filter((r) => (r.patent_number || '').includes('TEST-PW-MAIN-001'));
      for (const row of rows) {
        const st = await page.request.get(`${API}/api/v1/faculty/${row.id}/status`, { headers });
        if (st.status() === 200 && (await st.json()).workflow_state === 'FACULTY_ASSOCIATION_PENDING') {
          const ar = await page.request.get(`${API}/api/v1/associations/`, { headers });
          if (ar.status() === 200) {
            const mine = ((await ar.json()).associations as Array<{ record_id: string }>)
              .filter((a) => a.record_id === row.id);
            if (mine.length === 0) { recordId = row.id; reused = true; break; }
          }
        }
      }
    }
  } catch { /* fall through to upload */ }
  if (!reused) {
    await page.goto('/faculty/upload');
    await page.locator('input[aria-label="Choose file"]').setInputFiles('tests/fixtures/pw-main.pdf');
    await page.getByRole('button', { name: 'Submit upload' }).click();
    await page.getByRole('button', { name: 'Open record' }).click({ timeout: 60_000 });
    await expect(page).toHaveURL(/\/faculty\/records\/.+/, { timeout: 30_000 });
    recordId = page.url().split('/').pop()!;
    expect(recordId.length).toBeGreaterThan(8);
    // Wait for the background pipeline to finish identity + derivation by
    // polling the status API (same mechanism tests 2-7 and the reuse scan
    // use). Polling locator text right after a full page.goto races against
    // the SPA's async hydration (auth/me -> status) and force-reloads the
    // page before it can render, so the API is the deterministic source here.
    // The UI itself is asserted below and in the later tests.
    const deadline = Date.now() + PIPELINE_DEADLINE_MS;
    for (;;) {
      const stRes = await page.request.get(`${API}/api/v1/faculty/${recordId}/status`, { headers });
      expect(stRes.status()).toBe(200);
      const body = await stRes.json();
      if (body.workflow_state === 'FACULTY_ASSOCIATION_PENDING') break;
      if (Date.now() > deadline) throw new Error(`pipeline never reached faculty stage (last ${body.workflow_state})`);
      await page.waitForTimeout(15_000);
    }
  } else {
    await page.goto(`/faculty/records/${recordId}`);
  }
  // Uploader auto-accepted note + exactly one bulk action, never a self button.
  await expect(page.getByText(/You uploaded this patent, so you are automatically accepted/)).toBeVisible();
  await expect(page.getByRole('button', { name: /^Send Association Request$/ })).toHaveCount(1);
});

test('2. Pipeline reaches faculty stage with zero requests (HODs see nothing)', async ({ page }) => {
  const headers = await apiLogin(page.request, U.FACA.email, PASSWORD);
  await waitWorkflow(page, recordId, headers, 'FACULTY_ASSOCIATION_PENDING');
  const res = await page.request.get(`${API}/api/v1/associations/`, { headers });
  expect(res.status()).toBe(200);
  expect((await res.json()).count).toBe(0);
  for (const hod of ['HOD_CSE', 'HOD_EEE', 'HOD_AIDS']) {
    const hh = await apiLogin(page.request, U[hod].email, PASSWORD);
    const docs = await page.request.get(`${API}/api/v1/hod/documents?per_page=50`, { headers: hh });
    expect(docs.status()).toBe(200);
    const ids = ((await docs.json()).documents as Array<{ id: string }>).map((d) => d.id);
    expect(ids).not.toContain(recordId);
  }
});

test('3. A sends once: only B/C/D/E get requests (idempotent)', async ({ page }) => {
  await loginAs(page, 'FACA', /\/faculty\/dashboard/);
  await page.goto(`/faculty/records/${recordId}`);
  await page.getByRole('button', { name: /^Send Association Request$/ }).click();
  await expect(page.getByText(/Association requests sent to 4 other facult/)).toBeVisible({ timeout: 30_000 });
  const headers = await apiHeaders(page);
  const res = await page.request.get(`${API}/api/v1/associations/`, { headers });
  const rows = (await res.json()).associations as Array<{ recipient_id: string; status: string }>;
  const targets = rows.map((r) => r.recipient_id).sort();
  expect(targets).toEqual([U.FACB.id, U.FACC.id, U.FACD.id, U.FACE.id].sort());
  expect(rows.every((r) => r.status === 'PENDING')).toBe(true);
  // Resend: nothing new.
  await page.getByRole('button', { name: /^Send Association Request$/ }).click();
  await expect(page.getByText(/already covered|No new requests needed/)).toBeVisible({ timeout: 30_000 });
});

test('4. B/C/D accept via inbox; E pending; HOD blocked with exact counts', async ({ page }) => {
  for (const key of ['FACB', 'FACC', 'FACD']) {
    await loginAs(page, key, /\/faculty\/dashboard/);
    await page.goto('/faculty/associations');
    const card = page.locator('.assoc-card', { hasText: MAIN_TITLE });
    await card.getByRole('button', { name: 'Accept' }).click();
    await expect(page.getByText(/Request accepted/)).toBeVisible({ timeout: 30_000 });
  }
  // HOD attempts verification while E is pending -> 409 with exact counts.
  await loginAs(page, 'HOD_CSE', /\/hod\/dashboard/);
  const headers = await apiHeaders(page);
  const v = await page.request.post(`${API}/api/v1/verification/institutional/${recordId}`,
    { headers, data: { decision: 'verify' } });
  expect(v.status()).toBe(409);
  const body = await v.json();
  expect(body.error).toBe('ASSOCIATION_PENDING');
  expect(body.details.required_count).toBe(4);
  expect(body.details.pending_count).toBe(1);
  expect(body.details.accepted_count).toBe(3);
  expect(body.details.pending_faculty.map((p: { id: string }) => p.id)).toEqual([U.FACE.id]);
  // HOD documents still hide the patent (0 docs in department at this stage).
  await page.goto('/hod/documents');
  await expect(page.getByRole('link', { name: MAIN_FILE })).toHaveCount(0);
});

test('5. E accepts: faculty complete, NO HOD requests, HODs gain visibility', async ({ page }) => {
  await loginAs(page, 'FACE', /\/faculty\/dashboard/);
  await page.goto('/faculty/associations');
  const card = page.locator('.assoc-card', { hasText: MAIN_TITLE });
  await card.getByRole('button', { name: 'Accept' }).click();
  await expect(page.getByText(/Request accepted/)).toBeVisible({ timeout: 30_000 });
  const headers = await apiHeaders(page);
  const res = await page.request.get(`${API}/api/v1/associations/`, { headers });
  const rows = (await res.json()).associations as Array<{ recipient_id: string; status: string }>;
  // No HOD approval request exists anywhere: HODs are read-only.
  const hodIds = [U.HOD_CSE.id, U.HOD_EEE.id, U.HOD_AIDS.id, U.HOD_XXX.id];
  expect(rows.filter((r) => hodIds.includes(r.recipient_id))).toEqual([]);
  // Each represented HOD now sees it; unrelated XXX HOD does not.
  // (HOD Documents table shows the file name in the Document column.)
  for (const hod of ['HOD_CSE', 'HOD_EEE', 'HOD_AIDS']) {
    await loginAs(page, hod, /\/hod\/dashboard/);
    await page.goto('/hod/documents');
    await expect(page.getByRole('link', { name: MAIN_FILE })).toBeVisible({ timeout: 60_000 });
  }
  await loginAs(page, 'HOD_XXX', /\/hod\/dashboard/);
  await page.goto('/hod/documents');
  await expect(page.getByRole('link', { name: MAIN_FILE })).toHaveCount(0);
});

test('6. No HOD approval surface exists; wrong HOD cannot act', async ({ page, request }) => {
  await loginAs(page, 'HOD_CSE', /\/hod\/dashboard/);
  await page.goto('/hod/documents');
  // Read-only: no approval buttons anywhere on HOD pages.
  await expect(page.getByRole('button', { name: 'Manual Verify' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Confirm Verified' })).toHaveCount(0);
  const xxx = await apiLogin(request, U.HOD_XXX.email, PASSWORD);
  const cse = await apiLogin(request, U.HOD_CSE.email, PASSWORD);
  const list = await request.get(`${API}/api/v1/associations/`, { headers: cse });
  const rows = (await list.json()).associations as Array<{ id: string; recipient_id: string; status: string; record_title: string }>;
  const facRow = rows.find((r) => r.status === 'PENDING' && (r.record_title || '').includes('Main'));
  // If any pending row exists, a non-recipient still gets 403.
  if (facRow) {
    const rj = await request.post(`${API}/api/v1/associations/${facRow.id}/respond?action=accepted`, { headers: xxx, data: {} });
    expect(rj.status()).toBe(403);
  }
  const fac = await apiLogin(request, U.FACB.email, PASSWORD);
  const v = await request.post(`${API}/api/v1/verification/institutional/${recordId}`,
    { headers: fac, data: { decision: 'verify' } });
  expect(v.status()).toBe(403);
});

test('7. Completion state is grant-ready (verified, no HOD gate)', async ({ page }) => {
  const headers = await apiLogin(page.request, U.FACA.email, PASSWORD);
  await waitWorkflow(page, recordId, headers, 'FACULTY_ASSOCIATION_COMPLETE');
});

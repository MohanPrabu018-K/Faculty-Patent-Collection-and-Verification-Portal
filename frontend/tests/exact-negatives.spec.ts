// Negative paths in a real browser (Chromium).
// Own reject-path record (upload -> send -> B rejects -> NEEDS_REVIEW):
// - rejection blocks verify/grant paths (refused rule)
// - non-recipient respond -> 403; faculty/HOD/anonymous grant -> refused
// - HOD documents hide pre-completion records
// - double send stays idempotent
// Env: E2E_CREDS_FILE, E2E_API_URL.
import { test, expect, type Page, type APIRequestContext } from '@playwright/test';
import fs from 'node:fs';

const API = process.env.E2E_API_URL || 'http://localhost:8000';
const CREDS = JSON.parse(fs.readFileSync(process.env.E2E_CREDS_FILE!, 'utf-8'));
const U = CREDS.users as Record<string, { id: string; email: string; full_name: string }>;
const PASSWORD: string = CREDS.password;
const REJ_TITLE = 'Playwright Reject Widget';
// Local backend runs WITHOUT E2E_TEST=1 (login_per_ip=10/60s); pace logins.
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

async function apiLogin(request: APIRequestContext, email: string, password: string) {
  await new Promise((r) => setTimeout(r, PACE_MS));
  const res = await request.post(`${API}/api/v1/auth/login`, { data: { email, password } });
  expect(res.status()).toBe(200);
  // headersArray() preserves each Set-Cookie header (access_token +
  // csrf_token) so the CSRF token is captured correctly for POSTs.
  const setCookie = res.headersArray()
    .filter((h) => h.name.toLowerCase() === 'set-cookie')
    .map((h) => h.value);
  const pairs = setCookie.map((c) => c.split(';')[0]).join('; ');
  const m = pairs.match(/csrf_token=([^;\s]+)/);
  const header: Record<string, string> = { Cookie: pairs };
  if (m) header['X-CSRF-Token'] = m[1];
  return header;
}

async function waitState(page: Page, recordId: string, headers: Record<string, string>, want: string) {
  // Fresh uploads on a cold backend can take >8 min (OCR warm-up + external
  // adapters); reuse of an already-pending record is fast.
  const deadline = Date.now() + 20 * 60_000;
  for (;;) {
    const res = await page.request.get(`${API}/api/v1/faculty/${recordId}/status`, { headers });
    expect(res.status()).toBe(200);
    if ((await res.json()).workflow_state === want) return;
    if (Date.now() > deadline) throw new Error(`record ${recordId} never reached ${want}`);
    await page.waitForTimeout(10_000);
  }
}

let rejId = '';

test('reject record: upload, send, double-send stays idempotent', async ({ page }) => {
  await loginAs(page, 'FACA', /\/faculty\/dashboard/);
  await page.goto('/faculty/upload');
  await page.locator('input[aria-label="Choose file"]').setInputFiles('tests/fixtures/pw-reject.pdf');
  await page.getByRole('button', { name: 'Submit upload' }).click();
  await page.getByRole('button', { name: 'Open record' }).click({ timeout: 60_000 });
  await expect(page).toHaveURL(/\/faculty\/records\/.+/, { timeout: 30_000 });
  rejId = page.url().split('/').pop()!;
  const headers = await apiLogin(page.request, U.FACA.email, PASSWORD);
  await waitState(page, rejId, headers, 'FACULTY_ASSOCIATION_PENDING');
  await page.goto(`/faculty/records/${rejId}`);
  await page.getByRole('button', { name: /^Send Association Request$/ }).click();
  await expect(page.getByText(/Association requests sent to 1 other faculty/)).toBeVisible({ timeout: 30_000 });
  // Second click creates nothing new.
  await page.getByRole('button', { name: /^Send Association Request$/ }).click();
  await expect(page.getByText(/already covered|No new requests needed/)).toBeVisible({ timeout: 30_000 });
});

test('faculty rejects: NEEDS_REVIEW, still blocked, HOD sees nothing', async ({ page }) => {
  await loginAs(page, 'FACB', /\/faculty\/dashboard/);
  await page.goto('/faculty/associations');
  await page.locator('.assoc-card', { hasText: REJ_TITLE }).getByRole('button', { name: 'Reject' }).click();
  await expect(page.getByText(/Request rejected/)).toBeVisible({ timeout: 30_000 });
  const headers = await apiLogin(page.request, U.FACA.email, PASSWORD);
  await waitState(page, rejId, headers, 'NEEDS_REVIEW');
  // Rejection blocks verification (refused rule): HOD gets 409, nothing recorded.
  const hh = await apiLogin(page.request, U.HOD_CSE.email, PASSWORD);
  const v = await page.request.post(`${API}/api/v1/verification/institutional/${rejId}`,
    { headers: hh, data: { decision: 'verify' } });
  expect(v.status()).toBe(409);
  expect((await v.json()).error).toBe('ASSOCIATION_PENDING');
  // HOD documents hide pre-completion records.
  await loginAs(page, 'HOD_CSE', /\/hod\/dashboard/);
  await page.goto('/hod/documents');
  await expect(page.getByText('TEST-PW-REJ-001')).toHaveCount(0);
});

test('authorization negatives: roles and anonymity', async ({ page, request }) => {
  const fac = await apiLogin(request, U.FACB.email, PASSWORD);
  const g1 = await request.post(`${API}/api/v1/admin/ip-records/${rejId}/grant`,
    { headers: fac, data: { confirm: true } });
  expect(g1.status()).toBe(403);
  const hod = await apiLogin(request, U.HOD_CSE.email, PASSWORD);
  const g2 = await request.post(`${API}/api/v1/admin/ip-records/${rejId}/grant`,
    { headers: hod, data: { confirm: true } });
  expect(g2.status()).toBe(403);
  const g3 = await request.post(`${API}/api/v1/admin/ip-records/${rejId}/grant`,
    { data: { confirm: true } });
  // No credentials at all: the CSRF layer rejects before auth.
  expect(g3.status()).toBe(400);
  // Non-recipient cannot respond (even on a terminal request row).
  const list = await request.get(`${API}/api/v1/associations/`, { headers: fac });
  const rows = (await list.json()).associations as Array<{ id: string; record_title: string }>;
  const target = rows.find((r) => (r.record_title || '').includes('Reject'));
  if (target) {
    const xxx = await apiLogin(request, U.HOD_XXX.email, PASSWORD);
    const rj = await request.post(`${API}/api/v1/associations/${target.id}/respond?action=accepted`,
      { headers: xxx, data: {} });
    expect(rj.status()).toBe(403);
  }
});

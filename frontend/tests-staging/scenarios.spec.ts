/**
 * Authenticated staging rule matrix — rules A–F.
 *
 * Runs against a LIVE staging (or local) stack provisioned by
 * `scripts/staging/provision_staging.py`. Every assertion is server-authoritative
 * (it checks the API's own enforcement, not the UI's).
 *
 * Serial, single worker: the scenarios create and mutate real rows. See
 * docs/STAGING_SETUP.md and frontend/tests-staging/README.md.
 */
import { test, expect, request, APIRequestContext } from '@playwright/test';
import { StagingClient } from './client';
import { account, record, loadFixtures } from './fixtures';
import { resolveStagingEnv } from './guard';

test.describe.configure({ mode: 'serial' });

const env = resolveStagingEnv();

let fac01: StagingClient;
let fac02: StagingClient;
let fac04: StagingClient;
let fac05: StagingClient;
let fac10: StagingClient;
let hodA: StagingClient;
let sa: StagingClient;

test.beforeAll(async () => {
  loadFixtures(); // fail fast if provisioning was not run
  [fac01, fac02, fac04, fac05, fac10, hodA, sa] = await Promise.all([
    StagingClient.login(env.apiUrl, account('faculty01')),
    StagingClient.login(env.apiUrl, account('faculty02')),
    StagingClient.login(env.apiUrl, account('faculty04')),
    StagingClient.login(env.apiUrl, account('faculty05')),
    StagingClient.login(env.apiUrl, account('faculty10')),
    StagingClient.login(env.apiUrl, account('hodA')),
    StagingClient.login(env.apiUrl, account('superAdmin')),
  ]);
});

test.afterAll(async () => {
  await Promise.all(
    [fac01, fac02, fac04, fac05, fac10, hodA, sa].filter(Boolean).map((c) => c.dispose()),
  );
});

// ---------------------------------------------------------------------------
// Rule A — uploader is auto-accepted and NEVER receives a self-request.
// ---------------------------------------------------------------------------
test.describe('Rule A — uploader auto-association + idempotent send-all', () => {
  test('A1: send-all auto-accepts the uploader and creates requests only for OTHER internal faculty', async () => {
    const r = await fac01.post('/api/v1/associations/send-all', { data: { record_id: record('a1') } });
    expect(r.status, r.text).toBe(200);
    expect(r.body.uploader.status).toBe('AUTO_ACCEPTED');
    expect(r.body.uploader.id).toBe(account('faculty01').id);
    expect(r.body.created).toContain(account('faculty02').id);
    expect(r.body.created).not.toContain(account('faculty01').id);
  });

  test('A2: send-all is idempotent — a second call creates nothing and reports existing coverage', async () => {
    const r = await fac01.post('/api/v1/associations/send-all', { data: { record_id: record('a1') } });
    expect(r.status, r.text).toBe(200);
    expect(r.body.created).toEqual([]);
    expect(r.body.already_pending).toContain(account('faculty02').id);
  });
});

// ---------------------------------------------------------------------------
// Rule B — association request sending / recipient-only response / IDOR.
// ---------------------------------------------------------------------------
test.describe('Rule B — association sending rules', () => {
  test('B1: a non-uploader cannot send association requests', async () => {
    const r = await fac02.post('/api/v1/associations/', {
      params: { recipient_faculty_id: account('faculty10').faculty_id as string },
      data: { record_id: record('a1') },
    });
    expect(r.status, r.text).toBe(403);
    expect(r.body.error).toBe('AUTHORIZATION_ERROR');
  });

  test('B2: HOD accounts can never be association recipients', async () => {
    const r = await fac01.post('/api/v1/associations/', {
      params: { recipient_faculty_id: account('hodA').faculty_id as string },
      data: { record_id: record('a1') },
    });
    expect(r.status, r.text).toBe(422);
  });

  test('B3: a duplicate association request is refused with 409', async () => {
    const r = await fac01.post('/api/v1/associations/', {
      params: { recipient_faculty_id: account('faculty04').faculty_id as string },
      data: { record_id: record('a1') },
    });
    expect(r.status, r.text).toBe(409);
  });

  test('B4: IDOR — a non-recipient cannot respond to someone else’s request', async () => {
    const r = await fac10.post(`/api/v1/associations/${loadFixtures().associations.pendingRecipient}/respond`, {
      params: { action: 'accepted' },
    });
    expect(r.status, r.text).toBe(403);
    expect(r.body.error).toBe('AUTHORIZATION_ERROR');
  });

  test('B5: the addressed recipient CAN accept the request', async () => {
    const r = await fac04.post(`/api/v1/associations/${loadFixtures().associations.pendingRecipient}/respond`, {
      params: { action: 'accepted' },
    });
    expect(r.status, r.text).toBe(200);
    expect(r.body.status).toBe('ACCEPTED');
  });
});

// ---------------------------------------------------------------------------
// Rule C — external contributors are never association recipients.
// ---------------------------------------------------------------------------
test.describe('Rule C — external contributors excluded', () => {
  test('C1: a record with only external co-contributors creates no internal requests', async () => {
    const r = await fac01.post('/api/v1/associations/send-all', { data: { record_id: record('extOnly') } });
    expect(r.status, r.text).toBe(200);
    expect(r.body.uploader.status).toBe('AUTO_ACCEPTED');
    expect(r.body.created).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Rule D — HODs are strictly read-only and department-scoped.
// ---------------------------------------------------------------------------
test.describe('Rule D — HOD read-only + department scoping', () => {
  test('D1: HOD can read dashboard / documents / duplicates / conflicts', async () => {
    expect((await hodA.get('/api/v1/hod/dashboard')).status).toBe(200);
    expect((await hodA.get('/api/v1/hod/documents')).status).toBe(200);
    expect((await hodA.get('/api/v1/duplicates/')).status).toBe(200);
    expect((await hodA.get('/api/v1/conflicts/')).status).toBe(200);
  });

  test('D2: HOD cannot perform institutional verification', async () => {
    const r = await hodA.post(`/api/v1/verification/institutional/${record('hodA')}`, {
      data: { decision: 'verify' },
    });
    expect(r.status, r.text).toBe(403);
  });

  test('D3: HOD cannot resolve duplicate cases', async () => {
    const r = await hodA.post(`/api/v1/duplicates/${loadFixtures().duplicates.deptA}/resolve`, {
      params: { keep_record_id: record('a1') },
    });
    expect(r.status, r.text).toBe(403);
  });

  test('D4: HOD cannot resolve conflict cases', async () => {
    const r = await hodA.post(`/api/v1/conflicts/${loadFixtures().conflicts.deptC}/resolve`);
    expect(r.status, r.text).toBe(403);
  });

  test('D5: HOD listings are scoped to the HOD’s own department', async () => {
    // documents: dept A record visible, dept B record hidden
    const docs = await hodA.get('/api/v1/hod/documents', { params: { per_page: 100 } });
    expect(docs.status).toBe(200);
    const ids = (docs.body.documents as Array<{ id: string }>).map((d) => d.id);
    expect(ids).toContain(record('hodA'));
    expect(ids).not.toContain(record('hodB'));

    // duplicates: dept A case visible, dept B case hidden
    const dups = await hodA.get('/api/v1/duplicates/');
    const dupIds = (dups.body.duplicate_cases as Array<{ id: string }>).map((c) => c.id);
    expect(dupIds).toContain(loadFixtures().duplicates.deptA);
    expect(dupIds).not.toContain(loadFixtures().duplicates.deptB);

    // conflicts: dept C conflict hidden from dept A HOD
    const confs = await hodA.get('/api/v1/hod/conflicts');
    const confIds = (confs.body.conflicts as Array<{ id: string }>).map((c) => c.id);
    expect(confIds).not.toContain(loadFixtures().conflicts.deptC);
  });
});

// ---------------------------------------------------------------------------
// Rule E — Super Admin: grant gates + duplicate/conflict resolution.
// ---------------------------------------------------------------------------
test.describe('Rule E — Super Admin grant gates', () => {
  test('E0: SA cannot accept/reject association requests (only recipients can)', async () => {
    const r = await sa.post(`/api/v1/associations/${loadFixtures().associations.pendingHod}/respond`, {
      params: { action: 'accepted' },
    });
    expect(r.status, r.text).toBe(403);
  });

  test('E1: grant requires explicit confirmation', async () => {
    const r = await sa.post(`/api/v1/admin/ip-records/${record('grantable')}/grant`, { data: {} });
    expect(r.status, r.text).toBe(422);
    expect(r.body.error).toBe('GRANT_CONFIRMATION_REQUIRED');
  });

  test('E2: a non-verified record cannot be granted', async () => {
    const r = await sa.post(`/api/v1/admin/ip-records/${record('needVerify')}/grant`, { data: { confirm: true } });
    expect(r.status, r.text).toBe(422);
    expect(r.body.error).toBe('GRANT_NOT_ELIGIBLE');
  });

  test('E3: a fully eligible record is granted', async () => {
    const r = await sa.post(`/api/v1/admin/ip-records/${record('grantable')}/grant`, { data: { confirm: true } });
    expect(r.status, r.text).toBe(200);
    expect(r.body.workflow_state).toBe('GRANTED');
  });

  test('E4: double-grant is refused', async () => {
    const r = await sa.post(`/api/v1/admin/ip-records/${record('grantable')}/grant`, { data: { confirm: true } });
    expect(r.status, r.text).toBe(422);
    expect(r.body.error).toBe('GRANT_ALREADY_GRANTED');
  });

  test('E5: SA can resolve a duplicate case', async () => {
    const r = await sa.post(`/api/v1/duplicates/${loadFixtures().duplicates.deptB}/resolve`, {
      params: { keep_record_id: record('b1') },
      data: { action: 'resolve' },
    });
    expect(r.status, r.text).toBe(200);
    expect(r.body.status).toBe('RESOLVED');
  });

  test('E6: SA can resolve a conflict case', async () => {
    const r = await sa.post(`/api/v1/conflicts/${loadFixtures().conflicts.deptC}/resolve`, {
      data: { action: 'resolve' },
    });
    expect(r.status, r.text).toBe(200);
    expect(r.body.status).toBe('RESOLVED');
  });

  test('E7: SA can read the admin dashboard', async () => {
    expect((await sa.get('/api/v1/admin/dashboard')).status).toBe(200);
  });
});

// ---------------------------------------------------------------------------
// Rule F — cross-cutting: RBAC, CSRF, deactivation, audit, UI smoke.
// ---------------------------------------------------------------------------
test.describe('Rule F — cross-cutting enforcement', () => {
  test('F1: faculty cannot reach admin endpoints', async () => {
    const r = await fac01.get('/api/v1/admin/dashboard');
    expect(r.status, r.text).toBe(403);
  });

  test('F2: a cookie-authenticated POST without the CSRF token is rejected', async () => {
    const r = await fac01.post('/api/v1/associations/send-all', {
      data: { record_id: record('a2') },
      bearer: false,
      csrf: false,
    });
    expect(r.status, r.text).toBe(400);
    expect(r.text).toContain('CSRF_TOKEN_INVALID');
  });

  test('F3: a deactivated account cannot log in', async () => {
    const ctx: APIRequestContext = await request.newContext({ baseURL: env.apiUrl, ignoreHTTPSErrors: true });
    try {
      const acc = account('facultyDeactivated');
      const res = await ctx.post('/api/v1/auth/login', {
        data: { email: acc.email, password: acc.password },
        failOnStatusCode: false,
      });
      expect(res.status()).toBe(401);
      expect(await res.text()).toContain('deactivated');
    } finally {
      await ctx.dispose();
    }
  });

  test('F4: the grant recorded an audit trail', async () => {
    const r = await sa.get('/api/v1/audit/', { params: { action: 'PATENT_GRANTED' } });
    expect(r.status, r.text).toBe(200);
    expect(r.body.total).toBeGreaterThan(0);
  });

  test('F5: an unauthenticated browser session is redirected to /login', async ({ page }) => {
    await page.goto('/admin/dashboard');
    await expect(page).toHaveURL(/\/login/);
  });
});

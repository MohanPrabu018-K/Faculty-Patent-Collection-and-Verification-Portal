// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api } from './client';

const GRANT_PATH = '/admin/ip-records/rec-1/grant';

type FetchMock = ReturnType<typeof vi.fn>;

function mockFetch(handler: (url: string, init?: RequestInit) => unknown): FetchMock {
  const mock = vi.fn(async (url: string, init?: RequestInit) => handler(url, init));
  vi.stubGlobal('fetch', mock);
  return mock;
}

function jsonRes(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
    json: async () => body,
  };
}

function clearCookies() {
  for (const part of document.cookie.split(';')) {
    const name = part.split('=')[0]?.trim();
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  }
}

function headersOf(mock: FetchMock, callIndex: number): Record<string, string> {
  return ((mock.mock.calls[callIndex]?.[1] as RequestInit)?.headers ?? {}) as Record<string, string>;
}

function urlOf(mock: FetchMock, callIndex: number): string {
  return String(mock.mock.calls[callIndex]?.[0] ?? '');
}

async function seedSession(jwt = 'jwt-session', csrf = 'csrf-session') {
  mockFetch(async (url: string) => {
    if (String(url).endsWith('/auth/login')) {
      return jsonRes(200, { access_token: jwt, token_type: 'bearer', expires_in: 1800, csrf_token: csrf, user: { id: 'u1', email: 'a@b.c', full_name: 'A', role: 'super_admin' } });
    }
    return jsonRes(404, 'not found');
  });
  await api.login('a@b.c', 'pw');
}

beforeEach(() => {
  clearCookies();
  vi.unstubAllGlobals();
});

describe('shared API client security wiring (grant flow)', () => {
  it('grant request carries Authorization + X-CSRF-Token with credentials included', async () => {
    await seedSession('jwt-1', 'csrf-1');
    const mock = mockFetch(async () => jsonRes(200, { id: 'rec-1', workflow_state: 'GRANTED' }));
    await api.adminGrantPatent('rec-1');
    expect(mock).toHaveBeenCalledTimes(1);
    expect(urlOf(mock, 0)).toContain(GRANT_PATH);
    const headers = headersOf(mock, 0);
    expect(headers['Authorization']).toBe('Bearer jwt-1');
    expect(headers['X-CSRF-Token']).toBe('csrf-1');
    expect((mock.mock.calls[0]?.[1] as RequestInit)?.credentials).toBe('include');
    expect((mock.mock.calls[0]?.[1] as RequestInit)?.method).toBe('POST');
  });

  it('recovers from a stale CSRF pair via bootstrap and retries exactly once', async () => {
    await seedSession('jwt-1', 'csrf-stale');
    let calls = 0;
    const mock = mockFetch(async (url: string) => {
      calls += 1;
      const u = String(url);
      if (u.endsWith('/auth/csrf')) return jsonRes(200, { csrf_token: 'csrf-fresh' });
      if (calls === 1) return jsonRes(400, JSON.stringify({ error: 'CSRF_TOKEN_INVALID', message: 'Invalid or missing CSRF token' }));
      return jsonRes(200, { id: 'rec-1', workflow_state: 'GRANTED' });
    });
    const res = (await api.adminGrantPatent('rec-1')) as { workflow_state: string };
    expect(res.workflow_state).toBe('GRANTED');
    expect(mock).toHaveBeenCalledTimes(3);
    expect(headersOf(mock, 0)['X-CSRF-Token']).toBe('csrf-stale');
    expect(urlOf(mock, 1)).toContain('/auth/csrf');
    expect(headersOf(mock, 2)['X-CSRF-Token']).toBe('csrf-fresh');
  });

  it('does not retry when the first attempt succeeds', async () => {
    await seedSession('jwt-1', 'csrf-1');
    const mock = mockFetch(async () => jsonRes(200, { ok: true }));
    await api.adminGrantPatent('rec-1');
    expect(mock).toHaveBeenCalledTimes(1);
  });

  it('surfaces 401 without a CSRF bootstrap attempt', async () => {
    await seedSession('jwt-1', 'csrf-1');
    const mock = mockFetch(async () => jsonRes(401, JSON.stringify({ error: 'AUTH' })));
    await expect(api.adminGrantPatent('rec-1')).rejects.toMatchObject({ status: 401 });
    expect(mock).toHaveBeenCalledTimes(1);
  });

  it('never fabricates a CSRF token when none is available', async () => {
    await seedSession('jwt-1', 'csrf-1');
    // Log out clears in-memory tokens; cookies already cleared in beforeEach.
    mockFetch(async () => jsonRes(200, {}));
    await api.logout();
    const mock = mockFetch(async () => jsonRes(200, { ok: true }));
    await api.adminGrantPatent('rec-1');
    expect(headersOf(mock, 0)['Authorization']).toBeUndefined();
    expect(headersOf(mock, 0)['X-CSRF-Token']).toBeUndefined();
  });

  it('prefers the CSRF cookie over a stale in-memory token', async () => {
    await seedSession('jwt-1', 'csrf-stale-memory');
    document.cookie = 'csrf_token=csrf-cookie-fresh';
    const mock = mockFetch(async () => jsonRes(200, { ok: true }));
    await api.adminGrantPatent('rec-1');
    expect(headersOf(mock, 0)['X-CSRF-Token']).toBe('csrf-cookie-fresh');
  });
});

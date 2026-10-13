/**
 * Minimal HTTP client for the staging API, driven by Playwright's
 * APIRequestContext (real HTTP, real cookie jar — no mocks).
 *
 * Auth mirrors the browser: login returns an `access_token` + `csrf_token`;
 * we send the bearer token on normal calls and add `X-CSRF-Token` on
 * state-changing calls. `bearer:false` / `csrf:false` let a test exercise the
 * negative paths (CSRF rejection in particular).
 */
import { APIRequestContext, request } from '@playwright/test';
import type { Account } from './fixtures';

export type ReqOptions = {
  data?: unknown;
  params?: Record<string, string | number>;
  headers?: Record<string, string>;
  bearer?: boolean;
  csrf?: boolean;
};

export type ApiResult = {
  status: number;
  body: any;
  text: string;
};

export class StagingClient {
  private constructor(
    private readonly ctx: APIRequestContext,
    private readonly bearerToken: string,
    private readonly csrfToken: string,
    readonly account: Account,
  ) {}

  static async login(apiUrl: string, acc: Account): Promise<StagingClient> {
    const ctx = await request.newContext({
      baseURL: apiUrl,
      ignoreHTTPSErrors: true,
      extraHTTPHeaders: { Accept: 'application/json' },
    });
    const res = await ctx.post('/api/v1/auth/login', {
      data: { email: acc.email, password: acc.password },
      failOnStatusCode: false,
    });
    const text = await res.text();
    if (res.status() !== 200) {
      await ctx.dispose();
      throw new Error(`[staging] login failed for ${acc.email} (${res.status()}): ${text}`);
    }
    const body = JSON.parse(text);
    return new StagingClient(ctx, body.access_token, body.csrf_token, acc);
  }

  async request(method: string, path: string, opts: ReqOptions = {}): Promise<ApiResult> {
    const headers: Record<string, string> = { ...(opts.headers || {}) };
    if (opts.bearer !== false && this.bearerToken) headers['Authorization'] = `Bearer ${this.bearerToken}`;
    if (method !== 'GET' && opts.csrf !== false && this.csrfToken) headers['X-CSRF-Token'] = this.csrfToken;

    const res = await this.ctx.fetch(path, {
      method,
      headers,
      data: opts.data,
      params: opts.params,
      failOnStatusCode: false,
    });
    const text = await res.text();
    let body: any = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = null;
    }
    return { status: res.status(), body, text };
  }

  get(path: string, opts: ReqOptions = {}) {
    return this.request('GET', path, opts);
  }
  post(path: string, opts: ReqOptions = {}) {
    return this.request('POST', path, opts);
  }
  patch(path: string, opts: ReqOptions = {}) {
    return this.request('PATCH', path, opts);
  }

  async dispose(): Promise<void> {
    await this.ctx.dispose();
  }
}

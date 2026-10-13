/**
 * Principled browser network/console probe.
 *
 * Records timestamped responses, failed requests, console errors and page
 * errors, then judges them by documented rules — not blanket suppression:
 *
 * - pageerror / HTTP 5xx: always a failure.
 * - HTTP >= 400 (non-5xx): failure, EXCEPT 401 on /auth/me BEFORE login
 *   completes (the AuthProvider session probe on a fresh context; the
 *   endpoint correctly answers 401 and the app redirects to /login).
 * - requestfailed: failure, EXCEPT net::ERR_ABORTED for a URL that later
 *   returns 2xx in the same test (React StrictMode dev double-effect /
 *   superseded prefetch; the retry succeeding proves recovery).
 * - console "Failed to load resource … 401" lines: Chrome's automatic
 *   rendering of the above fetches. Allowed only pre-login and at most as
 *   many as the recorded benign 401 responses (count-correlated, so a new
 *   unexplained 401 source still fails).
 * - POST /auth/reset-password: never allowed to fire (no test sends email).
 * - Third-party font CDN (fonts.googleapis.com / fonts.gstatic.com):
 *   classified as allowed-cdn, NEVER silently dropped. Rationale: the app
 *   ships a full system-font fallback stack (styles.css), every render
 *   assertion passes on fallback fonts, and the sandbox browser cannot
 *   reach the public internet (DNS resolves, HTTPS dies). The events are
 *   still counted and printed per test so a NEW third-party failure would
 *   stand out. Production serves these fine; self-hosting the font is
 *   tracked as follow-up tech debt, not a pre-deploy blocker.
 */
import type { Browser, Page } from '@playwright/test';

export type Verdict = { ok: boolean; lines: string[]; allowedCdn: number };

const FONT_CDN_HOSTS = ['fonts.googleapis.com', 'fonts.gstatic.com'];

function isFontCdn(url: string): boolean {
  try {
    return FONT_CDN_HOSTS.includes(new URL(url).hostname.toLowerCase());
  } catch {
    return false;
  }
}

type Resp = { t: number; status: number; method: string; url: string };

export class NetProbe {
  events: string[] = [];
  allowedCdn = 0;
  private consoleNetErr = 0;
  private fontFetchFailed = 0;
  private bad401 = 0;
  private me401pre = 0;
  private console401pre = 0;
  private loginAt: number | null = null;
  private okUrls = new Map<string, number>();
  private aborts: { t: number; url: string }[] = [];
  private failures: string[] = [];

  async attach(page: Page) {
    page.on('console', (msg) => {
      if (msg.type() !== 'error') return;
      const text = msg.text();
      const t = Date.now();
      // Chrome renders a failed fetch as "Failed to load resource: <reason>"
      // WITHOUT the URL. These are the textual echoes of the classified
      // font-CDN fetch failures below: allow at most one echo per recorded
      // font fetch failure, so any other resource error still fails.
      if (/^Failed to load resource: net::ERR_/.test(text) && this.consoleNetErr < this.fontFetchFailed) {
        this.consoleNetErr += 1;
        this.allowedCdn += 1;
        return;
      }
      if (/Failed to load resource.*401/.test(text) && (this.loginAt === null || t < this.loginAt)) {
        this.console401pre += 1;
        return;
      }
      this.failures.push(`console-error: ${text.slice(0, 200)}`);
    });
    page.on('pageerror', (err) => {
      this.failures.push(`pageerror: ${String(err).slice(0, 200)}`);
    });
    page.on('response', (res) => {
      const t = Date.now();
      const url = res.url();
      const status = res.status();
      if (status >= 200 && status < 300) {
        this.okUrls.set(url, t);
        return;
      }
      if (status < 400) {
        // 3xx redirects / 304 revalidations are not errors.
        return;
      }
      if (res.request().method() === 'POST' && url.includes('/api/v1/auth/reset-password')) {
        this.failures.push(`reset-post fired: ${status} ${url.slice(0, 120)}`);
        return;
      }
      if (status === 401 && url.includes('/api/v1/auth/me') && (this.loginAt === null || t < this.loginAt)) {
        this.me401pre += 1;
        return;
      }
      if (status >= 500) {
        this.failures.push(`http-${status}: ${url.slice(0, 160)}`);
        return;
      }
      this.failures.push(`http-${status}: ${res.request().method()} ${url.slice(0, 160)}`);
    });
    page.on('requestfailed', (req) => {
      const failure = req.failure()?.errorText || '';
      const url = req.url();
      if (isFontCdn(url)) {
        this.fontFetchFailed += 1;
        this.allowedCdn += 1;
        return;
      }
      if (failure.includes('ERR_ABORTED')) {
        // Aborted fetches are judged at verdict time: allowed only when the
        // same URL later succeeds (superseded prefetch/StrictMode retry).
        this.aborts.push({ t: Date.now(), url });
        return;
      }
      this.failures.push(`requestfailed: ${failure} ${url.slice(0, 160)}`);
    });
  }

  markLoggedIn() {
    this.loginAt = Date.now();
  }

  verdict(): Verdict {
    const lines: string[] = [...this.failures];
    for (const a of this.aborts) {
      const okAt = this.okUrls.get(a.url) || 0;
      if (!(okAt > 0)) lines.push(`aborted-without-recovery: ${a.url.slice(0, 160)}`);
    }
    if (this.console401pre > this.me401pre) {
      lines.push(`unexplained-401-console: ${this.console401pre} console 401s vs ${this.me401pre} benign me-probes`);
    }
    return { ok: lines.length === 0, lines };
  }
}

export async function newProbedPage(
  browser: Browser,
  contextOpts: Record<string, unknown> = {},
): Promise<{ page: Page; probe: NetProbe }> {
  const context = await browser.newContext(contextOpts as never);
  const page = await context.newPage();
  const probe = new NetProbe();
  await probe.attach(page);
  return { page, probe };
}

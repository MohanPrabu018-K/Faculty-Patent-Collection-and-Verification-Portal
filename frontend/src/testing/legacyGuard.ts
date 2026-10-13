/**
 * Fail-closed loopback guard for the LEGACY Playwright configs
 * (`playwright.config.ts`, `playwright-e2e.config.ts`, `playwright-exact.config.ts`).
 *
 * Why this exists
 * ---------------
 * The legacy suite under `frontend/tests/**` predates the authenticated staging
 * suite and has no environment guard of its own. Those specs log in with real
 * accounts and perform irreversible workflow actions (uploads, association
 * accepts, patent grants), so the ONLY safe target is a purely local stack.
 *
 * Rules (fail closed):
 *   1. Every legacy run defaults to loopback FRONTEND_URL / API_URL.
 *   2. Known production hosts are refused outright.
 *   3. The whole `*.pages.dev` and `*.onrender.com` namespaces are refused,
 *      including in the middle of a hostname (suffix spoofing).
 *   4. ANY non-loopback override is refused. There is deliberately no
 *      allow-list — the legacy suite is loopback-only.
 *   5. The Playwright `webServer` is pinned to the frontend dev server
 *      (`npm run dev`) at a loopback URL, so it can never boot a process that
 *      talks to a remote / production database.
 *
 * This module is pure and dependency-free. It is exercised without a server or
 * database by `frontend/src/testing/legacyGuard.test.ts` (vitest).
 */

export const KNOWN_PRODUCTION_HOSTS: readonly string[] = [
  'faculty-patent-collection-and-verification-portal.pages.dev',
  'faculty-patent-portal-api.onrender.com',
];

/** Production hosting namespaces — refused for ANY host ending in these labels. */
export const PRODUCTION_HOST_SUFFIXES: readonly string[] = ['.pages.dev', '.onrender.com'];

const LOOPBACK_HOSTS: ReadonlySet<string> = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

export const DEFAULT_FRONTEND_URL = 'http://localhost:5173';
export const DEFAULT_API_URL = 'http://localhost:8000';

export type LegacyEnv = {
  baseUrl: string;
  apiUrl: string;
};

export type DevWebServer = {
  command: string;
  url: string;
  reuseExistingServer: boolean;
  timeout: number;
  env: Record<string, string>;
};

/** The API base the frontend app calls: `<apiUrl>` without a trailing slash + `/api/v1`. */
export function apiBaseOf(apiUrl: string): string {
  return `${apiUrl.replace(/\/+$/, '')}/api/v1`;
}

/**
 * Parse a URL and return its normalized hostname. Throws (fail closed) on an
 * empty value, a malformed URL, a non-http(s) scheme, or a missing host.
 */
function parseHost(label: string, rawUrl: string): string {
  const value = (rawUrl ?? '').trim();
  if (!value) {
    throw new Error(`[legacy-guard] ${label} is empty. Refusing to run.`);
  }

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`[legacy-guard] ${label} is not a valid URL: ${JSON.stringify(value)}`);
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error(
      `[legacy-guard] ${label} must use http or https, got "${parsed.protocol}". Refusing to run.`,
    );
  }

  // URL.hostname keeps IPv6 brackets ("[::1]") and lower-cases the rest.
  let host = parsed.hostname.toLowerCase();
  // Collapse a single trailing DNS dot ("localhost." === "localhost").
  if (host.endsWith('.') && host !== '.') host = host.slice(0, -1);

  if (!host) {
    throw new Error(`[legacy-guard] ${label} has no host: ${JSON.stringify(value)}`);
  }
  return host;
}

export function isLoopbackHost(host: string): boolean {
  return LOOPBACK_HOSTS.has(host.toLowerCase());
}

/**
 * True when the host is a known production host or ends with a production
 * namespace on a label boundary (so `notpages.dev` / `pages.dev.evil.com` are
 * NOT treated as production — they are simply not loopback and get refused).
 */
export function isProductionHost(host: string): boolean {
  const h = host.toLowerCase();
  return KNOWN_PRODUCTION_HOSTS.includes(h) || PRODUCTION_HOST_SUFFIXES.some((suffix) => h.endsWith(suffix));
}

/**
 * Throwing guard for a single URL. Returns the normalized hostname on success.
 * Loopback passes; production and any other non-loopback target abort the run.
 */
export function assertLoopback(label: string, url: string): string {
  const host = parseHost(label, url);

  if (isProductionHost(host)) {
    throw new Error(
      `[legacy-guard] ${label} points at the production host ${host}. ` +
        'The legacy suite may only run against loopback. Refusing to run.',
    );
  }
  if (!isLoopbackHost(host)) {
    throw new Error(
      `[legacy-guard] ${label} host ${host} is not loopback. The legacy suite is ` +
        'loopback-only; remote targets are refused. Refusing to run.',
    );
  }
  return host;
}

/** Guard an optional URL: empty / unset is allowed, anything present must be loopback. */
export function assertOptionalLoopback(label: string, rawUrl: string | undefined): void {
  if (!(rawUrl ?? '').trim()) return;
  assertLoopback(label, rawUrl as string);
}

/**
 * Resolve + validate the legacy environment. Defaults to loopback and throws on
 * anything non-loopback (including production hosts). Also validates
 * `E2E_API_URL` when present, since the exact/e2e specs read it directly.
 */
export function resolveLegacyEnv(env: NodeJS.ProcessEnv = process.env): LegacyEnv {
  assertOptionalLoopback('E2E_API_URL', env.E2E_API_URL);

  const baseUrl = (env.FRONTEND_URL || DEFAULT_FRONTEND_URL).trim();
  const apiUrl = (env.API_URL || DEFAULT_API_URL).trim();

  assertLoopback('FRONTEND_URL', baseUrl);
  assertLoopback('API_URL', apiUrl);

  return { baseUrl, apiUrl };
}

/**
 * Build the Playwright `webServer` block. The command is hard-pinned to the
 * frontend dev server (`npm run dev`); callers cannot substitute a backend /
 * DB-connected command. Both the webServer URL and the API URL must be
 * loopback, and the browser app's API target is pinned via `VITE_API_BASE_URL`.
 *
 * Why pin `VITE_API_BASE_URL`: the browser under test calls the API from the
 * Vite-served app, which resolves its base from `import.meta.env`. Vite gives an
 * existing process env var priority over any `.env` file, so pinning it here
 * means a stray `frontend/.env` (e.g. a remote API) can never make the browser
 * silently send requests to a non-loopback API. See `frontend/src/api/client.ts`.
 */
export function guardedDevWebServer(
  url: string,
  options: { apiUrl: string; reuseExistingServer?: boolean; timeout?: number },
): DevWebServer {
  assertLoopback('webServer.url', url);
  assertLoopback('webServer.apiUrl', options.apiUrl);
  return {
    command: 'npm run dev', // frontend dev server only — never a backend / DB-connected process
    url,
    reuseExistingServer: options.reuseExistingServer ?? !process.env.CI,
    timeout: options.timeout ?? 120_000,
    env: { VITE_API_BASE_URL: apiBaseOf(options.apiUrl) },
  };
}

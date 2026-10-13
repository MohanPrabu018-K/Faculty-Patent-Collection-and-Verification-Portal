/**
 * Fail-closed environment guard for the staging Playwright project.
 *
 * The project must never run against production. This module contains the pure
 * decision logic (easily unit-testable, see `00-guard.spec.ts`) and is invoked
 * at config-load time by `playwright-staging.config.ts`.
 *
 * Rules:
 *   1. STAGING_CONFIRM must equal "1" (explicit human acknowledgement).
 *   2. STAGING_FRONTEND_URL and STAGING_API_URL must both be set.
 *   3. Loopback hosts are always allowed.
 *   4. The known production URLs are ALWAYS refused, even if allow-listed.
 *   5. Any other non-loopback host must appear in STAGING_ALLOWED_HOSTS.
 */

export const KNOWN_PRODUCTION_HOSTS: readonly string[] = [
  'faculty-patent-collection-and-verification-portal.pages.dev',
  'faculty-patent-portal-api.onrender.com',
];

export type StagingEnv = {
  frontendUrl: string;
  apiUrl: string;
  allowedHosts: string[];
};

export function hostOf(url: string): string {
  return new URL(url).hostname.toLowerCase();
}

export function isLoopbackHost(host: string): boolean {
  return (
    host === 'localhost' ||
    host === '127.0.0.1' ||
    host === '::1' ||
    host === '[::1]' ||
    host === ''
  );
}

/** Throwing guard for a single URL. Exported for direct unit testing. */
export function assertNotProduction(label: string, url: string, allowedHosts: string[] = []): string {
  let host: string;
  try {
    host = hostOf(url);
  } catch {
    throw new Error(`[staging-guard] ${label} is not a valid URL: ${url}`);
  }
  if (isLoopbackHost(host)) return host;
  if (KNOWN_PRODUCTION_HOSTS.includes(host)) {
    throw new Error(`[staging-guard] ${label} points at the known PRODUCTION host ${host}. Refusing to run.`);
  }
  if (!allowedHosts.map((h) => h.toLowerCase()).includes(host)) {
    throw new Error(
      `[staging-guard] ${label} host ${host} is not loopback and not in STAGING_ALLOWED_HOSTS ` +
        `(${allowedHosts.join(', ') || 'empty'}). Refusing to run against an unconfirmed environment.`,
    );
  }
  return host;
}

/** Resolve + validate the staging environment. Throws on anything unconfirmed. */
export function resolveStagingEnv(env: NodeJS.ProcessEnv = process.env): StagingEnv {
  if (env.STAGING_CONFIRM !== '1') {
    throw new Error(
      '[staging-guard] STAGING_CONFIRM must be "1". Set it only once you have verified the ' +
        'target environment is NOT production.',
    );
  }
  const frontendUrl = (env.STAGING_FRONTEND_URL || '').trim();
  const apiUrl = (env.STAGING_API_URL || '').trim();
  if (!frontendUrl) throw new Error('[staging-guard] STAGING_FRONTEND_URL is required.');
  if (!apiUrl) throw new Error('[staging-guard] STAGING_API_URL is required.');

  const allowedHosts = (env.STAGING_ALLOWED_HOSTS || '')
    .split(',')
    .map((h) => h.trim())
    .filter(Boolean);

  assertNotProduction('STAGING_FRONTEND_URL', frontendUrl, allowedHosts);
  assertNotProduction('STAGING_API_URL', apiUrl, allowedHosts);

  return { frontendUrl, apiUrl, allowedHosts };
}

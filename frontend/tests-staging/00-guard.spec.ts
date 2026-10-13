/**
 * Guard self-checks — NO network required.
 *
 * These tests prove the fail-closed logic that protects the suite from ever
 * pointing at production. They can (and should) be run standalone:
 *
 *   $env:STAGING_CONFIRM='1'
 *   $env:STAGING_FRONTEND_URL='http://localhost:5173'
 *   $env:STAGING_API_URL='http://localhost:8000'
 *   npx playwright test -c playwright-staging.config.ts 00-guard.spec.ts
 */
import { test, expect } from '@playwright/test';
import { assertNotProduction, isLoopbackHost, resolveStagingEnv, KNOWN_PRODUCTION_HOSTS } from './guard';

test.describe('staging guard (in-process)', () => {
  test('refuses to run without explicit confirmation', () => {
    expect(() =>
      resolveStagingEnv({
        STAGING_FRONTEND_URL: 'http://localhost:5173',
        STAGING_API_URL: 'http://localhost:8000',
      } as NodeJS.ProcessEnv),
    ).toThrow(/STAGING_CONFIRM/);
  });

  test('requires both URLs', () => {
    expect(() =>
      resolveStagingEnv({ STAGING_CONFIRM: '1', STAGING_API_URL: 'http://localhost:8000' } as NodeJS.ProcessEnv),
    ).toThrow(/STAGING_FRONTEND_URL/);
    expect(() =>
      resolveStagingEnv({ STAGING_CONFIRM: '1', STAGING_FRONTEND_URL: 'http://localhost:5173' } as NodeJS.ProcessEnv),
    ).toThrow(/STAGING_API_URL/);
  });

  test('refuses the known production frontend and backend hosts even if allow-listed', () => {
    for (const host of KNOWN_PRODUCTION_HOSTS) {
      expect(() => assertNotProduction('x', `https://${host}`, [host])).toThrow(/PRODUCTION/);
    }
  });

  test('refuses a non-loopback host that is not allow-listed', () => {
    expect(() => assertNotProduction('x', 'https://staging.example.com', [])).toThrow(/not in STAGING_ALLOWED_HOSTS/);
  });

  test('allows loopback', () => {
    expect(isLoopbackHost('localhost')).toBe(true);
    expect(isLoopbackHost('127.0.0.1')).toBe(true);
    expect(assertNotProduction('x', 'http://127.0.0.1:8000')).toBe('127.0.0.1');
  });

  test('accepts a confirmed loopback environment', () => {
    const env = resolveStagingEnv({
      STAGING_CONFIRM: '1',
      STAGING_FRONTEND_URL: 'http://localhost:5173',
      STAGING_API_URL: 'http://localhost:8000',
    } as NodeJS.ProcessEnv);
    expect(env.frontendUrl).toBe('http://localhost:5173');
    expect(env.apiUrl).toBe('http://localhost:8000');
  });

  test('accepts an explicitly allow-listed staging host', () => {
    const env = resolveStagingEnv({
      STAGING_CONFIRM: '1',
      STAGING_FRONTEND_URL: 'https://staging-portal.example.net',
      STAGING_API_URL: 'https://staging-api.example.net',
      STAGING_ALLOWED_HOSTS: 'staging-portal.example.net, staging-api.example.net',
    } as NodeJS.ProcessEnv);
    expect(env.allowedHosts).toHaveLength(2);
  });
});

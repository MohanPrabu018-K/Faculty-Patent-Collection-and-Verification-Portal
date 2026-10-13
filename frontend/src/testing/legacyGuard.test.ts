// Focused unit tests for the legacy Playwright loopback guard.
// No server, no browser, no database — pure decision logic only.
import { describe, expect, it } from 'vitest';
import {
  DEFAULT_API_URL,
  DEFAULT_FRONTEND_URL,
  KNOWN_PRODUCTION_HOSTS,
  apiBaseOf,
  assertLoopback,
  assertOptionalLoopback,
  guardedDevWebServer,
  isLoopbackHost,
  isProductionHost,
  resolveLegacyEnv,
} from './legacyGuard';

describe('legacy guard — loopback allowed', () => {
  it.each([
    'http://localhost:5173',
    'http://127.0.0.1:8000',
    'https://localhost',
    'http://[::1]:8000',
    'http://LOCALHOST:5173',
    'http://localhost.:5173',
    'http://2130706433:8000', // decimal form of 127.0.0.1 — normalizes to loopback
  ])('allows %s', (url) => {
    expect(() => assertLoopback('FRONTEND_URL', url)).not.toThrow();
  });

  it('normalizes the decimal form of 127.0.0.1 to the loopback host', () => {
    expect(assertLoopback('API_URL', 'http://2130706433:8000')).toBe('127.0.0.1');
  });

  it('returns the normalized hostname', () => {
    expect(assertLoopback('API_URL', 'http://LOCALHOST:8000')).toBe('localhost');
  });

  it('classifies loopback hosts', () => {
    expect(isLoopbackHost('localhost')).toBe(true);
    expect(isLoopbackHost('127.0.0.1')).toBe(true);
    expect(isLoopbackHost('[::1]')).toBe(true);
    expect(isLoopbackHost('localhost.evil.com')).toBe(false);
  });
});

describe('legacy guard — production hosts refused', () => {
  it.each([
    ...KNOWN_PRODUCTION_HOSTS.map((h) => `https://${h}`),
    'https://anything.pages.dev',
    'http://foo.onrender.com:443',
    'https://a.b.c.pages.dev',
  ])('refuses %s', (url) => {
    expect(() => assertLoopback('API_URL', url)).toThrow(/production/i);
  });

  it('flags production namespaces on a label boundary only', () => {
    expect(isProductionHost('foo.pages.dev')).toBe(true);
    expect(isProductionHost('api.onrender.com')).toBe(true);
    expect(isProductionHost(KNOWN_PRODUCTION_HOSTS[0])).toBe(true);
    // Merely containing the string is NOT production (and must still be refused
    // as non-loopback, never silently allowed).
    expect(isProductionHost('notpages.dev')).toBe(false);
    expect(isProductionHost('pages.dev.evil.com')).toBe(false);
  });
});

describe('legacy guard — remote hosts refused', () => {
  it.each([
    'https://faculty.example.edu',
    'http://192.168.1.10:8000',
    'http://10.0.0.5',
    'https://staging-portal.example.net',
    'http://0.0.0.0:8000',
    'http://127.0.0.2:8000',
    'http://3232235778:8000', // decimal form of 192.168.0.2 — still refused
  ])('refuses %s', (url) => {
    expect(() => assertLoopback('API_URL', url)).toThrow(/loopback|production/i);
  });
});

describe('legacy guard — hostname suffix spoofing refused', () => {
  it.each([
    'http://localhost.evil.com', // loopback label smuggled in as a subdomain
    'http://127.0.0.1.evil.com',
    'https://pages.dev.evil.com', // production namespace as an earlier label
    'https://foo.pages.dev.evil.com',
    'https://evil-pages.dev', // label boundary is "evil-" not "."
    'http://localhost@evil.com', // userinfo trick: hostname is evil.com
    'http://127.0.0.1@evil.com',
  ])('refuses %s', (url) => {
    expect(() => assertLoopback('FRONTEND_URL', url)).toThrow(/loopback|production/i);
  });

  it('does not mistake a userinfo-only variation for the real loopback host', () => {
    // The dangerous direction above is refused; confirm the safe direction
    // still resolves to the actual connection target.
    expect(assertLoopback('FRONTEND_URL', 'http://evil.com@localhost')).toBe('localhost');
  });
});

describe('legacy guard — malformed URLs refused', () => {
  it.each([
    ['', /empty/i],
    ['   ', /empty/i],
    ['not a url', /valid URL/i],
    ['http://', /valid URL/i],
    ['ftp://localhost', /http or https/i],
    ['file:///etc/hosts', /http or https/i],
    ['localhost:5173', /http or https/i],
  ])('refuses %j', (url, pattern) => {
    expect(() => assertLoopback('API_URL', url)).toThrow(pattern);
  });
});

describe('resolveLegacyEnv', () => {
  it('defaults to loopback when nothing is set', () => {
    const env = resolveLegacyEnv({} as NodeJS.ProcessEnv);
    expect(env.baseUrl).toBe(DEFAULT_FRONTEND_URL);
    expect(env.apiUrl).toBe(DEFAULT_API_URL);
  });

  it('honours loopback overrides', () => {
    const env = resolveLegacyEnv({
      FRONTEND_URL: 'http://127.0.0.1:5173',
      API_URL: 'http://localhost:8080',
    } as NodeJS.ProcessEnv);
    expect(env.baseUrl).toBe('http://127.0.0.1:5173');
    expect(env.apiUrl).toBe('http://localhost:8080');
  });

  it('refuses a remote frontend override', () => {
    expect(() =>
      resolveLegacyEnv({ FRONTEND_URL: 'https://portal.example.com' } as NodeJS.ProcessEnv),
    ).toThrow(/loopback|production/i);
  });

  it('refuses a production API override', () => {
    expect(() =>
      resolveLegacyEnv({ API_URL: 'https://faculty-patent-portal-api.onrender.com' } as NodeJS.ProcessEnv),
    ).toThrow(/production/i);
  });

  it('refuses a remote E2E_API_URL even when the config URLs are local', () => {
    expect(() =>
      resolveLegacyEnv({ E2E_API_URL: 'https://api.example.com' } as NodeJS.ProcessEnv),
    ).toThrow(/loopback|production/i);
  });
});

describe('assertOptionalLoopback', () => {
  it('ignores an unset or empty value', () => {
    expect(() => assertOptionalLoopback('E2E_API_URL', undefined)).not.toThrow();
    expect(() => assertOptionalLoopback('E2E_API_URL', '')).not.toThrow();
  });

  it('allows loopback and refuses anything else', () => {
    expect(() => assertOptionalLoopback('E2E_API_URL', 'http://localhost:8000')).not.toThrow();
    expect(() => assertOptionalLoopback('E2E_API_URL', 'https://api.example.com')).toThrow(
      /loopback|production/i,
    );
  });
});

describe('apiBaseOf', () => {
  it('appends /api/v1 and normalizes trailing slashes', () => {
    expect(apiBaseOf('http://localhost:8000')).toBe('http://localhost:8000/api/v1');
    expect(apiBaseOf('http://localhost:8000/')).toBe('http://localhost:8000/api/v1');
    expect(apiBaseOf('http://localhost:8000////')).toBe('http://localhost:8000/api/v1');
  });
});

describe('guardedDevWebServer', () => {
  it('pins the frontend dev server and the browser API target to loopback', () => {
    const ws = guardedDevWebServer('http://localhost:5173', {
      apiUrl: 'http://localhost:8000',
      reuseExistingServer: true,
      timeout: 123,
    });
    expect(ws.command).toBe('npm run dev');
    expect(ws.url).toBe('http://localhost:5173');
    expect(ws.reuseExistingServer).toBe(true);
    expect(ws.timeout).toBe(123);
    expect(ws.env.VITE_API_BASE_URL).toBe('http://localhost:8000/api/v1');
  });

  it('never accepts a non-loopback webServer URL', () => {
    expect(() => guardedDevWebServer('https://portal.example.com', { apiUrl: 'http://localhost:8000' })).toThrow(
      /loopback|production/i,
    );
    expect(() => guardedDevWebServer('https://foo.pages.dev', { apiUrl: 'http://localhost:8000' })).toThrow(
      /production/i,
    );
  });

  it('never accepts a non-loopback API URL', () => {
    expect(() =>
      guardedDevWebServer('http://localhost:5173', { apiUrl: 'https://faculty-patent-portal-api.onrender.com' }),
    ).toThrow(/production/i);
    expect(() => guardedDevWebServer('http://localhost:5173', { apiUrl: 'https://api.example.com' })).toThrow(
      /loopback/i,
    );
  });

  it('pins VITE_API_BASE_URL to loopback even when the ambient env is remote (Vite process-env precedence)', () => {
    const previous = process.env.VITE_API_BASE_URL;
    process.env.VITE_API_BASE_URL = 'https://faculty-patent-portal-api.onrender.com/api/v1';
    try {
      const ws = guardedDevWebServer('http://127.0.0.1:5173', { apiUrl: 'http://127.0.0.1:8000' });
      expect(ws.env.VITE_API_BASE_URL).toBe('http://127.0.0.1:8000/api/v1');
    } finally {
      if (previous === undefined) delete process.env.VITE_API_BASE_URL;
      else process.env.VITE_API_BASE_URL = previous;
    }
  });
});

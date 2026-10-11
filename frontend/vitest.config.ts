import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Unit tests live in src/**/*.test.ts(x) and set their own jsdom environment
// via `// @vitest-environment jsdom`. The Playwright e2e specs under tests/
// must NOT be collected by vitest (they require a running browser/server).
// `threads` is used instead of the default `forks` pool, which intermittently
// timed out in this repo.
export default defineConfig({
  plugins: [react()],
  test: {
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    exclude: ['node_modules', 'dist', 'tests/**'],
    pool: 'threads',
  },
});

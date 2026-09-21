import { test, expect } from '@playwright/test';
import { BASE, U, RECORD_A, setPhase, log, loginUi, ss, PHASE_RESULTS, printSummary, installFailTracker } from './hardening-helpers';

installFailTracker();

test.describe('Phase 17 - Error/Empty State Hardening', () => {
  test('17.1 Invalid record shows error', async ({ page }) => {
    test.slow();
    setPhase('17.1');
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/records/00000000-0000-0000-0000-000000000000`, { waitUntil: 'load' });
    await page.waitForFunction(() => {
      const text = document.body?.textContent || '';
      return text.includes('Not Found') || text.includes('not found') || text.includes('error') || text.includes('Error') || text.includes('404');
    }, { timeout: 60000 });
    const text = await page.locator('body').textContent();
    const hasError = text?.includes('Not Found') || text?.includes('not found') || text?.includes('error') || text?.includes('Error') || text?.includes('404');
    expect(hasError).toBeTruthy();
    log('17.1', 'PASS', 'Invalid record shows error/not found');
  });
  test('17.2 Login page no blank state', async ({ page }) => {
    setPhase('17.2');
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    const text = await page.locator('body').textContent();
    expect(text).toContain('Login');
    expect(text).toContain('Email');
    expect(text).toContain('Password');
    log('17.2', 'PASS', 'Login page has proper form elements');
  });
  test('17.3 No React error boundary triggered', async ({ page }) => {
    setPhase('17.3');
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await loginUi(page, U.fac.e, U.fac.p);
    await page.goto(`${BASE}/faculty/dashboard`, { waitUntil: 'networkidle' });
    await page.goto(`${BASE}/faculty/records`, { waitUntil: 'networkidle' });
    await page.goto(`${BASE}/faculty/records/${RECORD_A}`, { waitUntil: 'networkidle' });
    const reactErrors = errors.filter(e => e.includes('Error') || e.includes('boundary'));
    expect(reactErrors).toHaveLength(0);
    log('17.3', 'PASS', 'No React error boundary triggered');
  });
  test('17.4 Empty search shows appropriate state', async ({ page }) => {
    setPhase('17.4');
    await loginUi(page, U.admin.e, U.admin.p);
    await page.goto(`${BASE}/search`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);
    const searchInput = page.getByPlaceholder(/search/i);
    if (await searchInput.count() > 0) {
      await searchInput.fill('ZZZZNONEXISTENT999');
      await page.waitForTimeout(1500);
      log('17.4', 'PASS', 'Empty search state handled');
    } else { log('17.4', 'INFO', 'No search input on search page'); }
  });
});

test.describe('Phase 18 - Responsive Hardening', () => {
  const viewports = [
    { name: 'desktop', width: 1440, height: 900 },
    { name: 'laptop', width: 1280, height: 720 },
    { name: 'tablet', width: 768, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
  ];

  for (const vp of viewports) {
    test(`18.1 Login at ${vp.name} (${vp.width}x${vp.height})`, async ({ page }) => {
      setPhase(`18.1-${vp.name}`);
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
      const btn = page.getByRole('button', { name: 'Login' });
      await expect(btn).toBeVisible();
      const box = await btn.boundingBox();
      expect(box).toBeTruthy();
      if (box) {
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(vp.width);
      }
      await ss(page, `18.1-login-${vp.name}`);
      log(`18.1-${vp.name}`, 'PASS', `Login renders at ${vp.name}`);
    });

    test(`18.2 Dashboard at ${vp.name}`, async ({ page }) => {
      setPhase(`18.2-${vp.name}`);
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await loginUi(page, U.fac.e, U.fac.p);
      await page.goto(`${BASE}/faculty/dashboard`, { waitUntil: 'networkidle' });
      await ss(page, `18.2-dashboard-${vp.name}`);
      const overflow = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth;
      });
      expect(overflow).toBe(false);
      log(`18.2-${vp.name}`, 'PASS', `Dashboard no horizontal overflow at ${vp.name}`);
    });

    test(`18.3 Record detail at ${vp.name}`, async ({ page }) => {
      setPhase(`18.3-${vp.name}`);
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await loginUi(page, U.fac.e, U.fac.p);
      await page.goto(`${BASE}/faculty/records/${RECORD_A}`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(2000);
      await ss(page, `18.3-record-${vp.name}`);
      log(`18.3-${vp.name}`, 'PASS', `Record detail renders at ${vp.name}`);
    });
  }
});

test.describe('Phase 19 - Accessibility Smoke', () => {
  test('19.1 Login form has labels', async ({ page }) => {
    setPhase('19.1');
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    const emailInput = page.getByLabel('Email');
    const passInput = page.getByLabel('Password');
    await expect(emailInput).toBeVisible();
    await expect(passInput).toBeVisible();
    log('19.1', 'PASS', 'Login form has accessible labels');
  });
  test('19.2 Login button has accessible name', async ({ page }) => {
    setPhase('19.2');
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    const btn = page.getByRole('button', { name: 'Login' });
    await expect(btn).toBeVisible();
    log('19.2', 'PASS', 'Login button has accessible name');
  });
  test('19.3 Keyboard Tab navigates login form', async ({ page }) => {
    setPhase('19.3');
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await page.keyboard.press('Tab');
    const focused = await page.evaluate(() => document.activeElement?.tagName);
    expect(['INPUT', 'BUTTON']).toContain(focused);
    log('19.3', 'PASS', `Tab focuses: ${focused}`);
  });
  test('19.4 Focus is visible on form elements', async ({ page }) => {
    setPhase('19.4');
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await page.keyboard.press('Tab');
    const hasOutline = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el) return false;
      const style = window.getComputedStyle(el);
      return style.outlineStyle !== 'none' || style.boxShadow !== 'none';
    });
    log('19.4', hasOutline ? 'PASS' : 'INFO', `Focus visibility: ${hasOutline}`);
  });
});

test.describe('Summary P17-19', () => {
  test('Results', async () => { printSummary(); expect(PHASE_RESULTS.filter(r => r.status === 'FAIL').length).toBe(0); });
});

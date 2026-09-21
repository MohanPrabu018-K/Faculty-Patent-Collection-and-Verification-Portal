import { test as setup } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { USERS } from './helpers';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const AUTH_DIR = path.resolve(__dirname, '.auth');

/** Login with retry for Neon connection pool exhaustion flake. */
async function loginWithRetry(
  page: import('@playwright/test').Page,
  email: string,
  password: string,
  waitForUrl: RegExp,
  label: string,
) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    if (attempt > 1) await page.waitForTimeout(5_000);
    await page.goto('/login');
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Password').fill(password);
    await page.getByRole('button', { name: 'Login' }).click();
    try {
      await page.waitForURL(waitForUrl, { timeout: 15_000 });
      return;
    } catch {
      if (attempt === 3) throw new Error(`${label}: login failed after 3 attempts (Neon pool flake)`);
    }
  }
}

setup('authenticate as faculty', async ({ page }) => {
  await loginWithRetry(page, USERS.facultyA.email, USERS.facultyA.password, /\/faculty\/dashboard/, 'faculty');
  await page.context().storageState({ path: `${AUTH_DIR}/faculty.json` });
});

setup('authenticate as admin', async ({ page }) => {
  await page.waitForTimeout(3_000);
  await loginWithRetry(page, USERS.admin.email, USERS.admin.password, /\/admin\/dashboard/, 'admin');
  await page.context().storageState({ path: `${AUTH_DIR}/admin.json` });
});

setup('authenticate as hod', async ({ page }) => {
  await page.waitForTimeout(3_000);
  await loginWithRetry(page, USERS.hod.email, USERS.hod.password, /\/hod\/dashboard/, 'hod');
  await page.context().storageState({ path: `${AUTH_DIR}/hod.json` });
});
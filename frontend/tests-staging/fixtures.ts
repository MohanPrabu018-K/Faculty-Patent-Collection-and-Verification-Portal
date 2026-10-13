/**
 * Loads the staging fixtures produced by `scripts/staging/provision_staging.py`.
 *
 * The file is gitignored and contains the resolved synthetic credentials and
 * deterministic record ids. If it is missing, provisioning has not been run.
 */
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

export type Account = {
  id: string;
  email: string;
  password: string;
  role: 'faculty' | 'hod_admin' | 'super_admin';
  faculty_id: string | null;
  department_id: string | null;
  is_active: boolean;
};

export type Fixtures = {
  generated_at: string;
  identity_source: string;
  departments: Record<string, string>;
  accounts: Record<string, Account>;
  records: Record<string, string>;
  associations: Record<string, string>;
  duplicates: Record<string, string>;
  conflicts: Record<string, string>;
};

const FIXTURES_PATH = path.join(path.dirname(fileURLToPath(import.meta.url)), '.staging-fixtures.json');

let cached: Fixtures | null = null;

export function loadFixtures(): Fixtures {
  if (cached) return cached;
  if (!fs.existsSync(FIXTURES_PATH)) {
    throw new Error(
      `[staging] fixtures not found at ${FIXTURES_PATH}. Run ` +
        '`python scripts/staging/provision_staging.py` against the disposable staging DB first.',
    );
  }
  cached = JSON.parse(fs.readFileSync(FIXTURES_PATH, 'utf8')) as Fixtures;
  return cached;
}

export function account(key: string): Account {
  const acc = loadFixtures().accounts[key];
  if (!acc) throw new Error(`[staging] no fixture account ${key}`);
  return acc;
}

export function record(key: string): string {
  const id = loadFixtures().records[key];
  if (!id) throw new Error(`[staging] no fixture record ${key}`);
  return id;
}

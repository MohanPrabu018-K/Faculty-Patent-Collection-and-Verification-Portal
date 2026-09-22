// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { authHeader } from './client';
import { downloadFile, formatDateOnly } from '../components/ui';

vi.mock('./client', () => ({
  authHeader: vi.fn(() => ({})),
}));

describe('formatDateOnly', () => {
  it('strips the time component from ISO datetimes', () => {
    expect(formatDateOnly('2024-10-22T00:00:00')).toBe('2024-10-22');
    expect(formatDateOnly('2024-10-22T00:00:00.000Z')).toBe('2024-10-22');
    expect(formatDateOnly('2024-10-22T15:30:45+05:30')).toBe('2024-10-22');
  });

  it('passes date-only values through unchanged', () => {
    expect(formatDateOnly('2024-10-22')).toBe('2024-10-22');
  });

  it('returns the placeholder for empty values', () => {
    expect(formatDateOnly(null)).toBe('—');
    expect(formatDateOnly(undefined)).toBe('—');
    expect(formatDateOnly('')).toBe('—');
  });

  it('returns non-date strings untouched', () => {
    expect(formatDateOnly('not a date')).toBe('not a date');
  });
});

describe('downloadFile', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.mocked(authHeader).mockReturnValue({ Authorization: 'Bearer jwt-1' });
    Object.defineProperty(window.URL, 'createObjectURL', { value: vi.fn(() => 'blob:fake'), configurable: true });
    Object.defineProperty(window.URL, 'revokeObjectURL', { value: vi.fn(), configurable: true });
  });

  it('sends credentials plus the Bearer fallback and triggers a download', async () => {
    const blob = new Blob(['a,b\n1,2'], { type: 'text/csv' });
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, blob: async () => blob }));
    vi.stubGlobal('fetch', fetchMock);
    await downloadFile('https://api/exports/x/download', 'ip-records-x.csv');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = ((fetchMock.mock.calls[0] as unknown[])?.[1] ?? {}) as RequestInit;
    expect(init.credentials).toBe('include');
    expect((init.headers as Record<string, string>)['Authorization']).toBe('Bearer jwt-1');
    expect(window.URL.createObjectURL).toHaveBeenCalledWith(blob);
  });

  it('throws a useful error carrying the backend message', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ error: 'AUTH', message: 'nope' }),
    }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(downloadFile('https://api/exports/x/download', 'x.csv')).rejects.toThrow(/Download failed \(401\)/);
  });
});

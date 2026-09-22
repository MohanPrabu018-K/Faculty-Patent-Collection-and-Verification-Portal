// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { AdminRecordsPage } from './AdminRecordsPage';

const { apiStubs, notifyMock } = vi.hoisted(() => ({
  apiStubs: {
    adminRecords: vi.fn(),
    adminRecordDetail: vi.fn(),
    adminUpdateRecord: vi.fn(),
    createExport: vi.fn(),
    exportDownloadUrl: (jobId: string) => `https://api.test/exports/${jobId}/download`,
  },
  notifyMock: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  ApiError: class extends Error {
    status: number;
    payload: string;
    constructor(status: number, payload: string) {
      super(payload || `Request failed: ${status}`);
      this.status = status;
      this.payload = payload;
    }
  },
  authHeader: () => ({}),
  api: apiStubs,
}));

vi.mock('../../stores/toast', () => ({
  useToast: () => ({ notify: notifyMock }),
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AdminRecordsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  apiStubs.adminRecords.mockReset();
  apiStubs.adminRecordDetail.mockReset();
  apiStubs.adminUpdateRecord.mockReset();
  apiStubs.createExport.mockReset();
  notifyMock.mockReset();
  apiStubs.adminRecords.mockResolvedValue({ records: [], total: 0, page: 1, per_page: 20 });
  Object.defineProperty(window.URL, 'createObjectURL', { value: vi.fn(() => 'blob:fake'), configurable: true });
  Object.defineProperty(window.URL, 'revokeObjectURL', { value: vi.fn(), configurable: true });
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, status: 200, blob: async () => new Blob(['a,b'], { type: 'text/csv' }) })),
  );
});

describe('AdminRecordsPage export flow', () => {
  it('selected format drives the export request and download', async () => {
    const user = userEvent.setup();
    apiStubs.createExport.mockResolvedValue({ job_id: 'job-1', format: 'excel', status: 'completed', created_at: 'x' });
    renderPage();
    await screen.findByText(/IP Records/);
    await user.selectOptions(screen.getByLabelText('Export format'), 'excel');
    await user.click(screen.getByRole('button', { name: 'Export EXCEL' }));
    await waitFor(() => expect(apiStubs.createExport).toHaveBeenCalledTimes(1));
    expect(apiStubs.createExport.mock.calls[0]?.[0]).toBe('excel');
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith('success', expect.stringContaining('EXCEL')));
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('/exports/job-1/download');
  });

  it('deselected fields are excluded from the export request', async () => {
    const user = userEvent.setup();
    apiStubs.createExport.mockResolvedValue({ job_id: 'job-2', format: 'csv', status: 'completed', created_at: 'x' });
    renderPage();
    await screen.findByText(/IP Records/);
    await user.click(screen.getByRole('button', { name: /Select Fields/ }));
    await user.click(screen.getByLabelText('grant date'));
    await user.click(screen.getByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(apiStubs.createExport).toHaveBeenCalledTimes(1));
    const [, , fields] = apiStubs.createExport.mock.calls[0] as [string, unknown, string[]];
    expect(fields).not.toContain('grant_date');
    expect(fields).toContain('title');
  });

  it('refuses to export with zero fields selected', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/IP Records/);
    await user.click(screen.getByRole('button', { name: /Select Fields/ }));
    await user.click(screen.getByRole('button', { name: 'Clear All' }));
    await user.click(screen.getByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith('error', expect.stringContaining('at least one field')));
    expect(apiStubs.createExport).not.toHaveBeenCalled();
  });

  it('surfaces backend export failures instead of failing silently', async () => {
    const user = userEvent.setup();
    apiStubs.createExport.mockRejectedValue(new Error('Export failed (500): boom'));
    renderPage();
    await screen.findByText(/IP Records/);
    await user.click(screen.getByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith('error', expect.stringContaining('boom')));
  });

  it('surfaces download failures instead of failing silently', async () => {
    const user = userEvent.setup();
    apiStubs.createExport.mockResolvedValue({ job_id: 'job-3', format: 'csv', status: 'completed', created_at: 'x' });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 403, text: async () => 'forbidden' })),
    );
    renderPage();
    await screen.findByText(/IP Records/);
    await user.click(screen.getByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith('error', expect.stringContaining('403')));
  });
});

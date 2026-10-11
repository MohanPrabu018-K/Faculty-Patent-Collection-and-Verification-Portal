// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { AdminGrantedPatentsPage } from './AdminGrantedPatentsPage';

const { apiStubs, notifyMock } = vi.hoisted(() => ({
  apiStubs: {
    adminRecords: vi.fn(),
    createExport: vi.fn(),
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
  api: apiStubs,
}));

vi.mock('../../stores/toast', () => ({
  useToast: () => ({ notify: notifyMock }),
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AdminGrantedPatentsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  apiStubs.adminRecords.mockReset();
  apiStubs.createExport.mockReset();
  notifyMock.mockReset();
  apiStubs.adminRecords.mockResolvedValue({ records: [], total: 0, page: 1, per_page: 20 });
});

describe('AdminGrantedPatentsPage verification filter', () => {
  it('GRANTED is sent as workflow_state, never as verification_status', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/Grant IP/);
    await user.selectOptions(screen.getByLabelText('Verification filter'), 'GRANTED');
    await waitFor(() => expect(apiStubs.adminRecords).toHaveBeenCalled());
    const lastParams = String(apiStubs.adminRecords.mock.calls.at(-1)?.[0] ?? '');
    expect(lastParams).toContain('workflow_state=GRANTED');
    expect(lastParams).not.toContain('verification_status=GRANTED');
  });

  it('VERIFIED keeps using verification_status', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/Grant IP/);
    await user.selectOptions(screen.getByLabelText('Verification filter'), 'VERIFIED');
    await waitFor(() => expect(apiStubs.adminRecords).toHaveBeenCalled());
    const lastParams = String(apiStubs.adminRecords.mock.calls.at(-1)?.[0] ?? '');
    expect(lastParams).toContain('verification_status=VERIFIED');
    expect(lastParams).not.toContain('workflow_state=');
  });
});

/**
 * The manual grant decision was removed from the admin surface. The page itself
 * (a historical record listing) is preserved: read-only rows, filters and
 * export remain, but no Grant Patent control exists.
 */
describe('AdminGrantedPatentsPage — grant action removed', () => {
  function verifiedRow() {
    return {
      id: 'rec-9',
      ip_type: 'PATENT',
      patent_number: 'IN999',
      title: 'Verified Widget',
      verification_status: 'VERIFIED',
      workflow_state: 'VERIFIED',
      processing_status: 'COMPLETED',
    };
  }

  it('renders no Grant Patent or Confirm Grant control for a verified record', async () => {
    apiStubs.adminRecords.mockResolvedValue({ records: [verifiedRow()], total: 1, page: 1, per_page: 20 });
    renderPage();
    await screen.findByText('Verified Widget');
    expect(screen.queryByRole('button', { name: /grant patent/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /confirm grant/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /granting/i })).toBeNull();
  });

  it('keeps the record readable via its Open link', async () => {
    apiStubs.adminRecords.mockResolvedValue({ records: [verifiedRow()], total: 1, page: 1, per_page: 20 });
    renderPage();
    await screen.findByText('Verified Widget');
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/faculty/records/rec-9');
  });

  it('keeps the historical GRANTED marker as a read-only badge', async () => {
    apiStubs.adminRecords.mockResolvedValue({
      records: [{ ...verifiedRow(), workflow_state: 'GRANTED' }], total: 1, page: 1, per_page: 20,
    });
    renderPage();
    await screen.findByText('Verified Widget');
    expect(screen.getAllByText(/Granted/).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /grant/i })).toBeNull();
  });
});

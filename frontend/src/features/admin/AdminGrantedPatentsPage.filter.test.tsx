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
    adminGrantPatent: vi.fn(),
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
  apiStubs.adminGrantPatent.mockReset();
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

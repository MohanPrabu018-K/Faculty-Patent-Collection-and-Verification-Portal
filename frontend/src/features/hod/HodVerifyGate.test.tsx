// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { HodDocumentsPage } from './HodPages';

const { apiStubs, notifyMock } = vi.hoisted(() => ({
  apiStubs: {
    hodDocuments: vi.fn(),
    institutionalStatus: vi.fn(),
    institutionalVerify: vi.fn(),
  },
  notifyMock: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  api: apiStubs,
}));

vi.mock('../../stores/toast', () => ({
  useToast: () => ({ notify: notifyMock }),
}));

function doc() {
  return {
    id: 'rec-1',
    title: 'Widget',
    patent_number: 'IN123',
    faculty_name: 'Uploader',
    verification_status: 'VERIFICATION_REQUIRED',
    processing_status: 'COMPLETED',
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <HodDocumentsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  apiStubs.hodDocuments.mockReset();
  apiStubs.institutionalStatus.mockReset();
  apiStubs.institutionalVerify.mockReset();
  notifyMock.mockReset();
  apiStubs.hodDocuments.mockResolvedValue({
    documents: [doc()], total: 1, page: 1, per_page: 20, total_pages: 1,
  });
});

describe('HOD Manual Verify gate (Bug 3)', () => {
  it('disables Confirm Verified while internal acceptance is pending', async () => {
    const user = userEvent.setup();
    apiStubs.institutionalStatus.mockResolvedValue({
      institutional: null, final_verification: null, pending_approvals: ['user-b'],
    });
    renderPage();

    await waitFor(() => expect(screen.getByText('Widget')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Manual Verify' }));

    await waitFor(() =>
      expect(screen.getByText(/blocked until required internal faculty acceptance/i)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Confirm Verified' })).toBeDisabled();
    // Non-approving outcomes stay available.
    expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled();
    expect(apiStubs.institutionalVerify).not.toHaveBeenCalled();
  });

  it('allows Confirm Verified once approvals are recorded', async () => {
    const user = userEvent.setup();
    apiStubs.institutionalStatus.mockResolvedValue({
      institutional: null, final_verification: null, pending_approvals: [],
    });
    apiStubs.institutionalVerify.mockResolvedValue({
      decision: 'verify', final_verification_status: 'VERIFIED',
    });
    renderPage();

    await waitFor(() => expect(screen.getByText('Widget')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Manual Verify' }));

    const confirm = await screen.findByRole('button', { name: 'Confirm Verified' });
    await waitFor(() => expect(confirm).toBeEnabled());
    expect(screen.queryByText(/blocked until required internal faculty acceptance/i)).toBeNull();
    await user.click(confirm);
    await waitFor(() => expect(apiStubs.institutionalVerify).toHaveBeenCalled());
  });
});

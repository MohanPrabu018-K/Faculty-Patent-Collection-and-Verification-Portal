// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { HodDocumentsPage } from './HodPages';

const { apiStubs, notifyMock } = vi.hoisted(() => ({
  apiStubs: {
    hodDocuments: vi.fn(),
  },
  notifyMock: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  api: apiStubs,
}));

vi.mock('../../stores/toast', () => ({
  useToast: () => ({ notify: notifyMock }),
}));

function doc(overrides: Record<string, unknown> = {}) {
  return {
    id: 'rec-1',
    title: 'Widget',
    patent_number: 'IN123',
    faculty_name: 'Uploader',
    verification_status: 'VERIFICATION_REQUIRED',
    processing_status: 'COMPLETED',
    grant_date: '2024-10-22',
    ...overrides,
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
  notifyMock.mockReset();
  apiStubs.hodDocuments.mockResolvedValue({
    documents: [doc()], total: 1, page: 1, per_page: 20, total_pages: 1,
  });
});

describe('HOD read-only documents (simplified workflow: no HOD approval actions)', () => {
  it('renders department documents with grant date and zero approval buttons', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Widget')).toBeInTheDocument());
    expect(screen.getByText('22/10/2024')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Manual Verify' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Confirm Verified' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull();
    expect(screen.queryByText(/HOD Manual Official Verification/)).toBeNull();
    expect(apiStubs.hodDocuments).toHaveBeenCalled();
  });

  it('offers only a View link per document', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Widget')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: 'View' })).toBeInTheDocument();
    expect(screen.queryByText(/Confirm Verified|Manual Verify/)).toBeNull();
  });
});

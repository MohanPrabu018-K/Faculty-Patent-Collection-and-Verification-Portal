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
  notifyMock.mockReset();
  apiStubs.hodDocuments.mockResolvedValue({
    documents: [doc()], total: 1, page: 1, per_page: 20, total_pages: 1,
  });
});

/**
 * Manual patent decisions (grant / verify / accept / reject) were removed from
 * the HOD dashboard. These tests lock that in: the documents table stays
 * readable, and no decision control is rendered even for a record that is
 * awaiting an official manual check.
 */
describe('HOD documents page — manual decision actions removed', () => {
  it('renders the department documents read-only with a View link', async () => {
    renderPage();
    expect(await screen.findByText('Widget')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View' })).toHaveAttribute('href', '/faculty/records/rec-1');
  });

  it('exposes no Manual Verify button', async () => {
    renderPage();
    await screen.findByText('Widget');
    expect(screen.queryByRole('button', { name: /manual verify/i })).toBeNull();
  });

  it('exposes no Verify / Accept / Reject / Grant controls', async () => {
    renderPage();
    await screen.findByText('Widget');
    for (const name of [/^verify/i, /^accept/i, /^reject/i, /grant/i, /confirm verified/i]) {
      expect(screen.queryByRole('button', { name })).toBeNull();
    }
  });

  it('offers no decision select or remarks/evidence decision form', async () => {
    renderPage();
    await screen.findByText('Widget');
    expect(screen.queryByLabelText('Decision')).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByText(/manual official verification/i)).toBeNull();
  });

  it('keeps read-only status and filter controls available', async () => {
    const user = (await import('@testing-library/user-event')).default.setup();
    renderPage();
    await screen.findByText('Widget');
    expect(screen.getByLabelText('Filter by status')).toBeInTheDocument();
    expect(screen.getByLabelText('Search documents')).toBeInTheDocument();
    await waitFor(() => expect(apiStubs.hodDocuments).toHaveBeenCalled());
    await user.selectOptions(screen.getByLabelText('Filter by status'), 'VERIFIED');
    await waitFor(() => expect(apiStubs.hodDocuments).toHaveBeenCalledTimes(2));
    expect(String(apiStubs.hodDocuments.mock.calls.at(-1)?.[0] ?? '')).toContain('status=VERIFIED');
  });
});
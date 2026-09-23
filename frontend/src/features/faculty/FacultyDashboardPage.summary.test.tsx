// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { MemoryRouter } from 'react-router-dom';
import { FacultyDashboardPage } from './FacultyDashboardPage';

const { apiStubs } = vi.hoisted(() => ({
  apiStubs: { facultyDashboard: vi.fn() },
}));

vi.mock('../../api/client', () => ({
  api: apiStubs,
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <FacultyDashboardPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  cleanup();
  apiStubs.facultyDashboard.mockReset();
});

describe('FacultyDashboardPage summary (Bug 11)', () => {
  it('does not render a Processing section; other summary cards remain', async () => {
    apiStubs.facultyDashboard.mockResolvedValue({
      records_summary: { total: 3, pending: 1, processing: 1, completed: 1, awaiting_review: 0, failed: 0 },
      recent_records: [],
    });
    renderPage();

    await waitFor(() => expect(screen.getByText('Total submissions')).toBeInTheDocument());
    expect(screen.getByText('Pending')).toBeInTheDocument();
    expect(screen.getByText('Awaiting review')).toBeInTheDocument();
    expect(screen.getByText('Verified')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    // The retired Processing UI must be gone even though the backend still
    // reports a processing count.
    expect(screen.queryByText('Processing')).toBeNull();
  });
});

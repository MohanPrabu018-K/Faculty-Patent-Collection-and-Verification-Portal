// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { RecordDetailPage } from './RecordDetailPage';

const { authState, apiStubs } = vi.hoisted(() => ({
  authState: { user: { id: 'uploader-1', role: 'faculty' } as { id: string; role: string } | null },
  apiStubs: {
    facultyRecordStatus: vi.fn(),
    associations: vi.fn(),
    institutionalStatus: vi.fn(),
    sendAssociation: vi.fn(),
    facultyRecordReview: vi.fn(),
  },
}));

vi.mock('../../api/client', () => ({
  api: {
    facultyRecordStatus: apiStubs.facultyRecordStatus,
    associations: apiStubs.associations,
    institutionalStatus: apiStubs.institutionalStatus,
    sendAssociation: apiStubs.sendAssociation,
    facultyRecordReview: apiStubs.facultyRecordReview,
    downloadRecordFile: vi.fn(),
  },
}));

vi.mock('../../stores/auth', () => ({
  useAuth: () => ({ user: authState.user, loading: false }),
}));

vi.mock('react-router-dom', async (original) => ({
  ...(await original<typeof import('react-router-dom')>()),
  useParams: () => ({ recordId: 'rec-1' }),
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RecordDetailPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  authState.user = { id: 'uploader-1', role: 'faculty' };
  apiStubs.facultyRecordStatus.mockReset();
  apiStubs.associations.mockReset();
  apiStubs.institutionalStatus.mockReset();
  apiStubs.sendAssociation.mockReset();
  apiStubs.facultyRecordReview.mockReset();
  apiStubs.institutionalStatus.mockResolvedValue({ institutional: null, final_verification: null });
  apiStubs.associations.mockResolvedValue({ associations: [], count: 0 });
});

afterEach(() => {
  cleanup();
});

describe('RecordDetailPage certificate dates (Bug 1)', () => {
  it('grant/filing/published dates render date-only, never raw timestamps', async () => {
    apiStubs.facultyRecordStatus.mockResolvedValue({
      id: 'rec-1',
      uploader_id: 'uploader-1',
      faculty_name: 'Uploader One',
      ip_type: 'PATENT',
      workflow_state: 'NEEDS_REVIEW',
      verification_status: 'VERIFICATION_REQUIRED',
      processing_status: 'COMPLETED',
      patent_number: 'IN123',
      title: 'Widget',
      filing_date: '2024-01-15T00:00:00+00:00',
      grant_date: '2024-10-22T00:00:00+00:00',
      published_date: '2024-10-22T00:00:00+00:00',
      contributors: [],
      jobs: [],
      files: [],
      field_provenance: [],
      evidence: {},
      qr_data: [],
    });
    renderPage();
    // Extracted Information shows calendar dates…
    await screen.findByText('Extracted Information');
    expect(screen.getAllByText('2024-10-22').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('2024-01-15')).toBeInTheDocument();
    // …and no timestamp leaks anywhere on the page.
    expect(screen.queryByText(/T00:00:00/)).toBeNull();
    expect(screen.queryByText(/\+00:00/)).toBeNull();
  });
});

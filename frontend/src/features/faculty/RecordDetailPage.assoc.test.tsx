// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { RecordDetailPage } from './RecordDetailPage';

const { authState, apiStubs, FakeApiError } = vi.hoisted(() => {
  class FakeApiError extends Error {
    status: number;
    payload: string;
    constructor(status: number, payload: string) {
      super(payload || `Request failed: ${status}`);
      this.status = status;
      this.payload = payload;
    }
  }
  return {
    FakeApiError,
    authState: { user: { id: 'uploader-1', role: 'faculty' } as { id: string; role: string } | null },
    apiStubs: {
      facultyRecordStatus: vi.fn(),
      associations: vi.fn(),
      institutionalStatus: vi.fn(),
      sendAssociation: vi.fn(),
      facultyRecordReview: vi.fn(),
    },
  };
});

vi.mock('../../api/client', () => ({
  ApiError: FakeApiError,
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

function contributor(name: string, overrides: Record<string, unknown> = {}) {
  return {
    id: `c-${name}`,
    name,
    contributor_type: 'INTERNAL_FACULTY',
    is_external: false,
    user_id: `user-${name}`,
    faculty_id: `FAC-${name}`,
    match_status: 'VERIFICATION_REQUIRED',
    ...overrides,
  };
}

function recordPayload(contributors: Record<string, unknown>[]) {
  return {
    id: 'rec-1',
    uploader_id: 'uploader-1',
    faculty_name: 'Uploader One',
    ip_type: 'PATENT',
    workflow_state: 'NEEDS_REVIEW',
    verification_status: 'VERIFICATION_REQUIRED',
    processing_status: 'COMPLETED',
    contributors,
    jobs: [],
    files: [],
    field_provenance: [],
    evidence: {},
    qr_data: [],
  };
}

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

describe('RecordDetailPage association send action', () => {
  it('uploader sees one Send button per unresolved internal contributor', async () => {
    apiStubs.facultyRecordStatus.mockResolvedValue(
      recordPayload([contributor('ashwin'), contributor('rajashekar'), contributor('monika', { contributor_type: 'EXTERNAL', is_external: true, user_id: null, faculty_id: null })]),
    );
    renderPage();
    const buttons = await screen.findAllByRole('button', { name: /send association request/i });
    expect(buttons).toHaveLength(2);
  });

  it('non-uploader and HOD do not see the send button', async () => {
    apiStubs.facultyRecordStatus.mockResolvedValue(recordPayload([contributor('ashwin')]));
    authState.user = { id: 'someone-else', role: 'faculty' };
    const { unmount } = renderPage();
    await screen.findByText('ashwin');
    expect(screen.queryByRole('button', { name: /send association request/i })).toBeNull();
    unmount();
    authState.user = { id: 'hod-1', role: 'hod_admin' };
    renderPage();
    await screen.findByText('ashwin');
    expect(screen.queryByRole('button', { name: /send association request/i })).toBeNull();
  });

  it('self contributor never shows the button', async () => {
    apiStubs.facultyRecordStatus.mockResolvedValue(
      recordPayload([contributor('myself', { name: 'Self Contributor', user_id: 'uploader-1', faculty_id: 'FAC-UP' })]),
    );
    renderPage();
    await screen.findByText('Self Contributor');
    expect(screen.queryByRole('button', { name: /send association request/i })).toBeNull();
  });

  it('successful send shows confirmation and pending state', async () => {
    apiStubs.facultyRecordStatus.mockResolvedValue(recordPayload([contributor('ashwin')]));
    apiStubs.sendAssociation.mockResolvedValue({ id: 'assoc-1', status: 'pending' });
    apiStubs.associations
      .mockResolvedValueOnce({ associations: [], count: 0 })
      .mockResolvedValue({ associations: [{ id: 'assoc-1', record_id: 'rec-1', recipient_id: 'user-ashwin', status: 'PENDING' }], count: 1 });
    const user = userEvent.setup();
    renderPage();
    const button = await screen.findByRole('button', { name: /send association request to/i });
    await user.click(button);
    expect(apiStubs.sendAssociation).toHaveBeenCalledWith('FAC-ashwin', expect.objectContaining({ record_id: 'rec-1' }));
    await screen.findByText(/association request sent to/i);
    await waitFor(() => expect(screen.getByText(/pending recipient decision/i)).toBeInTheDocument());
  });

  it('409 duplicate is adopted as sent, not an error', async () => {
    apiStubs.facultyRecordStatus.mockResolvedValue(recordPayload([contributor('ashwin')]));
    apiStubs.sendAssociation.mockRejectedValue(new FakeApiError(409, 'exists'));
    const user = userEvent.setup();
    renderPage();
    const button = await screen.findByRole('button', { name: /send association request to/i });
    await user.click(button);
    await screen.findByText(/already exists.*showing as sent/i);
    expect(screen.queryByText(/could not send/i)).toBeNull();
  });

  it('API failure shows a useful error', async () => {
    apiStubs.facultyRecordStatus.mockResolvedValue(recordPayload([contributor('ashwin')]));
    apiStubs.sendAssociation.mockRejectedValue(new FakeApiError(500, 'boom'));
    const user = userEvent.setup();
    renderPage();
    const button = await screen.findByRole('button', { name: /send association request to/i });
    await user.click(button);
    await screen.findByText(/could not send request/i);
  });

  it('grant date renders as a calendar date with no time component', async () => {
    apiStubs.facultyRecordStatus.mockResolvedValue({
      ...recordPayload([contributor('ashwin')]),
      grant_date: '2024-10-22T00:00:00',
    });
    renderPage();
    await screen.findByText('ashwin');
    expect(screen.getByText('2024-10-22')).toBeInTheDocument();
    expect(screen.queryByText(/T00:00:00/)).toBeNull();
  });
});

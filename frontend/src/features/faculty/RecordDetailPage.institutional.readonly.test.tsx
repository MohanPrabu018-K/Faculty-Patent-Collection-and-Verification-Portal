// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
    authState: { user: { id: 'hod-1', role: 'hod_admin', department_id: 'dept-1' } as Record<string, string> | null },
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

function recordPayload() {
  return {
    id: 'rec-1',
    uploader_id: 'uploader-1',
    faculty_name: 'Uploader One',
    ip_type: 'PATENT',
    workflow_state: 'VERIFICATION_REQUIRED',
    verification_status: 'VERIFICATION_REQUIRED',
    processing_status: 'COMPLETED',
    contributors: [],
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
  // A HOD viewing the record: previously this role got the decision form.
  authState.user = { id: 'hod-1', role: 'hod_admin', department_id: 'dept-1' };
  apiStubs.facultyRecordStatus.mockReset();
  apiStubs.associations.mockReset();
  apiStubs.institutionalStatus.mockReset();
  apiStubs.sendAssociation.mockReset();
  apiStubs.facultyRecordReview.mockReset();
  apiStubs.facultyRecordStatus.mockResolvedValue(recordPayload());
  apiStubs.associations.mockResolvedValue({ associations: [], count: 0 });
  apiStubs.institutionalStatus.mockResolvedValue({
    record_id: 'rec-1',
    official_verification_status: 'VERIFICATION_REQUIRED',
    verification_status: 'VERIFICATION_REQUIRED',
    workflow_state: 'VERIFICATION_REQUIRED',
    institutional: null,
    final_verification: null,
    history: [],
    pending_approvals: [],
  });
});

/**
 * Manual institutional decisions (verify / accept / reject) were removed from
 * the HOD and Super Admin surfaces. The record detail page keeps the
 * institutional card for READ-ONLY display, but must never offer a decision
 * control — including for a HOD on a record awaiting an official check.
 */
describe('RecordDetailPage institutional card is read-only', () => {
  it('renders the institutional card with automated verification state', async () => {
    renderPage();
    expect(await screen.findByText(/Institutional Verification \(HOD\)/i)).toBeInTheDocument();
    expect(await screen.findByText('Official verification (automated)')).toBeInTheDocument();
    expect(await screen.findByText('Final verification')).toBeInTheDocument();
  });

  it('offers a HOD no decision select, no confirmation checkbox and no submit button', async () => {
    renderPage();
    await screen.findByText(/Institutional Verification \(HOD\)/i);
    expect(screen.queryByLabelText('Decision')).toBeNull();
    expect(screen.queryByLabelText('Manual official verification confirmation')).toBeNull();
    expect(screen.queryByRole('button', { name: /submit institutional decision/i })).toBeNull();
  });

  it('offers no Verify / Reject / Accept patent-decision buttons to a HOD', async () => {
    renderPage();
    await screen.findByText(/Institutional Verification \(HOD\)/i);
    for (const name of [/^verify/i, /^reject/i, /^accept/i, /grant/i, /clarification/i]) {
      expect(screen.queryByRole('button', { name })).toBeNull();
    }
  });

  it('offers the same read-only view to a Super Admin', async () => {
    authState.user = { id: 'admin-1', role: 'super_admin' };
    renderPage();
    expect(await screen.findByText(/Institutional Verification \(HOD\)/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /submit institutional decision/i })).toBeNull();
  });

  it('shows historical HOD decisions without offering a new one', async () => {
    apiStubs.institutionalStatus.mockResolvedValue({
      record_id: 'rec-1',
      official_verification_status: 'VERIFICATION_REQUIRED',
      verification_status: 'VERIFICATION_REQUIRED',
      workflow_state: 'VERIFIED',
      institutional: {
        decision: 'verify',
        hod_faculty_id: 'FAC-HOD',
        remarks: 'checked IP India portal',
        evidence_ref: 'register p1',
        created_at: '2026-01-15T10:00:00',
      },
      final_verification: { status: 'VERIFIED', rationale: 'historical', missing_conditions: [] },
      history: [],
      pending_approvals: [],
    });
    renderPage();
    expect(await screen.findByText('INSTITUTIONALLY VERIFIED')).toBeInTheDocument();
    expect(screen.getByText('checked IP India portal')).toBeInTheDocument();
    expect(screen.getByText('register p1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /submit institutional decision/i })).toBeNull();
  });
});
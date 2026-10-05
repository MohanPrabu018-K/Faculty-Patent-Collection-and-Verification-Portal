// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { HodAuditPage } from './HodPages';

const { apiStubs, notifyMock } = vi.hoisted(() => ({
  apiStubs: { hodAudit: vi.fn() },
  notifyMock: vi.fn(),
}));

vi.mock('../../api/client', () => ({
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
        <HodAuditPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const RECORD_UUID = '47e615bd-6e80-4e8a-a6e6-6b25d11b54cd';
const ACTOR_UUID = 'aaaaaaaa-1111-2222-3333-444444444444';

beforeEach(() => {
  cleanup();
  apiStubs.hodAudit.mockReset();
  notifyMock.mockReset();
});

describe('HodAuditPage names (Bug 4)', () => {
  it('shows patent and actor names, never a raw UUID as the primary identifier', async () => {
    apiStubs.hodAudit.mockResolvedValue({
      audit_entries: [
        {
          id: 'audit-1',
          action: 'INSTITUTIONAL_VERIFICATION_VERIFY',
          actor_id: ACTOR_UUID,
          actor: { id: ACTOR_UUID, full_name: 'MV HOD', faculty_id: 'MVHOD' },
          entity_type: 'ip_record',
          entity_id: RECORD_UUID,
          entity: {
            type: 'ip_record',
            id: RECORD_UUID,
            display_name: 'Certificate 435272-001.pdf',
            title: 'ARTIFICIAL INTELLIGENCE BASED STRESS DETECTION DEVICE',
          },
          target_id: null,
          previous_value: null,
          new_value: null,
          created_at: '2026-09-23T06:00:00',
        },
      ],
      total: 1,
      page: 1,
      per_page: 25,
      total_pages: 1,
    });
    renderPage();

    await waitFor(() => expect(screen.getByText('MV HOD')).toBeInTheDocument());
    expect(screen.getByText('Certificate 435272-001.pdf')).toBeInTheDocument();
    // No raw UUID anywhere in the primary display.
    expect(screen.queryByText(RECORD_UUID)).toBeNull();
    expect(screen.queryByText(ACTOR_UUID)).toBeNull();
  });

  it('degrades gracefully when enrichment is absent', async () => {
    apiStubs.hodAudit.mockResolvedValue({
      audit_entries: [
        {
          id: 'audit-2',
          action: 'SOME_ACTION',
          actor_id: ACTOR_UUID,
          actor: null,
          entity_type: 'duplicate_case',
          entity_id: 'dddddddd-1111-2222-3333-444444444444',
          entity: null,
          target_id: null,
          previous_value: null,
          new_value: null,
          created_at: '2026-09-23T06:00:00',
        },
      ],
      total: 1,
      page: 1,
      per_page: 25,
      total_pages: 1,
    });
    renderPage();
    await waitFor(() => expect(screen.getByText(/SOME ACTION/)).toBeInTheDocument());
    // Unknown entity kinds fall back to type + short ref, never crash.
    expect(screen.getByText(/duplicate case/i)).toBeInTheDocument();
  });
});

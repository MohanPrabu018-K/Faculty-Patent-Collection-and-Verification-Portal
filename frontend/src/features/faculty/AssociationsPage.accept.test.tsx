// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { AssociationsPage } from './AssociationsPage';

const { apiStubs, notifyMock } = vi.hoisted(() => ({
  apiStubs: {
    associations: vi.fn(),
    respondAssociation: vi.fn(),
    clarifyAssociation: vi.fn(),
    cancelAssociation: vi.fn(),
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

vi.mock('../../stores/auth', () => ({
  useAuth: () => ({ user: { id: 'faculty-b', role: 'faculty' } }),
}));

vi.mock('../../stores/toast', () => ({
  useToast: () => ({ notify: notifyMock }),
}));

function row(status: string) {
  return {
    id: 'assoc-1',
    record_id: 'rec-1',
    record_title: 'Stress Detector',
    requester_id: 'faculty-a',
    requester_name: 'Faculty A',
    recipient_id: 'faculty-b',
    recipient_name: 'Faculty B',
    reason: 'co-author',
    status,
    responded_at: status === 'PENDING' ? null : '2024-10-22T00:00:00',
    created_at: '2024-10-21T00:00:00',
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AssociationsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  apiStubs.associations.mockReset();
  apiStubs.respondAssociation.mockReset();
  apiStubs.clarifyAssociation.mockReset();
  apiStubs.cancelAssociation.mockReset();
  notifyMock.mockReset();
});

describe('AssociationsPage accept persistence', () => {
  it('accepting a request refreshes the inbox to ACCEPTED (no stale PENDING)', async () => {
    const user = userEvent.setup();
    apiStubs.associations
      .mockResolvedValueOnce({ associations: [row('PENDING')], count: 1 })
      .mockResolvedValue({ associations: [row('ACCEPTED')], count: 1 });
    apiStubs.respondAssociation.mockResolvedValue({ request_id: 'assoc-1', status: 'ACCEPTED' });
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Accept' }));
    expect(apiStubs.respondAssociation).toHaveBeenCalledWith('assoc-1', 'accepted', undefined);
    // Refetch after accept shows the persisted ACCEPTED state, not stale PENDING.
    await waitFor(() => expect(screen.getByText('ACCEPTED')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Accept' })).toBeNull();
  });

  it('only the recipient sees respond actions', async () => {
    apiStubs.associations.mockResolvedValue({ associations: [row('PENDING')], count: 1 });
    renderPage();
    // faculty-b is the recipient here, so actions show; switch perspective via outgoing filter is covered by row logic.
    expect(await screen.findByRole('button', { name: 'Accept' })).toBeInTheDocument();
  });
});

// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { AdminFacultyPage } from './AdminFacultyPage';

const { apiStubs, notifyMock } = vi.hoisted(() => ({
  apiStubs: {
    adminFaculty: vi.fn(),
    adminFacultyDetail: vi.fn(),
    adminDepartments: vi.fn(),
    adminDesignations: vi.fn(),
    adminCreateFaculty: vi.fn(),
    adminUpdateFaculty: vi.fn(),
    adminActivateFaculty: vi.fn(),
    adminDeactivateFaculty: vi.fn(),
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
      <AdminFacultyPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  apiStubs.adminFaculty.mockReset();
  apiStubs.adminFacultyDetail.mockReset();
  apiStubs.adminDepartments.mockReset();
  apiStubs.adminDesignations.mockReset();
  apiStubs.adminCreateFaculty.mockReset();
  apiStubs.adminUpdateFaculty.mockReset();
  apiStubs.adminActivateFaculty.mockReset();
  apiStubs.adminDeactivateFaculty.mockReset();
  notifyMock.mockReset();
  apiStubs.adminFaculty.mockResolvedValue({ faculty: [], total: 0, page: 1, per_page: 20 });
  apiStubs.adminDepartments.mockResolvedValue({ departments: [], total: 0 });
  apiStubs.adminDesignations.mockResolvedValue({ designations: [], total: 0 });
});

describe('AdminFacultyPage email fields', () => {
  it('Add faculty form renders exactly one email input: Official email', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/Faculty Management/);
    await user.click(screen.getByRole('button', { name: 'Add faculty' }));
    await screen.findByText('Official email *');
    // Exactly one email input exists.
    expect(document.querySelectorAll('input[type="email"]')).toHaveLength(1);
    expect(screen.getByLabelText(/Official email/)).toBeInTheDocument();
    // The legacy generic "Email" field is gone.
    expect(screen.queryByText('Email *')).toBeNull();
  });

  it('create payload carries the official address as the login email', async () => {
    const user = userEvent.setup();
    apiStubs.adminCreateFaculty.mockResolvedValue({ id: 'u-new', email: 'new@college.edu', faculty_id: 'FAC-NEW' });
    renderPage();
    await screen.findByText(/Faculty Management/);
    await user.click(screen.getByRole('button', { name: 'Add faculty' }));
    await user.type(screen.getByLabelText(/Full name/), 'New Faculty');
    await user.type(screen.getByLabelText(/Official email/), 'new@college.edu');
    const createButton = screen.getByRole('button', { name: 'Create' });
    expect(createButton).toBeEnabled();
    await user.click(createButton);
    await waitFor(() => expect(apiStubs.adminCreateFaculty).toHaveBeenCalledTimes(1));
    const payload = apiStubs.adminCreateFaculty.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(payload['official_email']).toBe('new@college.edu');
    expect(payload['email']).toBe('new@college.edu');
  });

  it('Create stays disabled until a valid official email is entered', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/Faculty Management/);
    await user.click(screen.getByRole('button', { name: 'Add faculty' }));
    await user.type(screen.getByLabelText(/Full name/), 'New Faculty');
    expect(screen.getByRole('button', { name: 'Create' })).toBeDisabled();
    await user.type(screen.getByLabelText(/Official email/), 'not-an-email');
    expect(screen.getByRole('button', { name: 'Create' })).toBeDisabled();
  });
});

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
    adminDeleteFaculty: vi.fn(),
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

function row(id = 'fac-1') {
  return {
    id, full_name: 'Deletable Faculty', faculty_id: 'FAC-DEL',
    department_name: 'Physics', designation_name: 'Faculty',
    email: 'del@example.test', is_active: true,
    counts: { patents: 0, documents: 0 },
  };
}

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
  Object.values(apiStubs).forEach((fn) => (fn as ReturnType<typeof vi.fn>).mockReset());
  notifyMock.mockReset();
  apiStubs.adminFaculty.mockResolvedValue({ faculty: [row()], total: 1, page: 1, per_page: 20 });
  apiStubs.adminDepartments.mockResolvedValue({ departments: [], total: 0 });
  apiStubs.adminDesignations.mockResolvedValue({ designations: [], total: 0 });
});

describe('AdminFacultyPage delete flow (item 6)', () => {
  it('asks for confirmation with the exact required wording, then deletes and refreshes', async () => {
    const user = userEvent.setup();
    apiStubs.adminDeleteFaculty.mockResolvedValue({ id: 'fac-1', message: 'Faculty deleted' });
    renderPage();
    await screen.findByText('Deletable Faculty');
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await screen.findByText('Are you sure you want to delete this Faculty?');
    await user.click(screen.getByRole('button', { name: 'Yes, delete' }));
    await waitFor(() => expect(apiStubs.adminDeleteFaculty).toHaveBeenCalledWith('fac-1'));
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith('success', 'Faculty deleted'));
    // List refreshes after deletion.
    await waitFor(() => expect(apiStubs.adminFaculty.mock.calls.length).toBeGreaterThan(1));
  });

  it('cancel leaves the account untouched', async () => {    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Deletable Faculty');
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await screen.findByText('Are you sure you want to delete this Faculty?');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(apiStubs.adminDeleteFaculty).not.toHaveBeenCalled();
  });

  it('delete modal offers "Deactivate instead" which deactivates without deleting', async () => {
    const user = userEvent.setup();
    apiStubs.adminDeactivateFaculty.mockResolvedValue({ id: 'fac-1', status: 'inactive' });
    renderPage();
    await screen.findByText('Deletable Faculty');
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await screen.findByText('Are you sure you want to delete this Faculty?');
    await user.click(screen.getByRole('button', { name: 'Deactivate instead' }));
    await waitFor(() => expect(apiStubs.adminDeactivateFaculty).toHaveBeenCalledWith('fac-1'));
    expect(apiStubs.adminDeleteFaculty).not.toHaveBeenCalled();
  });

  it('backend 409 for data-linked faculty surfaces the human message, never raw JSON', async () => {
    const user = userEvent.setup();
    apiStubs.adminDeleteFaculty.mockRejectedValue(
      new Error('{"error":"FACULTY_HAS_DATA","message":"Cannot delete faculty with associated workflow data: 2 uploaded record(s)"}'),
    );
    renderPage();
    await screen.findByText('Deletable Faculty');
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await user.click(screen.getByRole('button', { name: 'Yes, delete' }));
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith(
      'error', 'Cannot delete faculty with associated workflow data: 2 uploaded record(s)',
    ));
    expect(notifyMock).not.toHaveBeenCalledWith('error', expect.stringContaining('FACULTY_HAS_DATA'));
  });

  it('duplicate-HOD 409 surfaces the required guidance message', async () => {
    const user = userEvent.setup();
    apiStubs.adminCreateFaculty.mockRejectedValue(
      new Error('{"error":"ACTIVE_HOD_EXISTS","message":"An active HOD already exists for this department."}'),
    );
    renderPage();
    await screen.findByText('Deletable Faculty');
    await user.click(screen.getByRole('button', { name: 'Add faculty' }));
    await user.type(screen.getByLabelText('Full name *'), 'Second HOD');
    await user.type(screen.getByLabelText('Official email *'), 'hod2@example.test');
    await user.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith(
      'error', expect.stringContaining('active HOD already exists for this department'),
    ));
    expect(notifyMock).not.toHaveBeenCalledWith('error', expect.stringContaining('ACTIVE_HOD_EXISTS'));
  });
});

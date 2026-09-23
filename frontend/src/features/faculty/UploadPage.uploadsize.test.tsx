// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { MemoryRouter } from 'react-router-dom';
import { UploadPage, friendlyUploadError, formatLimitMb } from './UploadPage';

const { apiStubs, notifyMock } = vi.hoisted(() => ({
  apiStubs: { csrf: vi.fn(), upload: vi.fn(), uploadConfig: vi.fn() },
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
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <UploadPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

function makePdf(name = 'cert.pdf') {
  return new File(['%PDF-1.4 fake content'], name, { type: 'application/pdf' });
}

// Raw backend 400 body for an oversized file (must never reach the user).
const rawTooLarge = (bytes: number, max: number) =>
  `{"error":"UPLOAD_ERROR","message":"File too large: ${bytes} bytes (max: ${max})","details":{}}`;

beforeEach(() => {
  cleanup();
  apiStubs.csrf.mockReset();
  apiStubs.upload.mockReset();
  apiStubs.uploadConfig.mockReset();
  notifyMock.mockReset();
  apiStubs.csrf.mockResolvedValue({ csrf_token: 't' });
});

describe('friendlyUploadError unit contract (Bug 12)', () => {
  it('maps oversized errors to the configured limit, never raw JSON', () => {
    expect(friendlyUploadError(rawTooLarge(7269488, 2097152), 2097152))
      .toBe('Maximum upload limit is 2 MB.');
    expect(friendlyUploadError(rawTooLarge(6000000, 5242880), 5242880))
      .toBe('Maximum upload limit is 5 MB.');
  });

  it('falls back to the backend max bytes when config is unavailable', () => {
    expect(friendlyUploadError(rawTooLarge(7269488, 2097152)))
      .toBe('Maximum upload limit is 2 MB.');
  });

  it('leaves non-size errors untouched', () => {
    expect(friendlyUploadError('Please choose a PDF or image file.', 2097152))
      .toBe('Please choose a PDF or image file.');
    expect(friendlyUploadError('Upload failed', 2097152)).toBe('Upload failed');
  });

  it('formats whole and fractional MB', () => {
    expect(formatLimitMb(2097152)).toBe('2 MB');
    expect(formatLimitMb(5242880)).toBe('5 MB');
    expect(formatLimitMb(1572864)).toBe('1.5 MB');
  });
});

describe('UploadPage oversized-file message (Bug 12)', () => {
  it('2 MB configured: oversized upload shows "Maximum upload limit is 2 MB."', async () => {
    const user = userEvent.setup();
    apiStubs.uploadConfig.mockResolvedValue({
      max_upload_bytes: 2097152, max_upload_mb: 2, allowed_extensions: ['.pdf'],
    });
    apiStubs.upload.mockRejectedValue(new Error(rawTooLarge(7269488, 2097152)));
    const { container } = renderPage();

    await user.upload(screen.getByLabelText('Choose file'), makePdf());
    await user.click(screen.getByRole('button', { name: 'Submit upload' }));

    await waitFor(() => {
      const alert = container.querySelector('.alert-error');
      expect(alert?.textContent).toBe('Maximum upload limit is 2 MB.');
    });
    expect(screen.queryByText(/7269488/)).toBeNull();
    expect(screen.queryByText(/UPLOAD_ERROR/)).toBeNull();
    expect(notifyMock).toHaveBeenCalledWith('error', 'Maximum upload limit is 2 MB.');
  });

  it('5 MB configured: message follows the backend config, not a hardcoded value', async () => {
    const user = userEvent.setup();
    apiStubs.uploadConfig.mockResolvedValue({
      max_upload_bytes: 5242880, max_upload_mb: 5, allowed_extensions: ['.pdf'],
    });
    apiStubs.upload.mockRejectedValue(new Error(rawTooLarge(6000000, 5242880)));
    const { container } = renderPage();

    await user.upload(screen.getByLabelText('Choose file'), makePdf());
    await user.click(screen.getByRole('button', { name: 'Submit upload' }));

    await waitFor(() => {
      const alert = container.querySelector('.alert-error');
      expect(alert?.textContent).toBe('Maximum upload limit is 5 MB.');
    });
    expect(screen.queryByText(/UPLOAD_ERROR/)).toBeNull();
  });

  it('successful upload shows no error', async () => {
    const user = userEvent.setup();
    apiStubs.uploadConfig.mockResolvedValue({
      max_upload_bytes: 2097152, max_upload_mb: 2, allowed_extensions: ['.pdf'],
    });
    apiStubs.upload.mockResolvedValue({ ip_record_id: 'REC123', status: 'PENDING', filename: 'cert.pdf' });
    const { container } = renderPage();

    await user.upload(screen.getByLabelText('Choose file'), makePdf());
    await user.click(screen.getByRole('button', { name: 'Submit upload' }));

    await waitFor(() => expect(screen.getByText(/Upload queued/)).toBeInTheDocument());
    expect(container.querySelector('.alert-error')).toBeNull();
    expect(screen.queryByText(/Record ID/)).toBeNull();
  });

  it('dropzone advertises the configured limit without hardcoding', async () => {
    apiStubs.uploadConfig.mockResolvedValue({
      max_upload_bytes: 5242880, max_upload_mb: 5, allowed_extensions: ['.pdf'],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText('Maximum upload limit is 5 MB.')).toBeInTheDocument());
  });
});

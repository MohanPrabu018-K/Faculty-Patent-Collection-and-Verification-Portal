// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { MemoryRouter } from 'react-router-dom';
import { UploadPage } from './UploadPage';

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

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const aborted = () => { const e = new Error('The operation was aborted.'); e.name = 'AbortError'; return e; };

beforeEach(() => {
  cleanup();
  apiStubs.csrf.mockReset();
  apiStubs.upload.mockReset();
  apiStubs.uploadConfig.mockReset();
  notifyMock.mockReset();
  apiStubs.uploadConfig.mockResolvedValue({
    max_upload_bytes: 20971520, max_upload_mb: 20, allowed_extensions: ['.pdf'],
  });
});

describe('UploadPage cancel behaviour (Bug 5: cancel must abort in-flight upload)', () => {
  it('cancelling during an upload aborts the request and never toasts stale state', async () => {
    const user = userEvent.setup();
    apiStubs.csrf.mockResolvedValue({ csrf_token: 't' });
    const d = deferred<Record<string, unknown>>();
    let capturedSignal: AbortSignal | undefined;
    apiStubs.upload.mockImplementation((_f: File, _c: string, s?: AbortSignal) => {
      capturedSignal = s;
      return d.promise;
    });
    renderPage();

    const input = screen.getByLabelText('Choose file');
    await user.upload(input, makePdf());
    await waitFor(() => expect(screen.getByText('cert.pdf')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Submit upload' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Uploading/ })).toBeDisabled());

    // Fail the in-flight upload exactly when the cancel aborts the signal.
    capturedSignal?.addEventListener('abort', () => d.reject(aborted()), { once: true });

    // Cancel while the upload is in flight.
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(capturedSignal?.aborted).toBe(true);
    // Loading is finished (button label reverts), file was cleared, and no
    // error/success banner or toast was produced by the abort.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Submit upload' })).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /Uploading/ })).toBeNull();
    expect(screen.queryByText(/Upload queued/)).toBeNull();
    expect(screen.queryByText(/Upload failed/)).toBeNull();
    // No triumph, no failure toast, no success banner, no stale preview.
    expect(notifyMock).not.toHaveBeenCalledWith('success', expect.any(String));
    expect(apiStubs.upload).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Upload queued/)).toBeNull();
  });

  it('successful upload still resolves to the record success banner', async () => {
    const user = userEvent.setup();
    apiStubs.csrf.mockResolvedValue({ csrf_token: 't' });
    apiStubs.upload.mockResolvedValue({ ip_record_id: 'REC123', status: 'PENDING' });
    renderPage();

    const input = screen.getByLabelText('Choose file');
    await user.upload(input, makePdf());
    await user.click(screen.getByRole('button', { name: 'Submit upload' }));
    await waitFor(() => expect(screen.getByText(/Upload queued/)).toBeInTheDocument());
    expect(apiStubs.upload).toHaveBeenCalledWith(
      expect.any(File),
      't',
      expect.any(AbortSignal),
    );
  });
});
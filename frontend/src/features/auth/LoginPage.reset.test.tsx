// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { LoginPage } from './LoginPage';

const { apiStubs, loginMock } = vi.hoisted(() => ({
  apiStubs: {
    csrf: vi.fn(),
    me: vi.fn(),
    forgotPassword: vi.fn(),
    resetPassword: vi.fn(),
  },
  loginMock: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  api: apiStubs,
}));

vi.mock('../../stores/auth', () => ({
  useAuth: () => ({ login: loginMock, user: null, loading: false }),
}));

function renderPage(initialEntries: string[] = ['/login']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <LoginPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  cleanup();
  apiStubs.csrf.mockReset();
  apiStubs.me.mockReset();
  apiStubs.forgotPassword.mockReset();
  apiStubs.resetPassword.mockReset();
  loginMock.mockReset();
});

describe('LoginPage forgot/reset views', () => {
  it('forgot view sends the request and shows the generic success message', async () => {
    const user = userEvent.setup();
    apiStubs.forgotPassword.mockResolvedValue({ message: 'If the email is registered, a password reset link has been sent.' });
    renderPage();
    await user.click(screen.getByRole('button', { name: /Forgot password/ }));
    await user.type(screen.getByLabelText('Email'), 'faculty@example.edu');
    await user.click(screen.getByRole('button', { name: /Send reset token/ }));
    await waitFor(() => expect(apiStubs.forgotPassword).toHaveBeenCalledWith('faculty@example.edu'));
    await screen.findByText(/If the email is registered/);
  });

  it('emailed /reset?token= link opens the reset view with the token prefilled', async () => {
    const user = userEvent.setup();
    apiStubs.resetPassword.mockResolvedValue({ message: 'Password has been reset successfully.' });
    renderPage(['/reset?token=abc123']);
    // Reset view renders immediately (no need to click through).
    expect(await screen.findByText('Reset Password')).toBeInTheDocument();
    expect(screen.getByLabelText('Reset token')).toHaveValue('abc123');
    await user.type(screen.getByLabelText('New password'), 'brand-new-9');
    await user.click(screen.getByRole('button', { name: /Reset password/ }));
    await waitFor(() => expect(apiStubs.resetPassword).toHaveBeenCalledWith('abc123', 'brand-new-9'));
    await screen.findByText(/Password has been reset successfully/);
  });

  it('reset submit without a token shows a validation error, not an API call', async () => {
    const user = userEvent.setup();
    renderPage(['/login']);
    await user.click(screen.getByRole('button', { name: /Forgot password/ }));
    await user.click(screen.getByRole('button', { name: /Enter reset token/ }));
    expect(await screen.findByText('Reset Password')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^Reset password$/ }));
    await screen.findByText(/Reset token is required/);
    expect(apiStubs.resetPassword).not.toHaveBeenCalled();
  });
});

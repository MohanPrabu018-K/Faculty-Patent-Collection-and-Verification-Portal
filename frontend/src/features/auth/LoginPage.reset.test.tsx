// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { LoginPage, MISSING_RESET_LINK_MESSAGE, friendlyAuthError } from './LoginPage';

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
  vi.useRealTimers();
});

describe('LoginPage forgot/reset views (Bug 3: reset-link flow)', () => {
  it('forgot view sends the request and shows the generic privacy message', async () => {
    const user = userEvent.setup();
    apiStubs.forgotPassword.mockResolvedValue({ message: 'If the email is registered, a password reset link has been sent.' });
    renderPage();
    await user.click(screen.getByRole('button', { name: /Forgot password/ }));
    await user.type(screen.getByLabelText('Email'), 'faculty@example.edu');
    await user.click(screen.getByRole('button', { name: /Send reset link/ }));
    await waitFor(() => expect(apiStubs.forgotPassword).toHaveBeenCalledWith('faculty@example.edu'));
    await screen.findByText(/If the email is registered/);
  });

  it('forgot view shows the honest unavailable message on 503, never fake success', async () => {
    const user = userEvent.setup();
    apiStubs.forgotPassword.mockRejectedValue(
      new Error('{"error":"EMAIL_UNAVAILABLE","message":"Password reset email is currently unavailable. Please contact the administrator."}'),
    );
    renderPage();
    await user.click(screen.getByRole('button', { name: /Forgot password/ }));
    await user.type(screen.getByLabelText('Email'), 'faculty@example.edu');
    await user.click(screen.getByRole('button', { name: /Send reset link/ }));
    await screen.findByText(/Password reset email is currently unavailable/);
    expect(screen.queryByText(/If the email is registered/)).toBeNull();
    expect(screen.queryByText(/EMAIL_UNAVAILABLE/)).toBeNull();
    expect(screen.queryByText(/"error"/)).toBeNull();
  });

  it('forgot view exposes no manual token entry', async () => {    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: /Forgot password/ }));
    expect(screen.queryByText(/Already have a reset token/)).toBeNull();
    expect(screen.queryByRole('button', { name: /Enter reset token/ })).toBeNull();
    expect(screen.queryByLabelText('Reset token')).toBeNull();
  });

  it('emailed /reset?token= link opens reset with passwords only (token auto-consumed)', async () => {
    const user = userEvent.setup();
    apiStubs.resetPassword.mockResolvedValue({ message: 'Password has been reset successfully.' });
    renderPage(['/reset?token=abc123']);
    expect(await screen.findByText('Reset Password')).toBeInTheDocument();
    // No manual token field exists; the URL token is consumed automatically.
    expect(screen.queryByLabelText('Reset token')).toBeNull();
    expect(screen.queryByText(/Paste your reset token/)).toBeNull();
    await user.type(screen.getByLabelText('New password'), 'brand-new-9');
    await user.type(screen.getByLabelText('Confirm password'), 'brand-new-9');
    await user.click(screen.getByRole('button', { name: /^Reset password$/ }));
    await waitFor(() => expect(apiStubs.resetPassword).toHaveBeenCalledWith('abc123', 'brand-new-9'));
    await screen.findByText(/Password has been reset successfully/);
  });

  it('mismatched passwords are rejected client-side with no API call', async () => {
    const user = userEvent.setup();
    renderPage(['/reset?token=abc123']);
    await user.type(screen.getByLabelText('New password'), 'brand-new-9');
    await user.type(screen.getByLabelText('Confirm password'), 'different-9');
    await user.click(screen.getByRole('button', { name: /^Reset password$/ }));
    await screen.findByText(/Passwords do not match/);
    expect(apiStubs.resetPassword).not.toHaveBeenCalled();
  });

  it('/reset without a token shows the missing-link message and never calls the API', async () => {
    const user = userEvent.setup();
    renderPage(['/reset']);
    await screen.findByText(MISSING_RESET_LINK_MESSAGE);
    expect(screen.queryByLabelText('New password')).toBeNull();
    expect(screen.queryByLabelText('Reset token')).toBeNull();
    expect(apiStubs.resetPassword).not.toHaveBeenCalled();
    // The recovery path leads back to the forgot view.
    await user.click(screen.getByRole('button', { name: /Request a new password reset email/ }));
    expect(await screen.findByText('Forgot Password')).toBeInTheDocument();
  });

  it('invalid/expired token shows a friendly message, never raw backend JSON', async () => {
    const user = userEvent.setup();
    apiStubs.resetPassword.mockRejectedValue(
      new Error('{"error":"AUTHENTICATION_ERROR","message":"Invalid or expired reset token","details":{}}'),
    );
    renderPage(['/reset?token=stale-token']);
    await user.type(screen.getByLabelText('New password'), 'brand-new-9');
    await user.type(screen.getByLabelText('Confirm password'), 'brand-new-9');
    await user.click(screen.getByRole('button', { name: /^Reset password$/ }));
    await screen.findByText(/reset link is invalid or has expired/);
    expect(screen.queryByText(/AUTHENTICATION_ERROR/)).toBeNull();
    expect(screen.queryByText(/"error"/)).toBeNull();
  });
});

describe('friendlyAuthError (Bug 3: no raw JSON in UI)', () => {
  it('maps invalid/expired tokens to the friendly message', () => {
    expect(friendlyAuthError(
      new Error('{"error":"AUTHENTICATION_ERROR","message":"Invalid or expired reset token","details":{}}'),
      'fallback',
    )).toMatch(/reset link is invalid or has expired/);
  });

  it('maps rate limiting to a friendly message', () => {
    expect(friendlyAuthError(
      new Error('{"error":"RATE_LIMIT_EXCEEDED","message":"Too many attempts. Please try again later."}'),
      'fallback',
    )).toMatch(/Too many attempts/);
  });

  it('maps SMTP-unavailable to the honest message, never raw JSON or fake success', () => {
    expect(friendlyAuthError(
      new Error('{"error":"EMAIL_UNAVAILABLE","message":"Password reset email is currently unavailable. Please contact the administrator.","details":{}}'),
      'fallback',
    )).toBe('Password reset email is currently unavailable. Please contact the administrator.');
  });

  it('maps FastAPI validation envelopes to friendly text, never raw JSON', () => {
    expect(friendlyAuthError(
      new Error('{"detail":[{"type":"value_error","loc":["body","email"],"msg":"value is not a valid email address","input":"x","ctx":{"reason":"bad"}}]}'),
      'fallback',
    )).toBe('Please enter a valid email address.');
  });

  it('passes through safe backend messages and never emits raw JSON', () => {
    expect(friendlyAuthError(
      new Error('{"error":"VALIDATION_ERROR","message":"Password must be at least 6 characters"}'),
      'fallback',
    )).toBe('Password must be at least 6 characters');
    expect(friendlyAuthError(new Error('plain failure'), 'fallback')).toBe('plain failure');
    expect(friendlyAuthError(new Error('{"error": broken'), 'fallback')).toBe('fallback');
    expect(friendlyAuthError(null, 'fallback')).toBe('fallback');
  });
});

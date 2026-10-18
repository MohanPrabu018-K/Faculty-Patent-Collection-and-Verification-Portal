import { useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { useAuth } from '../../stores/auth';
import { api } from '../../api/client';

const schema = z.object({ email: z.string().email(), password: z.string().min(6) });
type FormData = z.infer<typeof schema>;

const forgotSchema = z.object({ email: z.string().email() });
type ForgotFormData = z.infer<typeof forgotSchema>;

const resetSchema = z.object({
  newPassword: z.string().min(6, 'Password must be at least 6 characters'),
  confirmPassword: z.string().min(6, 'Password must be at least 6 characters'),
}).refine((d) => d.newPassword === d.confirmPassword, {
  message: 'Passwords do not match',
  path: ['confirmPassword'],
});
type ResetFormData = z.infer<typeof resetSchema>;

/** Role home pages. Invalid credentials / expired sessions always land here first. */
function homeForRole(role: string): string {
  if (role === 'super_admin') return '/admin/dashboard';
  if (role === 'hod_admin') return '/hod/dashboard';
  return '/faculty/dashboard';
}

/** Only honor a saved `from` location when the role is allowed to see it. */
function allowedFrom(from: unknown, role: string): string | null {
  if (typeof from !== 'string' || !from.startsWith('/')) return null;
  if (from.startsWith('/admin/')) return role === 'super_admin' ? from : null;
  if (from.startsWith('/hod/')) return role === 'hod_admin' || role === 'super_admin' ? from : null;
  return from;
}

type View = 'login' | 'forgot' | 'reset';

/** Shown when /reset is opened without a token: no manual token entry exists. */
export const MISSING_RESET_LINK_MESSAGE =
  'Your password reset link is missing or invalid. Please request a new password reset email.';

/**
 * Map login/forgot/reset failures to clean user-facing text.
 *
 * The backend keeps structured JSON internally ({error, message} or FastAPI
 * {detail: [...]} validation envelopes); the UI must never render those
 * wrappers. Known error codes map to friendly copy; any other
 * backend-provided human message passes through (backend messages never
 * contain tokens); otherwise a generic message is shown.
 */
export function friendlyAuthError(err: unknown, fallback: string): string {
  if (err instanceof Error) {
    const text = err.message.trim();
    if (text.startsWith('{') || text.startsWith('[')) {
      try {
        const parsed: unknown = JSON.parse(text);
        const message =
          parsed && typeof parsed === 'object' && typeof (parsed as Record<string, unknown>).message === 'string'
            ? String((parsed as Record<string, unknown>).message)
            : null;
        if (message) {
          if (/invalid or expired reset token/i.test(message)) {
            return 'Your reset link is invalid or has expired. Please request a new password reset email.';
          }
          if (/too many attempts/i.test(message)) {
            return 'Too many attempts. Please try again later.';
          }
          // BUG 1: SMTP-unavailable must surface honestly, never as raw JSON
          // and never as a fake "email sent" success.
          if (/password reset email is currently unavailable|email_unavailable/i.test(message)) {
            return 'Password reset email is currently unavailable. Please contact the administrator.';
          }
          return message;
        }
        // FastAPI request-validation envelope: {detail: [{msg, ...}, ...]}.
        const detail = parsed && typeof parsed === 'object'
          ? (parsed as Record<string, unknown>).detail
          : null;
        if (Array.isArray(detail) && detail.length > 0) {
          const first = detail[0] as Record<string, unknown>;
          const msg = typeof first?.msg === 'string' ? first.msg : null;
          if (msg && /valid email address/i.test(msg)) {
            return 'Please enter a valid email address.';
          }
          if (msg) return `Invalid request: ${msg}`;
        }
      } catch {
        /* fall through to generic */
      }
      return fallback;
    }
    return err.message;
  }
  return fallback;
}

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  // Deep link from the emailed reset URL (/reset?token=…): the token is
  // consumed automatically from the URL. There is intentionally NO manual
  // token entry anywhere in the normal flow.
  const initialToken = (searchParams.get('token') ?? '').trim();
  const [error, setError] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  // /reset always opens the reset view (with or without a token) so a bare
  // /reset visit shows the missing-link message instead of the login form.
  const [view, setView] = useState<View>(initialToken || location.pathname === '/reset' ? 'reset' : 'login');
  const [forgotSuccess, setForgotSuccess] = useState('');
  const [resetSuccess, setResetSuccess] = useState('');
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<FormData>({ resolver: zodResolver(schema) });
  const { register: registerForgot, handleSubmit: handleForgotSubmit, formState: { errors: forgotErrors, isSubmitting: forgotSubmitting } } = useForm<ForgotFormData>({ resolver: zodResolver(forgotSchema) });
  const { register: registerReset, handleSubmit: handleResetSubmit, formState: { errors: resetErrors, isSubmitting: resetSubmitting } } = useForm<ResetFormData>({ resolver: zodResolver(resetSchema) });

  const onSubmit = async (data: FormData) => {
    setError('');
    try {
      const csrf = await api.csrf();
      // login() already returns the fresh session (one /auth/me inside);
      // do not fetch it a second time just for role routing.
      const me = await login(data.email, data.password, csrf.csrf_token);
      const from = (location.state as { from?: unknown } | null)?.from;
      navigate(allowedFrom(from, me.role) ?? homeForRole(me.role), { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Login failed';
      if (message.includes('Invalid email or password')) {
        // The backend deliberately returns this identical message whether the
        // account is unknown or the password was wrong, so that login cannot
        // be used to enumerate registered accounts (D-005).
        setError('Invalid email or password. Please try again.');
      } else if (message.includes('Account is deactivated')) {
        setError('Your account has been deactivated. Please contact an administrator.');
      } else {
        // Never render raw backend JSON (e.g. FastAPI validation envelopes).
        setError(friendlyAuthError(err, 'Login failed. Please try again.'));
      }
    }
  };

  const onForgotSubmit = async (data: ForgotFormData) => {
    setError('');
    setForgotSuccess('');
    try {
      const result = await api.forgotPassword(data.email);
      setForgotSuccess(result.message || 'If the email is registered, a password reset link has been sent.');
    } catch (err) {
      setError(friendlyAuthError(err, 'Failed to send reset link. Please try again later.'));
    }
  };

  const onResetSubmit = async (data: ResetFormData) => {
    setError('');
    setResetSuccess('');
    if (!initialToken) {
      setError(MISSING_RESET_LINK_MESSAGE);
      return;
    }
    try {
      const result = await api.resetPassword(initialToken, data.newPassword);
      setResetSuccess(result.message || 'Password reset successfully. You can now log in.');
      setTimeout(() => setView('login'), 3000);
    } catch (err) {
      setError(friendlyAuthError(err, 'Password reset failed. Please request a new password reset email.'));
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="eyebrow">Faculty Profile Portal</div>
        {view === 'login' && (
          <>
            <h1>Faculty login</h1>
            <p>Sign in to manage patent and design registrations.</p>
            <form onSubmit={handleSubmit(onSubmit)} className="stack">
              <div className="field">
                <label htmlFor="email">Email</label>
                <input {...register('email')} id="email" type="email" placeholder="faculty@example.edu" aria-label="Email" />
                {errors.email && <small className="field-error">{errors.email.message}</small>}
              </div>
              <div className="field">
                <label htmlFor="password">Password</label>
                <div className="password-row">
                  <input {...register('password')} id="password" type={showPassword ? 'text' : 'password'} placeholder="Enter password" aria-label="Password" />
                  <button type="button" className="btn btn-secondary" onClick={() => setShowPassword(v => !v)}>
                    {showPassword ? 'Hide' : 'Show'}
                  </button>
                </div>
                {errors.password && <small className="field-error">{errors.password.message}</small>}
              </div>
              {error && <div className="alert alert-error" role="alert" aria-live="polite">{error}</div>}
              <button className="btn btn-primary" disabled={isSubmitting}>{isSubmitting ? 'Signing in...' : 'Login'}</button>
              <button type="button" className="btn btn-ghost" onClick={() => { setView('forgot'); setError(''); }}>
                Forgot password?
              </button>
            </form>
          </>
        )}
        {view === 'forgot' && (
          <>
            <h1>Forgot Password</h1>
            <p>Enter your registered email address and we&apos;ll send you a password reset link.</p>
            <form onSubmit={handleForgotSubmit(onForgotSubmit)} className="stack">
              <div className="field">
                <label htmlFor="forgot-email">Email</label>
                <input {...registerForgot('email')} id="forgot-email" type="email" placeholder="faculty@example.edu" aria-label="Email" />
                {forgotErrors.email && <small className="field-error">{forgotErrors.email.message}</small>}
              </div>
              {error && <div className="alert alert-error" role="alert" aria-live="polite">{error}</div>}
              {forgotSuccess && <div className="alert alert-success" role="status">{forgotSuccess}</div>}
              <button className="btn btn-primary" disabled={forgotSubmitting}>{forgotSubmitting ? 'Sending...' : 'Send reset link'}</button>
              <button type="button" className="btn btn-ghost" onClick={() => { setView('login'); setError(''); setForgotSuccess(''); }}>
                Back to login
              </button>
            </form>
          </>
        )}
        {view === 'reset' && (
          <>
            <h1>Reset Password</h1>
            {initialToken ? (
              <>
                <p>Enter a new password for your account.</p>
                <form onSubmit={handleResetSubmit(onResetSubmit)} className="stack">
                  <div className="field">
                    <label htmlFor="new-password">New Password</label>
                    <input {...registerReset('newPassword')} id="new-password" type={showPassword ? 'text' : 'password'} placeholder="Enter new password" aria-label="New password" />
                    {resetErrors.newPassword && <small className="field-error">{resetErrors.newPassword.message}</small>}
                  </div>
                  <div className="field">
                    <label htmlFor="confirm-password">Confirm Password</label>
                    <input {...registerReset('confirmPassword')} id="confirm-password" type={showPassword ? 'text' : 'password'} placeholder="Confirm new password" aria-label="Confirm password" />
                    {resetErrors.confirmPassword && <small className="field-error">{resetErrors.confirmPassword.message}</small>}
                  </div>
                  {error && <div className="alert alert-error" role="alert" aria-live="polite">{error}</div>}
                  {resetSuccess && <div className="alert alert-success" role="status">{resetSuccess}</div>}
                  <button className="btn btn-primary" disabled={resetSubmitting}>{resetSubmitting ? 'Resetting...' : 'Reset password'}</button>
                  <button type="button" className="btn btn-ghost" onClick={() => { setView('login'); setError(''); setResetSuccess(''); }}>
                    Back to login
                  </button>
                </form>
              </>
            ) : (
              <>
                <div className="alert alert-error" role="alert">{MISSING_RESET_LINK_MESSAGE}</div>
                <div className="stack" style={{ marginTop: 12 }}>
                  <button type="button" className="btn btn-primary" onClick={() => { setView('forgot'); setError(''); }}>
                    Request a new password reset email
                  </button>
                  <button type="button" className="btn btn-ghost" onClick={() => { setView('login'); setError(''); }}>
                    Back to login
                  </button>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

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

const resetSchema = z.object({ token: z.string().min(1, 'Reset token is required'), newPassword: z.string().min(6, 'Password must be at least 6 characters') });
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

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  // Deep link from the emailed reset URL (/reset?token=…): open the reset
  // view directly with the token prefilled. Manual paste flow unchanged.
  const initialToken = (searchParams.get('token') ?? '').trim();
  const [error, setError] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [view, setView] = useState<View>(initialToken ? 'reset' : 'login');
  const [forgotSuccess, setForgotSuccess] = useState('');
  const [resetSuccess, setResetSuccess] = useState('');
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<FormData>({ resolver: zodResolver(schema) });
  const { register: registerForgot, handleSubmit: handleForgotSubmit, formState: { errors: forgotErrors, isSubmitting: forgotSubmitting } } = useForm<ForgotFormData>({ resolver: zodResolver(forgotSchema) });
  const { register: registerReset, handleSubmit: handleResetSubmit, formState: { errors: resetErrors, isSubmitting: resetSubmitting } } = useForm<ResetFormData>({ resolver: zodResolver(resetSchema), defaultValues: { token: initialToken } });

  const onSubmit = async (data: FormData) => {
    setError('');
    try {
      const csrf = await api.csrf();
      await login(data.email, data.password, csrf.csrf_token);
      const me = await api.me();
      const from = (location.state as { from?: unknown } | null)?.from;
      navigate(allowedFrom(from, me.role) ?? homeForRole(me.role), { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Login failed';
      if (message.includes('Incorrect password')) {
        setError('Incorrect password. Please try again.');
      } else if (message.includes('Invalid email or password')) {
        setError('Invalid email or password. Please try again.');
      } else if (message.includes('Account is deactivated')) {
        setError('Your account has been deactivated. Please contact an administrator.');
      } else {
        setError(message);
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
      setError(err instanceof Error ? err.message : 'Failed to send reset link');
    }
  };

  const onResetSubmit = async (data: ResetFormData) => {
    setError('');
    setResetSuccess('');
    try {
      const result = await api.resetPassword(data.token, data.newPassword);
      setResetSuccess(result.message || 'Password reset successfully. You can now log in.');
      setTimeout(() => setView('login'), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Password reset failed');
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
            <p>Enter your registered email address and we'll send you a reset token.</p>
            <form onSubmit={handleForgotSubmit(onForgotSubmit)} className="stack">
              <div className="field">
                <label htmlFor="forgot-email">Email</label>
                <input {...registerForgot('email')} id="forgot-email" type="email" placeholder="faculty@example.edu" aria-label="Email" />
                {forgotErrors.email && <small className="field-error">{forgotErrors.email.message}</small>}
              </div>
              {error && <div className="alert alert-error" role="alert" aria-live="polite">{error}</div>}
              {forgotSuccess && <div className="alert alert-success" role="status">{forgotSuccess}</div>}
              <button className="btn btn-primary" disabled={forgotSubmitting}>{forgotSubmitting ? 'Sending...' : 'Send reset token'}</button>
              <button type="button" className="btn btn-ghost" onClick={() => { setView('login'); setError(''); setForgotSuccess(''); }}>
                Back to login
              </button>
            </form>
            <div style={{ marginTop: 16, borderTop: '1px solid var(--border, #e2e8f0)', paddingTop: 16 }}>
              <p style={{ fontSize: 13, color: 'var(--muted, #64748b)' }}>Already have a reset token?</p>
              <button type="button" className="btn btn-secondary" style={{ marginTop: 8 }} onClick={() => { setView('reset'); setError(''); setForgotSuccess(''); }}>
                Enter reset token
              </button>
            </div>
          </>
        )}
        {view === 'reset' && (
          <>
            <h1>Reset Password</h1>
            <p>Enter the reset token from your email and your new password.</p>
            <form onSubmit={handleResetSubmit(onResetSubmit)} className="stack">
              <div className="field">
                <label htmlFor="reset-token">Reset Token</label>
                <input {...registerReset('token')} id="reset-token" type="text" placeholder="Paste your reset token" aria-label="Reset token" />
                {resetErrors.token && <small className="field-error">{resetErrors.token.message}</small>}
              </div>
              <div className="field">
                <label htmlFor="new-password">New Password</label>
                <input {...registerReset('newPassword')} id="new-password" type={showPassword ? 'text' : 'password'} placeholder="Enter new password" aria-label="New password" />
                {resetErrors.newPassword && <small className="field-error">{resetErrors.newPassword.message}</small>}
              </div>
              {error && <div className="alert alert-error" role="alert" aria-live="polite">{error}</div>}
              {resetSuccess && <div className="alert alert-success" role="status">{resetSuccess}</div>}
              <button className="btn btn-primary" disabled={resetSubmitting}>{resetSubmitting ? 'Resetting...' : 'Reset password'}</button>
              <button type="button" className="btn btn-ghost" onClick={() => { setView('login'); setError(''); setResetSuccess(''); }}>
                Back to login
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}

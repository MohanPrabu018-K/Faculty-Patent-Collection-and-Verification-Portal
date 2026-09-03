import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { useAuth } from '../../stores/auth';
import { api } from '../../api/client';

const schema = z.object({ email: z.string().email(), password: z.string().min(6) });
type FormData = z.infer<typeof schema>;

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<FormData>({ resolver: zodResolver(schema) });

  const onSubmit = async (data: FormData) => {
    setError('');
    try {
      const csrf = await api.csrf();
      await login(data.email, data.password, csrf.csrf_token);
      navigate('/faculty/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="eyebrow">Faculty Profile Portal</div>
        <h1>Faculty login</h1>
        <p>Sign in to manage patent and design registrations.</p>
        <form onSubmit={handleSubmit(onSubmit)} className="stack">
          <label className="field">
            <span>Email</span>
            <input {...register('email')} type="email" placeholder="faculty@example.edu" />
            {errors.email && <small className="field-error">{errors.email.message}</small>}
          </label>
          <label className="field">
            <span>Password</span>
            <div className="password-row">
              <input {...register('password')} type={showPassword ? 'text' : 'password'} placeholder="Enter password" />
              <button type="button" className="btn btn-secondary" onClick={() => setShowPassword(v => !v)}>
                {showPassword ? 'Hide' : 'Show'}
              </button>
            </div>
            {errors.password && <small className="field-error">{errors.password.message}</small>}
          </label>
          {error && <div className="alert alert-error">{error}</div>}
          <button className="btn btn-primary" disabled={isSubmitting}>{isSubmitting ? 'Signing in...' : 'Login'}</button>
        </form>
      </div>
    </div>
  );
}

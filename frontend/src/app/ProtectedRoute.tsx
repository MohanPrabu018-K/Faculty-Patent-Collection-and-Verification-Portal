import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../stores/auth';

export function ProtectedRoute() {
  const { loading, user } = useAuth();
  const location = useLocation();
  if (loading) return <div className="page-center">Loading session...</div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

export function RequireRole({ roles }: { roles: string[] }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (!roles.includes(user.role)) return <Navigate to="/faculty/dashboard" replace />;
  return <Outlet />;
}

import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { ApiError, api, type AuthUser } from '../api/client';

export type User = AuthUser;

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string, csrfToken?: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  reload: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = async () => {
    try {
      setUser(await api.me());
    } catch (error) {
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) setUser(null);
      else setUser(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void reload(); }, []);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    loading,
    reload,
    login: async (email, password, csrfToken) => {
      await api.login(email, password, csrfToken);
      setUser(await api.me());
    },
    logout: async () => {
      await api.logout();
      setUser(null);
    },
    refresh: async () => {
      await api.refresh();
      setUser(await api.me());
    },
  }), [user, loading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

import { createContext, useContext, useMemo, useState } from 'react';

type Toast = { id: string; kind: 'success' | 'error' | 'info'; message: string };
type ToastContextValue = { notify: (kind: Toast['kind'], message: string) => void };

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const notify = (kind: Toast['kind'], message: string) => {
    const id = crypto.randomUUID();
    setToasts((current) => [...current, { id, kind, message }]);
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 3500);
  };

  const value = useMemo(() => ({ notify }), []);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" aria-live="polite" aria-atomic="true">
        {toasts.map((toast) => <div key={toast.id} className={`toast toast-${toast.kind}`}>{toast.message}</div>)}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}

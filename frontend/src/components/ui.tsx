import clsx from 'clsx';
import { useEffect } from 'react';

export function SectionCard({ title, subtitle, actions, children }: { title: string; subtitle?: string; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="section-card">
      <div className="section-head section-head-row">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {actions && <div className="section-head-actions">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

export function StatCard({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="stat-card">
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small className="muted">{hint}</small>}
    </div>
  );
}

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const v = value || 'UNKNOWN';
  return <span className={clsx('badge', `badge-${v.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`)}>{v.replace(/_/g, ' ')}</span>;
}

export function LoadingBlock({ label = 'Loading…' }: { label?: string }) {
  return <div className="loading-inline"><span className="spinner" /><span>{label}</span></div>;
}

export function ErrorBlock({ error }: { error: unknown }) {
  let message = 'Something went wrong.';
  if (error && typeof error === 'object' && 'message' in error) message = String((error as { message: unknown }).message);
  else if (typeof error === 'string') message = error;
  if (/\b403\b/.test(message) || /AUTHORIZATION/i.test(message)) message = 'You are not authorized to view this.';
  else if (/\b401\b/.test(message) && /credential/i.test(message)) message = 'Your session has expired. Please sign in again.';
  else if (/\b400\b/.test(message) && /credential/i.test(message)) message = 'Your session has expired. Please sign in again.';
  else if (/\b0\b/.test(message) || /network|connect/i.test(message)) message = 'Unable to connect to the server. Please check your network connection and try again.';
  return <div className="alert alert-error">{message}</div>;
}

export function EmptyState({ message, action }: { message: string; action?: React.ReactNode }) {
  return (
    <div className="empty-cell empty-state">
      <p>{message}</p>
      {action}
    </div>
  );
}

export function Toolbar({ children }: { children: React.ReactNode }) {
  return <div className="toolbar toolbar-flex">{children}</div>;
}

export function TableWrap({ children }: { children: React.ReactNode }) {
  return <div className="table-wrap">{children}</div>;
}

export function Pagination({ page, totalPages, onChange, disabled }: { page: number; totalPages: number; onChange: (p: number) => void; disabled?: boolean }) {
  if (!totalPages || totalPages <= 1) return null;
  return (
    <div className="pagination">
      <button className="btn btn-secondary" disabled={disabled || page <= 1} onClick={() => onChange(page - 1)}>Previous</button>
      <span className="muted">Page {page} of {totalPages}</span>
      <button className="btn btn-secondary" disabled={disabled || page >= totalPages} onClick={() => onChange(page + 1)}>Next</button>
    </div>
  );
}

export function Modal({ title, onClose, children, footer }: { title: string; onClose: () => void; children: React.ReactNode; footer?: React.ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label={title} onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="btn btn-secondary btn-icon" aria-label="Close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function formatDateTime(value: unknown): string {
  if (!value) return '—';
  const d = new Date(String(value));
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export function formatDate(value: unknown): string {
  if (!value) return '—';
  const d = new Date(String(value));
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: '2-digit' });
}

export function display(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.length ? value.map(display).join(', ') : '—';
  // Objects are never a good production display — callers should pass primitives.
  if (typeof value === 'object') return '—';
  return String(value);
}

/** A deliberately-collapsed technical view for structured evidence/detail blobs. */
export function TechnicalDetails({ label = 'Technical details', data }: { label?: string; data: unknown }) {
  if (data === null || data === undefined) return null;
  return (
    <details className="tech-details">
      <summary>{label}</summary>
      <pre className="inline-json">{typeof data === 'string' ? data : JSON.stringify(data, null, 2)}</pre>
    </details>
  );
}

export function MiniBars({ data, formatLabel }: { data: Record<string, number>; formatLabel?: (k: string) => string }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return <EmptyState message="No data." />;
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return (
    <div className="stack">
      {entries.map(([k, v]) => (
        <div key={k} className="bar-row">
          <span className="bar-label">{formatLabel ? formatLabel(k) : k.replace(/_/g, ' ')}</span>
          <span className="bar-track"><span className="bar-fill" style={{ width: `${(v / max) * 100}%` }} /></span>
          <strong className="bar-value">{v}</strong>
        </div>
      ))}
    </div>
  );
}

/** Fetch a URL with credentials and hand the browser a downloadable blob. */
export async function downloadFile(url: string, filename: string): Promise<void> {
  const res = await fetch(url, { credentials: 'include' });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 2000);
}

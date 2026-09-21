import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { SectionCard, StatusBadge, ErrorBlock, display } from '../../components/ui';
import { useAuth } from '../../stores/auth';
import { useToast } from '../../stores/toast';

function KV({ label, value }: { label: string; value: unknown }) {
  return <div className="detail-field"><span>{label}</span><strong>{display(value)}</strong></div>;
}

function StatusRow({ label, status, note }: { label: string; status: string; note?: string }) {
  return (
    <div className="pill-row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
      <div>
        <strong>{label}</strong>
        {note ? <div className="muted" style={{ fontSize: 13 }}>{note}</div> : null}
      </div>
      <StatusBadge value={status} />
    </div>
  );
}

export function AdminSettingsPage() {
  const { user } = useAuth();
  const { notify } = useToast();
  const client = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ['admin-settings'], queryFn: api.adminSettings });
  const [mb, setMb] = useState('');
  const save = useMutation({
    mutationFn: (v: number) => api.adminUpdateSettings({ max_upload_mb: v }),
    onSuccess: async (r) => { notify('success', `Upload limit set to ${r.max_upload_mb} MB`); setMb(''); await client.invalidateQueries({ queryKey: ['admin-settings'] }); },
    onError: (e) => notify('error', e instanceof Error ? e.message : 'Save failed'),
  });

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading settings…</span></div>;
  if (error) return <ErrorBlock error={error} />;
  if (!data) return <ErrorBlock error="Settings unavailable" />;

  const app = data.application as Record<string, unknown>;
  const ocr = data.ocr as Record<string, unknown>;
  const ext = (ocr.external_fallback ?? {}) as Record<string, unknown>;
  const qr = data.qr as Record<string, unknown>;
  const ver = data.verification as Record<string, unknown>;
  const ipIndia = (ver.ip_india ?? {}) as Record<string, unknown>;
  const up = data.uploads as Record<string, unknown>;
  const sess = data.session as Record<string, unknown>;

  return (
    <div className="stack-lg">
      <SectionCard title="Account" subtitle="Your signed-in identity. Managed by the institution — not editable here.">
        <div className="kv-grid">
          <KV label="Name" value={user?.full_name} />
          <KV label="Email" value={user?.email} />
          <KV label="Role" value={(user?.role || '').replace('_', ' ')} />
          <KV label="Faculty ID" value={user?.faculty_id} />
          <KV label="Department" value={user?.department_id} />
          <KV label="Account status" value="active" />
        </div>
        <p className="muted" style={{ marginTop: 12 }}>
          To change account details or reset a password, use <strong>Faculty → Edit</strong> (for other users) or contact the system administrator.
        </p>
      </SectionCard>

      <SectionCard title="System" subtitle="Read-only. These values come from server configuration.">
        <div className="kv-grid">
          <KV label="Application" value={app.name} />
          <KV label="Environment" value={app.environment} />
          <KV label="Debug mode" value={String(app.debug)} />
          <KV label="API prefix" value={app.api_prefix} />
        </div>
      </SectionCard>

      <SectionCard title="Document processing" subtitle="OCR and QR capability status.">
        <div className="stack">
          <StatusRow label="Embedded PDF text extraction" status={String(ocr.embedded_text_extraction || 'ENABLED')} note="PyMuPDF — used first for text-layer PDFs" />
          <StatusRow label={`Local OCR (${display(ocr.engine)})`} status={String(ocr.status)} note={`Tesseract ${ocr.tesseract_available ? 'installed' : 'NOT installed'} · languages: ${display(ocr.tesseract_langs)}`} />
          <StatusRow label={`External OCR fallback (${display(ext.provider)})`} status={String(ext.status)} note={String(ext.note || 'Optional — not required for normal operation.')} />
          <StatusRow label="QR decoding" status={String(qr.status)} note={`Engines: ${Array.isArray(qr.engines) ? (qr.engines as string[]).join(', ') : display(qr.engines)}`} />
        </div>
      </SectionCard>

      <SectionCard title="Verification" subtitle="Official IP verification configuration.">
        <div className="stack">
          <StatusRow label="IP India (InPASS) automated lookup" status={String(ipIndia.status)} note={String(ipIndia.note || '')} />
          <StatusRow label="Manual verification fallback" status={String(ver.manual_fallback || 'ENABLED')} note="Records that cannot be auto-verified are flagged for manual review." />
          <KV label="Default country" value={ver.default_country} />
        </div>
      </SectionCard>

      <SectionCard title="Uploads" subtitle="Super Admin can change max upload size (enforced by backend on new uploads). Secrets are never editable here.">
        <div className="kv-grid">
          <KV label="Allowed file types" value={up.allowed_extensions} />
          <KV label="Max upload size" value={`${display(up.max_upload_mb)} MB`} />
          <KV label="Max PDF pages" value={up.max_pdf_pages} />
          <KV label="Storage backend" value={up.storage_backend} />
        </div>
        <div className="toolbar" style={{ marginTop: 12 }}>
          <input className="toolbar-input" type="number" min={Number(up.max_upload_mb_min ?? 1)} max={Number(up.max_upload_mb_max ?? 100)} step="1" placeholder={`New limit in MB (${display(up.max_upload_mb_min)}–${display(up.max_upload_mb_max)})`} value={mb} onChange={(e) => setMb(e.target.value)} aria-label="Max upload MB" style={{ width: 260 }} />
          <button className="btn btn-primary btn-sm" disabled={save.isPending || !mb} onClick={() => save.mutate(Number(mb))}>{save.isPending ? 'Saving…' : 'Save upload limit'}</button>
        </div>
        <p className="muted">Allowed {display(up.max_upload_mb_min)}–{display(up.max_upload_mb_max)} MB. Every change is audit-logged (SETTINGS_UPDATED).</p>
      </SectionCard>

      <SectionCard title="Session & security" subtitle="Read-only session policy.">
        <div className="kv-grid">
          <KV label="JWT algorithm" value={sess.jwt_algorithm} />
          <KV label="Access token lifetime" value={`${display(sess.access_token_minutes)} min`} />
          <KV label="Secure cookies" value={String(sess.cookie_secure)} />
          <KV label="Cookie SameSite" value={sess.cookie_samesite} />
        </div>
      </SectionCard>
    </div>
  );
}

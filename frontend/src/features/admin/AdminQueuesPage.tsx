import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import {
  SectionCard, StatusBadge, ErrorBlock, EmptyState,
  TableWrap, Modal, TechnicalDetails, formatDateTime, display,
} from '../../components/ui';
import { useToast } from '../../stores/toast';

type Row = Record<string, unknown>;

function parseEvidence(raw: unknown): Record<string, unknown> | null {
  if (!raw) return null;
  if (typeof raw === 'object') return raw as Record<string, unknown>;
  if (typeof raw === 'string') {
    try { return JSON.parse(raw) as Record<string, unknown>; } catch { return null; }
  }
  return null;
}

/* ------------------------------- Verification ------------------------------ */

function VerificationCard({ row, onRetry, busy }: { row: Row; onRetry: () => void; busy: boolean }) {
  const ev = parseEvidence(row.result) ?? {};
  const first = (v: unknown) => (Array.isArray(v) ? (v[0] as Record<string, unknown>)?.value : v);
  const fields = [
    ['OCR engine', ev.ocr_engine],
    ['Text layer', ev.ocr_has_text_layer === true ? 'Yes' : ev.ocr_has_text_layer === false ? 'No' : undefined],
    ['Confidence', ev.confidence != null ? `${Math.round(Number(ev.confidence) * 100)}%` : undefined],
    ['Patent no.', first(ev.patent_number)],
    ['Design no.', first(ev.design_number)],
    ['Applicant', first(ev.applicant)],
    ['Source', ev.verification_source ?? row.source],
  ].filter(([, v]) => v != null && v !== '');

  return (
    <div className="assoc-card">
      <div className="assoc-card-head">
        <div>
          <strong><Link className="link" to={`/faculty/records/${row.ip_record_id}`}>{String(row.ip_record_id || row.id).slice(0, 12)}…</Link></strong>
          <div className="muted">Attempt #{display(row.attempt_number)} · {formatDateTime(row.created_at)}</div>
        </div>
        <StatusBadge value={String(row.status || 'UNVERIFIED')} />
      </div>
      <div className="assoc-meta">
        {fields.map(([k, v]) => <div key={String(k)} className="detail-field"><span>{String(k)}</span><strong>{display(v)}</strong></div>)}
      </div>
      {typeof ev.ocr_text === 'string' && ev.ocr_text ? (
        <div className="detail-field"><span>Extracted text (excerpt)</span><span className="muted" style={{ whiteSpace: 'pre-wrap' }}>{ev.ocr_text.slice(0, 240)}{ev.ocr_text.length > 240 ? '…' : ''}</span></div>
      ) : null}
      <TechnicalDetails data={row.result} />
      <div className="btn-row">
        <button className="btn btn-sm btn-primary" disabled={busy} onClick={onRetry}>Retry verification</button>
      </div>
    </div>
  );
}

/* --------------------------------- Page ---------------------------------- */

export function AdminQueuesPage() {
  const client = useQueryClient();
  const { notify } = useToast();
  const [confirm, setConfirm] = useState<{ kind: 'verify' | 'duplicate' | 'conflict'; row: Row } | null>(null);

  const verifications = useQuery({ queryKey: ['admin-verifications'], queryFn: () => api.adminVerifications('?per_page=25') });
  const duplicates = useQuery({ queryKey: ['admin-duplicates'], queryFn: () => api.adminDuplicates('?per_page=50') });
  const conflicts = useQuery({ queryKey: ['admin-conflicts'], queryFn: () => api.adminConflicts('?per_page=50') });
  const associations = useQuery({ queryKey: ['admin-associations'], queryFn: () => api.adminAssociations('?per_page=50') });

  const invalidate = (key: string) => client.invalidateQueries({ queryKey: [key] });

  const retryVerification = useMutation({
    mutationFn: (attemptId: string) => api.adminResolveVerification(attemptId),
    onSuccess: async () => { notify('success', 'Verification retry submitted'); setConfirm(null); await invalidate('admin-verifications'); },
    onError: (e) => notify('error', e instanceof Error ? e.message : 'Failed to retry verification'),
  });
  const resolveDuplicate = useMutation({
    mutationFn: ({ caseId, keepRecordId }: { caseId: string; keepRecordId: string }) => api.adminResolveDuplicate(caseId, keepRecordId),
    onSuccess: async () => { notify('success', 'Duplicate case resolved'); setConfirm(null); await invalidate('admin-duplicates'); },
    onError: (e) => notify('error', e instanceof Error ? e.message : 'Failed to resolve duplicate'),
  });
  const resolveConflict = useMutation({
    mutationFn: (conflictId: string) => api.adminResolveConflict(conflictId, 'resolved'),
    onSuccess: async () => { notify('success', 'Conflict resolved'); setConfirm(null); await invalidate('admin-conflicts'); },
    onError: (e) => notify('error', e instanceof Error ? e.message : 'Failed to resolve conflict'),
  });
  const busy = retryVerification.isPending || resolveDuplicate.isPending || resolveConflict.isPending;

  const vRows = verifications.data?.verifications ?? [];
  const dRows = duplicates.data?.duplicates ?? [];
  const cRows = conflicts.data?.conflicts ?? [];
  const aRows = associations.data?.associations ?? [];

  return (
    <div className="stack-lg">
      <SectionCard title="Verification Review" subtitle={`${verifications.data?.total ?? 0} attempts`}>
        {verifications.isLoading && !verifications.data ? <div className="loading-inline"><span className="spinner" /><span>Loading verifications…</span></div> : verifications.error ? <ErrorBlock error={verifications.error} />
          : vRows.length === 0 ? <EmptyState message="No verification attempts to review." />
            : <div className="stack">{vRows.map((r) => <VerificationCard key={String(r.id)} row={r} busy={busy} onRetry={() => setConfirm({ kind: 'verify', row: r })} />)}</div>}
      </SectionCard>

      <SectionCard title="Duplicate Review" subtitle={`${duplicates.data?.total ?? 0} cases`}>
        {duplicates.isLoading && !duplicates.data ? <div className="loading-inline"><span className="spinner" /><span>Loading duplicates…</span></div> : duplicates.error ? <ErrorBlock error={duplicates.error} />
          : dRows.length === 0 ? <EmptyState message="No duplicate cases." />
            : <TableWrap><table className="data-table">
              <thead><tr><th>Record</th><th>Duplicate of</th><th>Confidence</th><th>Method</th><th>Detected by</th><th>Status</th><th></th></tr></thead>
              <tbody>{dRows.map((r) => (
                <tr key={String(r.id)}>
                  <td><Link className="link" to={`/faculty/records/${r.ip_record_id_1}`}>{String(r.ip_record_id_1).slice(0, 8)}…</Link></td>
                  <td><Link className="link" to={`/faculty/records/${r.ip_record_id_2}`}>{String(r.ip_record_id_2).slice(0, 8)}…</Link></td>
                  <td>{r.confidence != null ? `${Math.round(Number(r.confidence) * 100)}%` : '—'}</td>
                  <td>{display(r.detection_method)}</td>
                  <td>{display(r.detected_by)}</td>
                  <td><StatusBadge value={String(r.status || 'OPEN')} /></td>
                  <td>{String(r.status) === 'OPEN'
                    ? <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => setConfirm({ kind: 'duplicate', row: r })}>Resolve</button>
                    : <span className="muted">{display(r.resolution_notes) || '—'}</span>}</td>
                </tr>
              ))}</tbody>
            </table></TableWrap>}
      </SectionCard>

      <SectionCard title="Conflict Review" subtitle={`${conflicts.data?.total ?? 0} cases`}>
        {conflicts.isLoading && !conflicts.data ? <div className="loading-inline"><span className="spinner" /><span>Loading conflicts…</span></div> : conflicts.error ? <ErrorBlock error={conflicts.error} />
          : cRows.length === 0 ? <EmptyState message="No conflict cases." />
            : <TableWrap><table className="data-table">
              <thead><tr><th>Record</th><th>Type</th><th>Field</th><th>Severity</th><th>Description</th><th>Status</th><th></th></tr></thead>
              <tbody>{cRows.map((r) => (
                <tr key={String(r.id)}>
                  <td><Link className="link" to={`/faculty/records/${r.ip_record_id}`}>{String(r.ip_record_id).slice(0, 8)}…</Link></td>
                  <td>{display(r.conflict_type)}</td>
                  <td>{display(r.field_name)}</td>
                  <td><StatusBadge value={String(r.severity || 'MEDIUM')} /></td>
                  <td>{display(r.description)}</td>
                  <td><StatusBadge value={String(r.status || 'OPEN')} /></td>
                  <td>{String(r.status) === 'OPEN'
                    ? <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => setConfirm({ kind: 'conflict', row: r })}>Resolve</button>
                    : <span className="muted">{display(r.resolution_notes) || '—'}</span>}</td>
                </tr>
              ))}</tbody>
            </table></TableWrap>}
      </SectionCard>

      <SectionCard title="Association / Contributor Review" subtitle={`${associations.data?.total ?? 0} requests`} actions={<Link className="btn btn-sm btn-secondary" to="/faculty/associations">Open associations</Link>}>
        {associations.isLoading && !associations.data ? <div className="loading-inline"><span className="spinner" /><span>Loading associations…</span></div> : associations.error ? <ErrorBlock error={associations.error} />
          : aRows.length === 0 ? <EmptyState message="No association requests." />
            : <TableWrap><table className="data-table">
              <thead><tr><th>Requester</th><th>Recipient</th><th>Record</th><th>Reason</th><th>Status</th><th>Created</th></tr></thead>
              <tbody>{aRows.map((r) => (
                <tr key={String(r.id)}>
                  <td>{display(r.requesting_faculty_id || r.requester_id)}</td>
                  <td>{display(r.target_faculty_id || r.recipient_id)}</td>
                  <td>{r.ip_record_id ? <Link className="link" to={`/faculty/records/${r.ip_record_id}`}>{String(r.ip_record_id).slice(0, 8)}…</Link> : '—'}</td>
                  <td>{display(r.reason || r.message)}</td>
                  <td><StatusBadge value={String(r.status || 'PENDING')} /></td>
                  <td>{formatDateTime(r.created_at)}</td>
                </tr>
              ))}</tbody>
            </table></TableWrap>}
      </SectionCard>

      {confirm && (
        <Modal
          title={confirm.kind === 'verify' ? 'Retry verification' : confirm.kind === 'duplicate' ? 'Resolve duplicate case' : 'Resolve conflict'}
          onClose={() => setConfirm(null)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => setConfirm(null)}>Cancel</button>
              <button
                className="btn btn-primary"
                disabled={busy}
                onClick={() => {
                  if (confirm.kind === 'verify') retryVerification.mutate(String(confirm.row.id));
                  else if (confirm.kind === 'duplicate') resolveDuplicate.mutate({ caseId: String(confirm.row.id), keepRecordId: String(confirm.row.ip_record_id_1) });
                  else resolveConflict.mutate(String(confirm.row.id));
                }}
              >
                Confirm
              </button>
            </>
          }
        >
          {confirm.kind === 'verify' && <p>Re-run the verification pipeline for record <strong>{String(confirm.row.ip_record_id).slice(0, 12)}…</strong>?</p>}
          {confirm.kind === 'duplicate' && <p>Resolve this duplicate case, keeping <strong>{String(confirm.row.ip_record_id_1).slice(0, 8)}…</strong> as canonical.</p>}
          {confirm.kind === 'conflict' && <p>Mark this conflict case as resolved.</p>}
        </Modal>
      )}
    </div>
  );
}

function ConflictDetailModal({ conflict, onClose, onResolve, busy }: { conflict: Row | null; onClose: () => void; onResolve: (action: 'resolve' | 'dismiss', resolution?: string, value?: 'certificate' | 'official' | 'manual') => void; busy: boolean }) {
  if (!conflict) return null;
  
  const detectedValue = conflict.detected_value as string | undefined;
  const expectedValue = conflict.expected_value as string | undefined;
  const canonicalValue = (conflict as any).canonical_value as string | undefined;
  const fieldName = conflict.field_name as string | undefined;
  const conflictType = conflict.conflict_type as string | undefined;
  
  return (
    <Modal
      title={`Conflict: ${display(conflictType)}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Close</button>
          {conflict.status === 'OPEN' && (
            <>
              <button className="btn btn-danger" disabled={busy} onClick={() => onResolve('dismiss', 'Dismissed as false positive')}>Dismiss</button>
              {fieldName && detectedValue && expectedValue && (
                <>
                  <button className="btn btn-warning" disabled={busy} onClick={() => onResolve('resolve', 'Use certificate value', 'certificate')}>Use Certificate Value</button>
                  <button className="btn btn-primary" disabled={busy} onClick={() => onResolve('resolve', 'Use official value', 'official')}>Use Official Value</button>
                  <button className="btn btn-info" disabled={busy} onClick={() => onResolve('resolve', 'Enter manual value', 'manual')}>Enter Manual Value</button>
                </>
              )}
              <button className="btn btn-success" disabled={busy} onClick={() => onResolve('resolve', 'Resolved without value change')}>Mark Resolved</button>
            </>
          )}
        </>
      }
    >
      <div className="stack">
        <div className="detail-field"><span>Conflict ID</span><strong>{display(conflict.id)}</strong></div>
        <div className="detail-field"><span>Record</span><strong><Link className="link" to={`/faculty/records/${conflict.ip_record_id}`}>{display(conflict.ip_record_id)}</Link></strong></div>
        <div className="detail-field"><span>Type</span><strong>{display(conflictType)}</strong></div>
        <div className="detail-field"><span>Severity</span><strong><span className={`status-badge ${(conflict.severity as string || 'MEDIUM').toLowerCase()}`}>{display(conflict.severity)}</span></strong></div>
        <div className="detail-field"><span>Status</span><strong><span className={`status-badge ${(conflict.status as string || 'OPEN').toLowerCase()}`}>{display(conflict.status)}</span></strong></div>
        <div className="detail-field"><span>Created</span><strong>{conflict.created_at ? new Date(conflict.created_at as string).toLocaleString() : '—'}</strong></div>
        {fieldName && (
          <div className="section-head"><h3>Field Comparison</h3></div>
        )}
        {fieldName && (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Source</th><th>Value</th></tr></thead>
              <tbody>
                {detectedValue && <tr><td><strong>Certificate / OCR</strong></td><td><code>{display(detectedValue)}</code></td></tr>}
                {expectedValue && <tr><td><strong>Official Source</strong></td><td><code>{display(expectedValue)}</code></td></tr>}
                {canonicalValue && <tr><td><strong>Canonical / Current</strong></td><td><code>{display(canonicalValue)}</code></td></tr>}
              </tbody>
            </table>
          </div>
        )}
        {conflict.description != null && (
          <div className="section-head"><h3>Description</h3></div>
        )}
        {(conflict.description as string | undefined) && <div className="muted" style={{ whiteSpace: 'pre-wrap' }}>{display(conflict.description as string | undefined)}</div>}
        {conflict.resolution_notes != null && (
          <div className="section-head"><h3>Resolution Notes</h3></div>
        )}
        {(conflict.resolution_notes as string | undefined) && <div className="muted" style={{ whiteSpace: 'pre-wrap' }}>{display(conflict.resolution_notes as string | undefined)}</div>}
      </div>
    </Modal>
  );
}

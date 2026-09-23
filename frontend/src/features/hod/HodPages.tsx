import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import {
  SectionCard, StatCard, StatusBadge, ErrorBlock, EmptyState,
  Toolbar, TableWrap, Pagination, Modal, formatDateTime, formatDate, display, docName,
} from '../../components/ui';
import { useToast } from '../../stores/toast';
import { useDebounce } from '../../hooks/useDebounce';

/* --------------------------------- Dashboard -------------------------------- */

export function HodDashboardPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['hod-dashboard'], queryFn: api.hodDashboard });
  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading department dashboard…</span></div>;
  if (error) return <ErrorBlock error={error} />;
  const k = data?.kpis ?? {};
  return (
    <SectionCard title="Department Dashboard" subtitle="Live, department-scoped counters.">
      <div className="grid stats-grid">
        <StatCard label="Faculty" value={k.total_faculty ?? 0} />
        <StatCard label="Documents" value={k.total_documents ?? 0} />
        <StatCard label="Verified" value={k.verified ?? 0} />
        <StatCard label="Pending" value={k.pending ?? 0} />
        <StatCard label="Rejected" value={k.rejected ?? 0} />
        <StatCard label="Requires approval" value={k.requires_approval ?? 0} />
        <StatCard label="Open conflicts" value={k.conflicts ?? 0} />
        <StatCard label="Open duplicates" value={k.duplicates ?? 0} />
      </div>
    </SectionCard>
  );
}

/* ---------------------------------- Faculty -------------------------------- */

export function HodFacultyPage() {
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 400);
  const [activeOnly, setActiveOnly] = useState(false);
  // Server-side search if available, else client-side debounced
  const params = useMemo(() => debouncedSearch.trim() ? `?search=${encodeURIComponent(debouncedSearch.trim())}` : '', [debouncedSearch]);
  const { data, isLoading, error, isFetching, refetch } = useQuery({ queryKey: ['hod-faculty', params], queryFn: ({ signal }) => api.hodFaculty(params, signal), placeholderData: keepPreviousData });

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading department faculty…</span></div>;
  if (error && !data) return <ErrorBlock error={error} />;

  // If backend already filtered via search param, no need for client filter; keep as fallback for small datasets
  const rows = (data?.faculty ?? []).filter((f) => {
    if (debouncedSearch.trim() && params) return true; // server already filtered
    const hay = `${f.full_name} ${f.faculty_id} ${f.email}`.toLowerCase();
    return (!debouncedSearch || hay.includes(debouncedSearch.toLowerCase())) && (!activeOnly || f.is_active);
  });

  return (
    <SectionCard title="Department Faculty" subtitle={`${data?.count ?? 0} faculty in your department.`}>
      <Toolbar>
        <input className="toolbar-input" placeholder="Search name, ID, email" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search faculty" />
        <label className="pill-row" style={{ gap: 6 }}>
          <input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} />
          <span className="muted">Active only</span>
        </label>
      </Toolbar>
      {error && data ? (
        <div className="alert alert-error" role="alert" style={{ marginBottom: 12 }}>
          Refresh failed: {error instanceof Error ? error.message : String(error)}{' '}
          <button className="btn btn-sm btn-secondary" onClick={() => void refetch()} disabled={isFetching}>Retry</button>
        </div>
      ) : null}
      {rows.length === 0 && !isFetching ? (
        <EmptyState message="No faculty match your filters." />
      ) : (
        <div className={isFetching && data ? 'table-fetching' : ''}>
          {isFetching && data ? <div className="table-fetching-indicator"><span className="spinner" /> Updating…</div> : null}
          <TableWrap>
          <table className="data-table">
            <thead>
              <tr><th>Name</th><th>Faculty ID</th><th>Designation</th><th>Documents</th><th>Patents</th><th>Verified</th><th>Pending</th><th>Rejected</th><th>Status</th></tr>
            </thead>
            <tbody>
              {rows.map((f) => {
                const c = (f.counts ?? {}) as Record<string, number>;
                return (
                  <tr key={String(f.id)}>
                    <td><strong>{display(f.full_name)}</strong><div className="muted">{display(f.email)}</div></td>
                    <td>{display(f.faculty_id)}</td>
                    <td>{display(f.designation_name)}</td>
                    <td>{c.documents ?? 0}</td>
                    <td>{c.patents ?? 0}</td>
                    <td>{c.verified ?? 0}</td>
                    <td>{c.pending ?? 0}</td>
                    <td>{c.rejected ?? 0}</td>
                    <td><StatusBadge value={f.is_active ? 'ACTIVE' : 'INACTIVE'} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
        </div>
      )}
    </SectionCard>
  );
}

/* --------------------------------- Documents ------------------------------- */

export function HodDocumentsPage() {
  const client = useQueryClient();
  const { notify } = useToast();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 400);
  const [verifyTarget, setVerifyTarget] = useState<Record<string, unknown> | null>(null);
  const [verifyRemarks, setVerifyRemarks] = useState('');
  const [verifyEvidenceRef, setVerifyEvidenceRef] = useState('');

  const params = useMemo(() => {
    const q = new URLSearchParams({ page: String(page), per_page: '20' });
    if (status) q.set('status', status);
    if (debouncedSearch.trim()) q.set('search', debouncedSearch.trim());
    return `?${q.toString()}`;
  }, [page, status, debouncedSearch]);

  const { data, isLoading, error, isFetching, refetch } = useQuery({ queryKey: ['hod-documents', params], queryFn: ({ signal }) => api.hodDocuments(params, signal), placeholderData: keepPreviousData });

  const verifyMutation = useMutation({
    mutationFn: ({ recordId, decision, remarks, evidenceRef }: { recordId: string; decision: 'verify' | 'reject' | 'clarification'; remarks?: string; evidenceRef?: string }) =>
      api.institutionalVerify(recordId, { decision, remarks, evidence_ref: evidenceRef }),
    onSuccess: async (result) => {
      notify('success', `Institutional verification recorded: ${result.decision}. Final status: ${result.final_verification_status}`);
      setVerifyTarget(null);
      setVerifyRemarks('');
      setVerifyEvidenceRef('');
      await Promise.all([
        client.invalidateQueries({ queryKey: ['hod-documents'] }),
        client.invalidateQueries({ queryKey: ['hod-dashboard'] }),
      ]);
    },
    onError: (e) => notify('error', e instanceof Error ? e.message : 'Verification failed'),
  });

  // Bug 3: when the HOD opens the verify dialog, load the record's
  // outstanding internal approvals. "Confirm Verified" stays disabled while
  // acceptance is pending (the backend rejects verify with 409 regardless).
  const verifyRecordId = verifyTarget ? String(verifyTarget.id) : '';
  const verifyEligibility = useQuery({
    queryKey: ['hod-verify-eligibility', verifyRecordId],
    queryFn: () => api.institutionalStatus(verifyRecordId),
    enabled: Boolean(verifyRecordId),
    staleTime: 30 * 1000,
  });
  const pendingApprovals = Array.isArray(verifyEligibility.data?.pending_approvals)
    ? (verifyEligibility.data?.pending_approvals as string[])
    : [];
  const verifyBlocked = pendingApprovals.length > 0;

  const docs = data?.documents ?? [];

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading department documents…</span></div>;
  if (error && !data) return <ErrorBlock error={error} />;

  return (
    <SectionCard title="Department Documents" subtitle={`${data?.total ?? 0} documents in your department.`}>
      <Toolbar>
        <input className="toolbar-input" placeholder="Search title or number" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} aria-label="Search documents" />
        <select className="toolbar-input" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Filter by status">
          <option value="">All statuses</option>
          <option value="AWAITING_REVIEW">Awaiting review</option>
          <option value="VERIFICATION_REQUIRED">Verification required (needs manual official check)</option>
          <option value="VERIFIED">Verified</option>
          <option value="DUPLICATE_REVIEW">Duplicate review</option>
          <option value="FAILED">Failed</option>
        </select>
      </Toolbar>
      {error && data ? (
        <div className="alert alert-error" role="alert" style={{ marginBottom: 12 }}>
          Refresh failed: {error instanceof Error ? error.message : String(error)}{' '}
          <button className="btn btn-sm btn-secondary" onClick={() => void refetch()} disabled={isFetching}>Retry</button>
        </div>
      ) : null}
      {docs.length === 0 && !isFetching ? (
        <EmptyState message="No documents match your filters." />
      ) : (
        <div className={isFetching && data ? 'table-fetching' : ''}>
          {isFetching && data ? <div className="table-fetching-indicator"><span className="spinner" /> Updating…</div> : null}
          <TableWrap>
          <table className="data-table">
            <thead>
              <tr><th>Document</th><th>Faculty</th><th>Type</th><th>Grant Date</th><th>Uploaded</th><th>Processing</th><th>Verification</th><th>Flags</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={String(d.id)}>
                  <td>
                    {/* Bugs 4+5: persisted document name first; the raw UUID
                        is never the primary user-facing identifier. */}
                    <strong><Link className="link" to={`/faculty/records/${d.id}`}>{display(d.document_name || d.title || d.patent_number || d.design_number || 'Untitled document')}</Link></strong>
                    <div className="muted">{display(d.ip_type)}{d.document_filename && d.document_filename !== d.title ? ` · ${display(d.document_filename)}` : ''}</div>
                  </td>
                  <td>{display(d.faculty_name)}<div className="muted">{display(d.faculty_id)}</div></td>
                  <td>{display(d.ip_type)}</td>
                  <td>{d.grant_date ? formatDate(d.grant_date) : '—'}</td>
                  <td>{formatDate(d.created_at)}</td>
                  <td><StatusBadge value={String(d.processing_status || 'UNKNOWN')} /></td>
                  <td><StatusBadge value={String(d.verification_status || 'UNKNOWN')} /></td>
                  <td>
                    <div className="pill-row">
                      {d.has_duplicate ? <StatusBadge value="DUPLICATE" /> : null}
                      {d.has_conflict ? <StatusBadge value="CONFLICT" /> : null}
                      {!d.has_duplicate && !d.has_conflict ? <span className="muted">—</span> : null}
                    </div>
                  </td>
                  <td>
                    <div className="btn-row">
                      <Link className="link" to={`/faculty/records/${d.id}`}>View</Link>
                      {String(d.verification_status) !== 'VERIFIED' && (
                        <button className="btn btn-sm btn-primary" onClick={() => { setVerifyTarget(d); setVerifyRemarks(''); setVerifyEvidenceRef(''); }}>
                          Manual Verify
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        </div>
      )}
      <Pagination page={page} totalPages={data?.total_pages ?? 1} onChange={setPage} disabled={isFetching} />

      {verifyTarget && (
        <Modal
          title="HOD Manual Official Verification"
          onClose={() => { setVerifyTarget(null); setVerifyRemarks(''); setVerifyEvidenceRef(''); }}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => { setVerifyTarget(null); setVerifyRemarks(''); setVerifyEvidenceRef(''); }}>Cancel</button>
              <button className="btn btn-secondary" disabled={verifyMutation.isPending} onClick={() => verifyMutation.mutate({ recordId: String(verifyTarget.id), decision: 'reject', remarks: verifyRemarks || undefined, evidenceRef: verifyEvidenceRef || undefined })}>
                {verifyMutation.isPending ? 'Saving…' : 'Reject'}
              </button>
              <button className="btn btn-primary" disabled={verifyMutation.isPending || verifyBlocked} onClick={() => verifyMutation.mutate({ recordId: String(verifyTarget.id), decision: 'verify', remarks: verifyRemarks || undefined, evidenceRef: verifyEvidenceRef || undefined })}>
                {verifyMutation.isPending ? 'Saving…' : 'Confirm Verified'}
              </button>
            </>
          }
        >
          <div className="stack">
            {verifyBlocked ? (
              <div className="alert alert-error" role="alert">
                Verification is blocked until required internal faculty acceptance is recorded
                ({pendingApprovals.length} pending). The “Confirm Verified” action is disabled.
              </div>
            ) : null}
            <div className="alert alert-info" style={{ background: '#eef3fb', color: 'var(--primary)', border: '1px solid #cdd8ea' }}>
              <strong>Manual Official Verification</strong>
              <p style={{ margin: '6px 0 0', fontSize: 13 }}>
                By clicking "Confirm Verified", you certify that you have manually checked this record against the official IP portal
                and the submitted details match. This is an institutional verification — not an automated IP India verification.
              </p>
            </div>
            <div className="detail-field">
              <span>Record</span>
              <strong>{display(verifyTarget.title || verifyTarget.patent_number || verifyTarget.design_number || verifyTarget.id)}</strong>
            </div>
            <div className="detail-field">
              <span>Faculty</span>
              <strong>{display(verifyTarget.faculty_name)}</strong>
            </div>
            <div className="detail-field">
              <span>Current verification status</span>
              <strong><StatusBadge value={String(verifyTarget.verification_status || 'UNKNOWN')} /></strong>
            </div>
            <label className="field">
              <span>Remarks (optional)</span>
              <textarea className="toolbar-input" rows={3} placeholder="e.g. Checked IP India portal on 2025-01-15, patent number matches" value={verifyRemarks} onChange={(e) => setVerifyRemarks(e.target.value)} />
            </label>
            <label className="field">
              <span>Evidence reference (optional)</span>
              <input className="toolbar-input" placeholder="e.g. IP India screenshot URL or reference number" value={verifyEvidenceRef} onChange={(e) => setVerifyEvidenceRef(e.target.value)} />
            </label>
          </div>
        </Modal>
      )}
    </SectionCard>
  );
}

/* -------------------------------- Duplicates ------------------------------- */

export function HodDuplicatesPage() {
  const client = useQueryClient();
  const { notify } = useToast();
  const [confirmCase, setConfirmCase] = useState<Record<string, unknown> | null>(null);
  const [confirmReject, setConfirmReject] = useState<Record<string, unknown> | null>(null);
  const { data, isLoading, error } = useQuery({ queryKey: ['hod-duplicates'], queryFn: () => api.hodDuplicates() });

  const resolve = useMutation({
    mutationFn: ({ id, keep }: { id: string; keep: string }) => api.resolveDuplicate(id, keep, 'resolve'),
    onSuccess: async () => {
      notify('success', 'Duplicate case resolved');
      setConfirmCase(null);
      await Promise.all([
        client.invalidateQueries({ queryKey: ['hod-duplicates'] }),
        client.invalidateQueries({ queryKey: ['hod-dashboard'] }),
        client.invalidateQueries({ queryKey: ['hod-documents'] }),
      ]);
    },
    onError: (e) => notify('error', e instanceof Error ? e.message : 'Failed to resolve'),
  });

  const reject = useMutation({
    mutationFn: ({ id }: { id: string }) => api.resolveDuplicate(id, '', 'dismiss'),
    onSuccess: async () => {
      notify('success', 'Duplicate case rejected');
      setConfirmReject(null);
      await Promise.all([
        client.invalidateQueries({ queryKey: ['hod-duplicates'] }),
        client.invalidateQueries({ queryKey: ['hod-dashboard'] }),
        client.invalidateQueries({ queryKey: ['hod-documents'] }),
      ]);
    },
    onError: (e) => notify('error', e instanceof Error ? e.message : 'Failed to reject'),
  });

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading duplicates…</span></div>;
  if (error) return <ErrorBlock error={error} />;

  const rows = data?.duplicates ?? [];

  return (
    <SectionCard title="Department Duplicates" subtitle={`${data?.count ?? 0} duplicate cases touching your department.`}>
      {rows.length === 0 ? (
        <EmptyState message="No duplicate cases in your department." />
      ) : (
        <TableWrap>
          <table className="data-table">
            <thead>
              <tr><th>Record</th><th>Duplicate of</th><th>Confidence</th><th>Method</th><th>Detected by</th><th>Detected</th><th>Status</th><th>Action</th></tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={String(d.id)}>
                  {/* Bugs 4+5: persisted document names via record_1/record_2
                      (backend-enriched); the raw UUID is never displayed. */}
                  <td><Link className="link" to={`/faculty/records/${d.ip_record_id_1}`}>{docName(d.record_1)}</Link></td>
                  <td><Link className="link" to={`/faculty/records/${d.ip_record_id_2}`}>{docName(d.record_2)}</Link></td>
                  <td>{d.confidence != null ? `${Math.round(Number(d.confidence) * 100)}%` : '—'}</td>
                  <td>{display(d.detection_method)}</td>
                  <td>{display(d.detected_by)}</td>
                  <td>{formatDate(d.detected_at)}</td>
                  <td><StatusBadge value={String(d.status || 'OPEN')} /></td>
                  <td>
                    {String(d.status) === 'OPEN'
                      ? (
                        <div className="btn-row">
                          <button className="btn btn-sm btn-primary" disabled={resolve.isPending} onClick={() => setConfirmCase(d)}>Resolve</button>
                          <button className="btn btn-sm btn-danger" disabled={reject.isPending} onClick={() => setConfirmReject(d)}>Reject</button>
                        </div>
                      )
                      : <span className="muted">{display(d.resolution_notes) || '—'}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
      {confirmCase && (
        <Modal
          title="Resolve duplicate case"
          onClose={() => setConfirmCase(null)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => setConfirmCase(null)}>Cancel</button>
              <button
                className="btn btn-primary"
                disabled={resolve.isPending}
                onClick={() => resolve.mutate({ id: String(confirmCase.id), keep: String(confirmCase.ip_record_id_1) })}
              >
                Resolve — keep {String(confirmCase.ip_record_id_1).slice(0, 8)}…
              </button>
            </>
          }
        >
          <p>Mark this duplicate case resolved, keeping record <strong>{String(confirmCase.ip_record_id_1).slice(0, 8)}…</strong> as the canonical one.</p>
        </Modal>
      )}
      {confirmReject && (
        <Modal
          title="Reject duplicate case"
          onClose={() => setConfirmReject(null)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => setConfirmReject(null)}>Cancel</button>
              <button
                className="btn btn-danger"
                disabled={reject.isPending}
                onClick={() => reject.mutate({ id: String(confirmReject.id) })}
              >
                Reject duplicate
              </button>
            </>
          }
        >
          <p>Reject this duplicate case. Both records will remain but the duplicate flag will be dismissed.</p>
        </Modal>
      )}
    </SectionCard>
  );
}

/* -------------------------------- Conflicts -------------------------------- */

export function HodConflictsPage() {
  const client = useQueryClient();
  const { notify } = useToast();
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const { data, isLoading, error } = useQuery({ queryKey: ['hod-conflicts'], queryFn: () => api.hodConflicts() });

  const resolve = useMutation({
    mutationFn: (id: string) => api.resolveConflict(id, 'resolve'),
    onSuccess: async () => {
      notify('success', 'Conflict resolved');
      setConfirmId(null);
      await Promise.all([
        client.invalidateQueries({ queryKey: ['hod-conflicts'] }),
        client.invalidateQueries({ queryKey: ['hod-dashboard'] }),
      ]);
    },
    onError: (e) => notify('error', e instanceof Error ? e.message : 'Failed to resolve'),
  });

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading conflicts…</span></div>;
  if (error) return <ErrorBlock error={error} />;

  const rows = data?.conflicts ?? [];

  return (
    <SectionCard title="Department Conflicts" subtitle={`${data?.count ?? 0} conflict cases in your department.`}>
      {rows.length === 0 ? (
        <EmptyState message="No conflict cases in your department." />
      ) : (
        <TableWrap>
          <table className="data-table">
            <thead>
              <tr><th>Record</th><th>Type</th><th>Field</th><th>Severity</th><th>Description</th><th>Status</th><th>Action</th></tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={String(c.id)}>
                  <td><Link className="link" to={`/faculty/records/${c.ip_record_id}`}>{docName(c.record)}</Link></td>
                  <td>{display(c.conflict_type)}</td>
                  <td>{display(c.field_name)}</td>
                  <td><StatusBadge value={String(c.severity || 'MEDIUM')} /></td>
                  <td>{display(c.description)}</td>
                  <td><StatusBadge value={String(c.status || 'OPEN')} /></td>
                  <td>
                    {String(c.status) === 'OPEN'
                      ? <button className="btn btn-sm btn-primary" disabled={resolve.isPending} onClick={() => setConfirmId(String(c.id))}>Resolve</button>
                      : <span className="muted">{display(c.resolution_notes) || '—'}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
      {confirmId && (
        <Modal
          title="Resolve conflict"
          onClose={() => setConfirmId(null)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => setConfirmId(null)}>Cancel</button>
              <button className="btn btn-primary" disabled={resolve.isPending} onClick={() => resolve.mutate(confirmId)}>Mark resolved</button>
            </>
          }
        >
          <p>Mark this conflict case as resolved for your department.</p>
        </Modal>
      )}
    </SectionCard>
  );
}

/* --------------------------------- Reports -------------------------------- */

export function HodReportsPage() {
  const { notify } = useToast();
  const { data, isLoading, error } = useQuery({ queryKey: ['hod-reports'], queryFn: () => api.hodReports() });
  const reminders = useMutation({
    mutationFn: () => api.hodReminders({ kind: 'pending_documents' }),
    onSuccess: (r) => notify('success', `Reminder queued for ${(r as { count?: number }).count ?? 0} pending documents`),
    onError: () => notify('error', 'Failed to send reminders'),
  });

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading department report…</span></div>;
  if (error) return <ErrorBlock error={error} />;

  const summary = (data?.summary ?? {}) as Record<string, number>;
  const byType = (data?.by_type ?? {}) as Record<string, number>;
  const byVerif = (data?.by_verification ?? {}) as Record<string, number>;
  const byYear = (data?.by_year ?? {}) as Record<string, number>;
  const trend = (data?.upload_trend ?? []) as Array<{ date: string; value: number }>;

  return (
    <div className="stack-lg">
      <SectionCard
        title="Department Report"
        subtitle="Aggregated statistics for your department."
        actions={<button className="btn btn-sm btn-secondary" disabled={reminders.isPending} onClick={() => reminders.mutate()}>Send pending-document reminders</button>}
      >
        <div className="grid stats-grid">
          <StatCard label="Documents" value={summary.total_documents ?? 0} />
          <StatCard label="Faculty" value={summary.total_faculty ?? 0} />
          <StatCard label="Verified" value={summary.verified ?? 0} />
          <StatCard label="Pending" value={summary.pending ?? 0} />
          <StatCard label="Rejected" value={summary.rejected ?? 0} />
          <StatCard label="Open duplicates" value={summary.duplicates_open ?? 0} />
          <StatCard label="Open conflicts" value={summary.conflicts_open ?? 0} />
        </div>
      </SectionCard>

      <div className="grid detail-grid">
        <BreakdownCard title="By document type" data={byType} />
        <BreakdownCard title="By verification status" data={byVerif} />
      </div>

      <SectionCard title="Uploads by year">
        <Bars data={byYear} />
      </SectionCard>

      <SectionCard title="Upload trend (monthly)">
        {trend.length === 0 ? <EmptyState message="No uploads recorded yet." /> : (
          <Bars data={Object.fromEntries(trend.map((t) => [new Date(t.date).toLocaleDateString(undefined, { month: 'short', year: '2-digit' }), t.value]))} />
        )}
      </SectionCard>
    </div>
  );
}

function BreakdownCard({ title, data }: { title: string; data: Record<string, number> }) {
  const entries = Object.entries(data);
  return (
    <SectionCard title={title}>
      {entries.length === 0 ? <EmptyState message="No data." /> : (
        <div className="stack">
          {entries.map(([k, v]) => (
            <div key={k} className="pill-row" style={{ justifyContent: 'space-between' }}>
              <StatusBadge value={k} />
              <strong>{v}</strong>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function Bars({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return <EmptyState message="No data." />;
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return (
    <div className="stack">
      {entries.map(([k, v]) => (
        <div key={k} className="bar-row">
          <span className="bar-label">{k}</span>
          <span className="bar-track"><span className="bar-fill" style={{ width: `${(v / max) * 100}%` }} /></span>
          <strong className="bar-value">{v}</strong>
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------- Audit -------------------------------- */

export function HodAuditPage() {
  const [page, setPage] = useState(1);
  const { data, isLoading, error, isFetching, refetch } = useQuery({
    queryKey: ['hod-audit', page],
    queryFn: ({ signal }) => api.hodAudit(`?page=${page}&per_page=25`, signal),
    placeholderData: keepPreviousData,
  });

  const rows = data?.audit_entries ?? [];

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading department audit…</span></div>;
  if (error && !data) return <ErrorBlock error={error} />;

  return (
    <SectionCard title="Department Audit" subtitle={`${data?.total ?? 0} recorded actions for your department.`}>
      {error && data ? (
        <div className="alert alert-error" role="alert" style={{ marginBottom: 12 }}>
          Refresh failed: {error instanceof Error ? error.message : String(error)}{' '}
          <button className="btn btn-sm btn-secondary" onClick={() => void refetch()} disabled={isFetching}>Retry</button>
        </div>
      ) : null}
      {rows.length === 0 && !isFetching ? (
        <EmptyState message="No audit activity for your department yet." />
      ) : (
        <div className={isFetching && data ? 'table-fetching' : ''}>
          {isFetching && data ? <div className="table-fetching-indicator"><span className="spinner" /> Updating…</div> : null}
          <TableWrap>
          <table className="data-table">
            <thead><tr><th>Action</th><th>Actor</th><th>Entity</th><th>Details</th><th>When</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={String(r.id)}>
                  <td><strong>{String(r.action).replace(/_/g, ' ')}</strong></td>
                  <td>{display(r.actor_id)}</td>
                  <td>{display(r.entity_type)}<div className="muted">{String(r.entity_id || '').slice(0, 8)}</div></td>
                  <td className="muted">{display(r.new_value)}</td>
                  <td>{formatDateTime(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        </div>
      )}
      <Pagination page={page} totalPages={data?.total_pages ?? 1} onChange={setPage} disabled={isFetching} />
    </SectionCard>
  );
}

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import {
  SectionCard, StatCard, StatusBadge, ErrorBlock, EmptyState,
  Toolbar, TableWrap, Pagination, formatDateTime, formatDate, formatDateOnly, display, docName, personName,
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
  // HOD is a READ-ONLY institutional review/visibility role: this page
  // lists department documents with full detail links. There are no HOD
  // approval actions anywhere — faculty association and Super Admin grant
  // are the only human gates.
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 400);

  const params = useMemo(() => {
    const q = new URLSearchParams({ page: String(page), per_page: '20' });
    if (status) q.set('status', status);
    if (debouncedSearch.trim()) q.set('search', debouncedSearch.trim());
    return `?${q.toString()}`;
  }, [page, status, debouncedSearch]);

  const { data, isLoading, error, isFetching, refetch } = useQuery({ queryKey: ['hod-documents', params], queryFn: ({ signal }) => api.hodDocuments(params, signal), placeholderData: keepPreviousData });

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
                  <td>{d.grant_date ? formatDateOnly(d.grant_date) : '—'}</td>
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

    </SectionCard>
  );
}

/* -------------------------------- Duplicates ------------------------------- */

export function HodDuplicatesPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['hod-duplicates'], queryFn: () => api.hodDuplicates() });

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading duplicates…</span></div>;
  if (error) return <ErrorBlock error={error} />;

  const rows = data?.duplicates ?? [];

  return (
    <SectionCard title="Department Duplicates" subtitle={`${data?.count ?? 0} duplicate cases touching your department. Read-only.`}>
      {rows.length === 0 ? (
        <EmptyState message="No duplicate cases in your department." />
      ) : (
        <TableWrap>
          <table className="data-table">
            <thead>
              <tr><th>Record</th><th>Duplicate of</th><th>Confidence</th><th>Method</th><th>Detected by</th><th>Detected</th><th>Status</th><th>Resolution</th></tr>
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
                  <td><span className="muted">{display(d.resolution_notes) || '—'}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </SectionCard>
  );
}

/* -------------------------------- Conflicts -------------------------------- */

export function HodConflictsPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['hod-conflicts'], queryFn: () => api.hodConflicts() });

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading conflicts…</span></div>;
  if (error) return <ErrorBlock error={error} />;

  const rows = data?.conflicts ?? [];

  return (
    <SectionCard title="Department Conflicts" subtitle={`${data?.count ?? 0} conflict cases in your department. Read-only.`}>
      {rows.length === 0 ? (
        <EmptyState message="No conflict cases in your department." />
      ) : (
        <TableWrap>
          <table className="data-table">
            <thead>
              <tr><th>Record</th><th>Type</th><th>Field</th><th>Severity</th><th>Description</th><th>Status</th><th>Resolution</th></tr>
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
                  <td><span className="muted">{display(c.resolution_notes) || '—'}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
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

/**
 * Bug 4: HOD audit readability helpers. Prefer backend-resolved human names;
 * raw UUIDs appear only as secondary muted text (traceability preserved).
 */
export function auditPerson(info: unknown, fallbackId?: unknown): React.ReactNode {
  if (info && typeof info === 'object') {
    const r = info as Record<string, unknown>;
    const name = r.full_name || r.faculty_id;
    if (typeof name === 'string' && name.trim()) {
      return <span>{name}{typeof r.faculty_id === 'string' && r.faculty_id !== name ? <span className="muted"> · {r.faculty_id}</span> : null}</span>;
    }
  }
  return <span>{personName(info, fallbackId)}</span>;
}

export function auditEntity(info: unknown, entityType?: unknown, entityId?: unknown): React.ReactNode {
  const label = typeof entityType === 'string' && entityType ? entityType.replace(/_/g, ' ') : 'Event';
  if (info && typeof info === 'object') {
    const r = info as Record<string, unknown>;
    const name = r.display_name || r.full_name || r.title || r.faculty_id;
    if (typeof name === 'string' && name.trim()) {
      return <span>{label}<div><strong>{name}</strong></div></span>;
    }
  }
  if (typeof entityId === 'string' && entityId.trim()) {
    return <span>{label}<div className="muted">{entityId.slice(0, 8)}…</div></span>;
  }
  return <span>{label}</span>;
}

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
                  {/* Bug 4: human-readable actor + entity names first; raw IDs
                      stay only as secondary muted text for traceability. */}
                  <td>{auditPerson(r.actor, r.actor_id)}</td>
                  <td>{auditEntity(r.entity, r.entity_type, r.entity_id)}</td>
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

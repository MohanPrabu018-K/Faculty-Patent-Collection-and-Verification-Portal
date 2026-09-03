import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import {
  SectionCard, StatCard, StatusBadge, LoadingBlock, ErrorBlock, EmptyState,
  Toolbar, TableWrap, Pagination, Modal, formatDateTime, formatDate, display,
} from '../../components/ui';
import { useToast } from '../../stores/toast';

/* --------------------------------- Dashboard -------------------------------- */

export function HodDashboardPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['hod-dashboard'], queryFn: api.hodDashboard });
  if (isLoading) return <LoadingBlock label="Loading department dashboard…" />;
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
  const [activeOnly, setActiveOnly] = useState(false);
  const { data, isLoading, error } = useQuery({ queryKey: ['hod-faculty'], queryFn: () => api.hodFaculty() });

  if (isLoading) return <LoadingBlock label="Loading department faculty…" />;
  if (error) return <ErrorBlock error={error} />;

  const rows = (data?.faculty ?? []).filter((f) => {
    const hay = `${f.full_name} ${f.faculty_id} ${f.email}`.toLowerCase();
    return (!search || hay.includes(search.toLowerCase())) && (!activeOnly || f.is_active);
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
      {rows.length === 0 ? (
        <EmptyState message="No faculty match your filters." />
      ) : (
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
      )}
    </SectionCard>
  );
}

/* --------------------------------- Documents ------------------------------- */

export function HodDocumentsPage() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');

  const params = useMemo(() => {
    const q = new URLSearchParams({ page: String(page), per_page: '20' });
    if (status) q.set('status', status);
    if (search) q.set('search', search);
    return `?${q.toString()}`;
  }, [page, status, search]);

  const { data, isLoading, error, isFetching } = useQuery({ queryKey: ['hod-documents', params], queryFn: () => api.hodDocuments(params) });

  if (isLoading) return <LoadingBlock label="Loading department documents…" />;
  if (error) return <ErrorBlock error={error} />;

  const docs = data?.documents ?? [];

  return (
    <SectionCard title="Department Documents" subtitle={`${data?.total ?? 0} documents in your department.`}>
      <Toolbar>
        <input className="toolbar-input" placeholder="Search title or number" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} aria-label="Search documents" />
        <select className="toolbar-input" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Filter by status">
          <option value="">All statuses</option>
          <option value="AWAITING_REVIEW">Awaiting review</option>
          <option value="VERIFICATION_REQUIRED">Verification required</option>
          <option value="VERIFIED">Verified</option>
          <option value="DUPLICATE_REVIEW">Duplicate review</option>
          <option value="FAILED">Failed</option>
        </select>
      </Toolbar>
      {docs.length === 0 ? (
        <EmptyState message="No documents match your filters." />
      ) : (
        <TableWrap>
          <table className="data-table">
            <thead>
              <tr><th>Document</th><th>Faculty</th><th>Type</th><th>Uploaded</th><th>Processing</th><th>Verification</th><th>Flags</th></tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={String(d.id)}>
                  <td>
                    <strong>{display(d.title || d.patent_number || d.design_number || d.id)}</strong>
                    <div className="muted">{display(d.id)}</div>
                  </td>
                  <td>{display(d.faculty_name)}<div className="muted">{display(d.faculty_id)}</div></td>
                  <td>{display(d.ip_type)}</td>
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
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
      <Pagination page={page} totalPages={data?.total_pages ?? 1} onChange={setPage} disabled={isFetching} />
    </SectionCard>
  );
}

/* -------------------------------- Duplicates ------------------------------- */

export function HodDuplicatesPage() {
  const client = useQueryClient();
  const { notify } = useToast();
  const [confirmCase, setConfirmCase] = useState<Record<string, unknown> | null>(null);
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

  if (isLoading) return <LoadingBlock label="Loading duplicates…" />;
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
                  <td><Link className="link" to={`/faculty/records/${d.ip_record_id_1}`}>{String(d.ip_record_id_1).slice(0, 8)}…</Link></td>
                  <td><Link className="link" to={`/faculty/records/${d.ip_record_id_2}`}>{String(d.ip_record_id_2).slice(0, 8)}…</Link></td>
                  <td>{d.confidence != null ? `${Math.round(Number(d.confidence) * 100)}%` : '—'}</td>
                  <td>{display(d.detection_method)}</td>
                  <td>{display(d.detected_by)}</td>
                  <td>{formatDate(d.detected_at)}</td>
                  <td><StatusBadge value={String(d.status || 'OPEN')} /></td>
                  <td>
                    {String(d.status) === 'OPEN'
                      ? <button className="btn btn-sm btn-primary" disabled={resolve.isPending} onClick={() => setConfirmCase(d)}>Resolve</button>
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

  if (isLoading) return <LoadingBlock label="Loading conflicts…" />;
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
                  <td><Link className="link" to={`/faculty/records/${c.ip_record_id}`}>{String(c.ip_record_id).slice(0, 8)}…</Link></td>
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

  if (isLoading) return <LoadingBlock label="Loading department report…" />;
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
  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ['hod-audit', page],
    queryFn: () => api.hodAudit(`?page=${page}&per_page=25`),
  });

  if (isLoading) return <LoadingBlock label="Loading department audit…" />;
  if (error) return <ErrorBlock error={error} />;

  const rows = data?.audit_entries ?? [];

  return (
    <SectionCard title="Department Audit" subtitle={`${data?.total ?? 0} recorded actions for your department.`}>
      {rows.length === 0 ? (
        <EmptyState message="No audit activity for your department yet." />
      ) : (
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
      )}
      <Pagination page={page} totalPages={data?.total_pages ?? 1} onChange={setPage} disabled={isFetching} />
    </SectionCard>
  );
}

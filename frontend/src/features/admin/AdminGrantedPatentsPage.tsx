import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { keepPreviousData, useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import {
  SectionCard, StatusBadge, ErrorBlock, EmptyState,
  Toolbar, TableWrap, Pagination, formatDate, display, downloadFile,
} from '../../components/ui';
import { useToast } from '../../stores/toast';
import { useDebounce } from '../../hooks/useDebounce';

const GRANTABLE_IP_TYPES = new Set(['PATENT', 'DESIGN_REGISTRATION']);
const IP_TYPE_LABELS: Record<string, string> = {
  PATENT: 'Patent',
  DESIGN_REGISTRATION: 'Design Registration',
};

export function AdminGrantedPatentsPage() {
  const navigate = useNavigate();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 400);
  const [verification, setVerification] = useState('');
  const [exporting, setExporting] = useState(false);
  const [exportFormat, setExportFormat] = useState<'csv' | 'excel' | 'pdf' | 'docx' | 'txt'>('csv');
  const [grantConfirmId, setGrantConfirmId] = useState<string | null>(null);

  const grantMut = useMutation({
    mutationFn: (recordId: string) => api.adminGrantPatent(recordId),
    onSuccess: (_data, recordId) => {
      notify('success', 'Patent granted successfully');
      setGrantConfirmId(null);
      void queryClient.invalidateQueries({ queryKey: ['admin-granted-patents'] });
      void queryClient.invalidateQueries({ queryKey: ['admin-records'] });
    },
    onError: (e) => notify('error', e instanceof Error ? e.message : 'Grant failed'),
  });

  const runExport = async () => {
    setExporting(true);
    try {
      const filters: Record<string, unknown> = {};
      if (debouncedSearch.trim()) filters.search = debouncedSearch.trim();
      // GRANTED is a workflow_state, not a verification_status (the backend
      // verification_status column is a PG enum without GRANTED).
      if (verification === 'GRANTED') filters.workflow_state = 'GRANTED';
      else if (verification) filters.verification_status = verification;
      const job = await api.createExport(exportFormat as any, filters);
      const extMap: Record<string, string> = { csv: 'csv', excel: 'xlsx', pdf: 'pdf', docx: 'docx', txt: 'txt' };
      await downloadFile(api.exportDownloadUrl(job.job_id), `granted-ip-${job.job_id}.${extMap[exportFormat] ?? exportFormat}`);
      notify('success', `${exportFormat.toUpperCase()} export downloaded`);
    } catch (e) {
      notify('error', e instanceof Error ? e.message : 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  const params = useMemo(() => {
    const q = new URLSearchParams({ page: String(page), per_page: '20' });
    // GRANTED lives on workflow_state (string column); sending it as
    // verification_status hits the PG enum and returns INTERNAL_ERROR.
    if (verification === 'GRANTED') q.set('workflow_state', 'GRANTED');
    else if (verification) q.set('verification_status', verification);
    if (debouncedSearch.trim()) q.set('search', debouncedSearch.trim());
    return `?${q.toString()}`;
  }, [page, verification, debouncedSearch]);

  const { data, isLoading, error, isFetching, refetch } = useQuery({ queryKey: ['admin-granted-patents', params], queryFn: ({ signal }) => api.adminRecords(params, signal), placeholderData: keepPreviousData });

  const all = data?.records ?? [];
  const rows = all.filter((r) => GRANTABLE_IP_TYPES.has(String(r.ip_type ?? '')));
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.per_page)) : 1;

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading grant records…</span></div>;
  if (error && !data) return <ErrorBlock error={error} />;

  return (
    <SectionCard
      title="Grant IP"
      subtitle={`${data?.total ?? 0} IP records (patents and design registrations). OCR extracts titles, inventors, dates and numbers automatically.`}
      actions={
        <>
          <select className="toolbar-input" value={exportFormat} onChange={(e) => setExportFormat(e.target.value as any)} aria-label="Export format" style={{ width: 110 }}>
            <option value="csv">CSV</option>
            <option value="excel">Excel</option>
            <option value="pdf">PDF</option>
            <option value="docx">Word</option>
            <option value="txt">Text</option>
          </select>
          <button className="btn btn-sm btn-secondary" disabled={exporting} onClick={runExport}>{exporting ? 'Exporting…' : `Export ${exportFormat.toUpperCase()}`}</button>
          <button className="btn btn-sm btn-primary" onClick={() => navigate('/admin/patent-upload')}>Add IP record</button>
        </>
      }
    >
      <Toolbar>
        <input className="toolbar-input" placeholder="Search title, number, inventor" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} aria-label="Search IP records" />
        <select className="toolbar-input" value={verification} onChange={(e) => { setVerification(e.target.value); setPage(1); }} aria-label="Verification filter">
          <option value="">All verification states</option>
          <option value="VERIFIED">Verified</option>
          <option value="GRANTED">Granted</option>
          <option value="VERIFICATION_REQUIRED">Verification required</option>
          <option value="UNVERIFIED">Unverified</option>
          <option value="MISMATCH">Mismatch</option>
        </select>
      </Toolbar>

      {error && data ? (
        <div className="alert alert-error" role="alert" style={{ marginBottom: 12 }}>
          Refresh failed: {error instanceof Error ? error.message : String(error)}{' '}
          <button className="btn btn-sm btn-secondary" onClick={() => void refetch()} disabled={isFetching}>Retry</button>
        </div>
      ) : null}

      {grantConfirmId && (
        <div className="modal-overlay" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div style={{ background: '#fff', borderRadius: 8, padding: 24, maxWidth: 420, width: '90%' }}>
            <h3 style={{ marginTop: 0 }}>Confirm Grant Patent</h3>
            <p>Are you sure you want to mark this patent as Granted?</p>
            <p style={{ fontSize: 13, color: '#6b7280' }}>This action cannot be reversed.</p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
              <button className="btn btn-ghost btn-sm" onClick={() => setGrantConfirmId(null)} disabled={grantMut.isPending}>Cancel</button>
              <button className="btn btn-primary btn-sm" onClick={() => grantMut.mutate(grantConfirmId)} disabled={grantMut.isPending}>{grantMut.isPending ? 'Granting…' : 'Confirm Grant'}</button>
            </div>
          </div>
        </div>
      )}

      {rows.length === 0 && !isFetching ? (
        <EmptyState message="No grant-eligible IP records match your filters." action={<button className="btn btn-primary" onClick={() => navigate('/admin/patent-upload')}>Add the first IP record</button>} />
      ) : (
        <div className={isFetching && data ? 'table-fetching' : ''}>
          {isFetching && data ? <div className="table-fetching-indicator"><span className="spinner" /> Updating…</div> : null}
          <TableWrap>
          <table className="data-table">
            <thead>
              <tr><th>IP Type</th><th>Number / ID</th><th>Title</th><th>Inventor(s)</th><th>Applicant</th><th>Grant Date</th><th>Processing</th><th>Verification</th><th>Workflow</th><th></th></tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const isVerified = String(r.verification_status || '') === 'VERIFIED' && String(r.workflow_state || '') !== 'GRANTED';
                const isGranted = String(r.workflow_state || '') === 'GRANTED';
                return (
                  <tr key={String(r.id)}>
                    <td>{IP_TYPE_LABELS[String(r.ip_type ?? '')] ?? display(r.ip_type)}</td>
                    <td><strong>{display(r.patent_number || r.application_number || r.design_number || r.serial_number)}</strong></td>
                    <td>{display(r.title)}</td>
                    <td>{display(r.contributor_name)}</td>
                    <td>{display(r.applicant || r.patentee)}</td>
                    <td>{r.grant_date ? formatDate(r.grant_date) : '—'}</td>
                    <td><StatusBadge value={String(r.processing_status || 'UNKNOWN')} /></td>
                    <td><StatusBadge value={String(r.verification_status || 'UNKNOWN')} /></td>
                    <td><StatusBadge value={isGranted ? 'GRANTED' : String(r.workflow_state || '—')} /></td>
                    <td>
                      {isGranted ? (
                        <span style={{ color: '#059669', fontWeight: 600, fontSize: 13 }}>Granted</span>
                      ) : isVerified ? (
                        <button className="btn btn-sm btn-primary" onClick={() => setGrantConfirmId(String(r.id))}>Grant Patent</button>
                      ) : (
                        <Link className="link" to={`/faculty/records/${r.id}`}>Open</Link>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
        </div>
      )}
      <Pagination page={page} totalPages={totalPages} onChange={setPage} disabled={isFetching} />
    </SectionCard>
  );
}

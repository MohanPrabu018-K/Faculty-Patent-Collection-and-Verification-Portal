import { useMemo, useState } from 'react';
import { keepPreviousData, useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '../../api/client';
import { SectionCard, StatusBadge, downloadFile, Pagination } from '../../components/ui';
import { useToast } from '../../stores/toast';
import { useDebounce } from '../../hooks/useDebounce';

function readable(value: unknown) {
  if (value === null || value === undefined || value === '') return 'Not available';
  return String(value);
}

function friendlyError(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof TypeError && err.message === 'Failed to fetch') return 'Unable to connect to the server. Please check your network connection and try again.';
  return String(err || 'An unexpected error occurred');
}

export function AdminRecordsPage() {
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 400);
  const [status, setStatus] = useState('');
  const [ipType, setIpType] = useState('');
  const [processStatus, setProcessStatus] = useState('');
  const [workflow, setWorkflow] = useState('');
  const [isArchived, setIsArchived] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [exportFormat, setExportFormat] = useState<'csv' | 'excel' | 'pdf' | 'docx' | 'txt'>('csv');
  const [showFieldSelect, setShowFieldSelect] = useState(false);
  const allExportFields = ['title', 'patent_number', 'design_number', 'application_number', 'grant_date', 'filing_date', 'applicant', 'patentee', 'faculty_name', 'faculty_id', 'department', 'designation', 'ip_type', 'verification_status', 'processing_status', 'workflow_state', 'created_at'];
  const [selectedFields, setSelectedFields] = useState<string[]>([...allExportFields]);

  const toggleField = (field: string) => {
    setSelectedFields(prev => prev.includes(field) ? prev.filter(f => f !== field) : [...prev, field]);
  };

  const runExport = async (fmtOverride?: string) => {
    const fmt = (fmtOverride as any) || exportFormat;
    if (selectedFields.length === 0) { notify('error', 'Select at least one field to export'); return; }
    setExporting(true);
    try {
      const filters: Record<string, unknown> = {};
      if (debouncedSearch.trim()) filters.search = debouncedSearch.trim();
      if (status) filters.verification_status = status;
      if (ipType) filters.ip_type = ipType;
      if (processStatus) filters.processing_status = processStatus;
      if (workflow) filters.workflow_state = workflow;
      if (isArchived !== '') filters.is_archived = isArchived;
      if (dateFrom) filters.date_from = dateFrom;
      if (dateTo) filters.date_to = dateTo;
      const job = await api.createExport(fmt as any, Object.keys(filters).length ? filters : undefined, selectedFields.length < allExportFields.length ? selectedFields : undefined);
      const extMap: Record<string, string> = { csv: 'csv', excel: 'xlsx', pdf: 'pdf', docx: 'docx', txt: 'txt' };
      await downloadFile(api.exportDownloadUrl(job.job_id), `ip-records-${job.job_id}.${extMap[fmt] ?? fmt}`);
      notify('success', `${fmt.toUpperCase()} export downloaded`);
    } catch (e) {
      notify('error', e instanceof Error ? e.message : 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  const params = useMemo(() => {
    const query = new URLSearchParams({ page: String(page), per_page: '20' });
    if (debouncedSearch.trim()) query.set('search', debouncedSearch.trim());
    if (status) query.set('verification_status', status);
    if (ipType) query.set('ip_type', ipType);
    if (processStatus) query.set('processing_status', processStatus);
    if (workflow) query.set('workflow_state', workflow);
    if (isArchived !== '') query.set('is_archived', isArchived);
    if (dateFrom) query.set('date_from', dateFrom);
    if (dateTo) query.set('date_to', dateTo);
    return `?${query.toString()}`;
  }, [page, debouncedSearch, status, ipType, processStatus, workflow, isArchived, dateFrom, dateTo]);

  const { data, isLoading, error, refetch, isFetching } = useQuery({ queryKey: ['admin-records', params], queryFn: ({ signal }) => api.adminRecords(params, signal), placeholderData: keepPreviousData });
  const records = (data as { records?: Array<Record<string, unknown>> })?.records ?? [];
  // Server-side search (debounced) — backend now handles title/numbers/faculty/applicant. No client filtering.
  const filtered = records;
  const selected = filtered.find((record) => String(record.id) === selectedId) ?? filtered[0];
  const detail = useQuery({ queryKey: ['admin-record-detail', selected?.id], queryFn: () => api.adminRecordDetail(String(selected?.id)), enabled: Boolean(selected?.id) });

  const archiveMut = useMutation({
    mutationFn: ({ recordId, archived }: { recordId: string; archived: boolean }) => api.adminUpdateRecord(recordId, { is_archived: archived }),
    onMutate: async ({ recordId, archived }) => {
      await queryClient.cancelQueries({ queryKey: ['admin-records'] });
      const prev = queryClient.getQueryData(['admin-records', params]);
      queryClient.setQueryData(['admin-records', params], (old: Record<string, unknown> | undefined) => {
        if (!old) return old;
        return { ...old, records: ((old.records ?? []) as Record<string, unknown>[]).map((r: Record<string, unknown>) => r.id === recordId ? { ...r, is_archived: archived } : r) };
      });
      return { prev };
    },
    onSuccess: (_data, vars) => {
      notify('success', vars.archived ? 'Record archived' : 'Record unarchived');
      void queryClient.invalidateQueries({ queryKey: ['admin-records'] });
      void detail.refetch();
    },
    onError: (_e, _vars, context) => {
      if (context?.prev) queryClient.setQueryData(['admin-records', params], context.prev);
      notify('error', 'Archive action failed');
    },
  });

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading IP records…</span></div>;
  if (error && !data) return <div className="alert alert-error">{friendlyError(error)}</div>;

  return (
    <div className="stack-lg">
      <SectionCard
        title="IP Records"
        subtitle="Search, filter, and inspect records from the backend. Debounced search (400ms)."
        actions={
          <div className="btn-row" style={{ flexWrap: 'wrap', gap: 6 }}>
            <button className="btn btn-sm btn-ghost" onClick={() => setShowFieldSelect(v => !v)}>{showFieldSelect ? 'Hide Fields' : 'Select Fields'}</button>
            <select className="toolbar-input" value={exportFormat} onChange={(e) => setExportFormat(e.target.value as any)} aria-label="Export format" style={{ width: 110 }}>
              <option value="csv">CSV</option>
              <option value="excel">Excel</option>
              <option value="pdf">PDF</option>
              <option value="docx">Word</option>
              <option value="txt">Text</option>
            </select>
            <button className="btn btn-sm btn-secondary" disabled={exporting} onClick={() => runExport()}>{exporting ? 'Exporting…' : `Export ${exportFormat.toUpperCase()}`}</button>
          </div>
        }
      >
        <div className="toolbar">
          <input className="toolbar-input" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Search by title, number, type, or status" aria-label="Search records" />
          <select className="toolbar-input" value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }} aria-label="Filter by verification status">
            <option value="">All verification statuses</option>
            <option value="UNVERIFIED">Unverified</option>
            <option value="VERIFICATION_REQUIRED">Verification required</option>
            <option value="VERIFIED">Verified</option>
            <option value="MISMATCH">Mismatch</option>
          </select>
          <select className="toolbar-input" value={ipType} onChange={(event) => { setIpType(event.target.value); setPage(1); }} aria-label="Filter by IP type">
            <option value="">All IP types</option>
            <option value="PATENT">Patent</option>
            <option value="DESIGN_REGISTRATION">Design</option>
            <option value="UNKNOWN_OTHER">Other</option>
          </select>
          <select className="toolbar-input" value={processStatus} onChange={(event) => { setProcessStatus(event.target.value); setPage(1); }} aria-label="Filter by processing status">
            <option value="">All processing statuses</option>
            <option value="QUEUED">Queued</option>
            <option value="PROCESSING">Processing</option>
            <option value="AWAITING_REVIEW">Awaiting review</option>
            <option value="COMPLETED">Completed</option>
            <option value="COMPLETED_WITH_ERRORS">Completed with errors</option>
            <option value="FAILED">Failed</option>
          </select>
          <select className="toolbar-input" value={workflow} onChange={(event) => { setWorkflow(event.target.value); setPage(1); }} aria-label="Filter by workflow state">
            <option value="">All workflow states</option>
            <option value="UPLOADED">Uploaded</option>
            <option value="PROCESSING">Processing</option>
            <option value="IDENTIFIER_FOUND">Identifier found</option>
            <option value="VERIFICATION_PENDING">Verification pending</option>
            <option value="VERIFICATION_REQUIRED">Verification required</option>
            <option value="NEEDS_REVIEW">Needs review</option>
            <option value="FACULTY_APPROVAL_PENDING">Faculty approval pending</option>
            <option value="DUPLICATE_REVIEW">Duplicate review</option>
            <option value="DATA_CONFLICT">Data conflict</option>
            <option value="VERIFIED">Verified</option>
            <option value="REJECTED">Rejected</option>
            <option value="FAILED">Failed</option>
          </select>
          <select className="toolbar-input" value={isArchived} onChange={(event) => { setIsArchived(event.target.value); setPage(1); }} aria-label="Filter by archive status">
            <option value="">All archive statuses</option>
            <option value="false">Active records</option>
            <option value="true">Archived records</option>
          </select>
          <input className="toolbar-input" type="date" value={dateFrom} onChange={(event) => { setDateFrom(event.target.value); setPage(1); }} aria-label="Created from" />
          <input className="toolbar-input" type="date" value={dateTo} onChange={(event) => { setDateTo(event.target.value); setPage(1); }} aria-label="Created to" />
        </div>
        {showFieldSelect && (
          <div style={{ padding: '8px 12px', background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 6, marginBottom: 12 }}>
            <div style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
              <button className="btn btn-sm btn-ghost" onClick={() => setSelectedFields([...allExportFields])}>Select All</button>
              <button className="btn btn-sm btn-ghost" onClick={() => setSelectedFields([])}>Clear All</button>
              <span className="muted" style={{ fontSize: 12, alignSelf: 'center' }}>{selectedFields.length} of {allExportFields.length} fields selected</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px' }}>
              {allExportFields.map(f => (
                <label key={f} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, cursor: 'pointer' }}>
                  <input type="checkbox" checked={selectedFields.includes(f)} onChange={() => toggleField(f)} />
                  {f.replace(/_/g, ' ')}
                </label>
              ))}
            </div>
          </div>
        )}
        {error && data ? (
          <div className="alert alert-error" role="alert" style={{ marginBottom: 12 }}>
            Refresh failed: {friendlyError(error)}{' '}
            <button className="btn btn-sm btn-secondary" onClick={() => void refetch()} disabled={isFetching}>Retry</button>
          </div>
        ) : null}
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
          <div className="muted">{isFetching ? 'Searching…' : `${(data as any)?.total ?? filtered.length} total · ${filtered.length} on page`}{debouncedSearch !== search ? ' (typing…)' : ''}</div>
          <button className="btn btn-secondary" onClick={() => { setSearch(''); setStatus(''); setIpType(''); setProcessStatus(''); setWorkflow(''); setIsArchived(''); setDateFrom(''); setDateTo(''); setSelectedId(''); setPage(1); void refetch(); }} disabled={isFetching}>Clear filters</button>
        </div>
        <div className="admin-record-layout">
          <div className={isFetching && data ? 'table-wrap table-fetching' : 'table-wrap'}>
            {isFetching && data && <div className="table-fetching-indicator"><span className="spinner" /> Updating…</div>}
            <table className="data-table">
              <thead><tr><th>Record</th><th>Faculty</th><th>Document type</th><th>Processing</th><th>Verification</th><th>Updated</th></tr></thead>
              <tbody>
                {filtered.length === 0 ? <tr><td colSpan={6} className="empty-cell">No records match the current filters.</td></tr> : filtered.map((record) => {
                  const identifier = (record.design_number as string) || (record.patent_number as string) || (record.application_number as string) || '';
                  const primary = (record.title as string) || identifier || String(record.id);
                  const showIdentifier = Boolean(identifier) && identifier !== primary;
                  return (
                    <tr key={String(record.id)} onClick={() => setSelectedId(String(record.id))} className={selectedId === String(record.id) ? 'row-selected' : ''} style={{ cursor: 'pointer' }}>
                      <td>
                        <div>
                          <strong className="link">{readable(primary)}</strong>
                          {showIdentifier ? <div className="muted">{readable(identifier)}</div> : null}
                        </div>
                      </td>
                      <td>{readable(record.faculty_name || record.uploader_name || record.uploader_id)}</td>
                      <td>{readable(record.ip_type)}</td>
                      <td><StatusBadge value={String(record.processing_status || 'UNKNOWN')} /></td>
                      <td><StatusBadge value={String(record.verification_status || 'UNKNOWN')} /></td>
                      <td>{readable(record.updated_at || record.created_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="compact-card admin-detail-panel">
            <div className="section-head"><h2>Record details</h2><p>Selected record information from the backend.</p></div>
            {detail.isLoading ? <div className="loading-inline"><span className="spinner" /><span>Loading details…</span></div> : detail.error ? <div className="alert alert-error">{String(detail.error)}</div> : selected ? <div className="stack">
              <div className="detail-field"><span>Title</span><strong>{readable((detail.data as Record<string, unknown>)?.title || selected.title)}</strong></div>
              {/* Bug 5: document identifiers, not the raw database UUID. */}
              <div className="detail-field"><span>Document number</span><strong>{readable((detail.data as Record<string, unknown>)?.design_number || (detail.data as Record<string, unknown>)?.patent_number || (detail.data as Record<string, unknown>)?.application_number || (detail.data as Record<string, unknown>)?.serial_number || selected.design_number || selected.patent_number || selected.application_number || 'Not available')}</strong></div>
              <div className="detail-field"><span>Faculty</span><strong>{readable(selected.faculty_name || selected.uploader_name || selected.uploader_id)}</strong></div>
              <div className="detail-field"><span>Document type</span><strong>{readable(selected.ip_type)}</strong></div>
              <div className="detail-field"><span>Processing status</span><strong><StatusBadge value={String((detail.data as Record<string, unknown>)?.processing_status || selected.processing_status || 'UNKNOWN')} /></strong></div>
              <div className="detail-field"><span>Verification status</span><strong><StatusBadge value={String((detail.data as Record<string, unknown>)?.verification_status || selected.verification_status || 'UNKNOWN')} /></strong></div>
              <div className="detail-field"><span>Archived</span><strong>{selected.is_archived ? 'Yes — hidden from active views' : 'No'}</strong></div>
              <div className="detail-field"><span>Created</span><strong>{readable(selected.created_at)}</strong></div>
              <div className="detail-field"><span>Updated</span><strong>{readable(selected.updated_at)}</strong></div>
              <button className="btn btn-sm btn-secondary" disabled={archiveMut.isPending} onClick={() => archiveMut.mutate({ recordId: String(selected.id), archived: !selected.is_archived })}>
                {archiveMut.isPending ? 'Saving…' : selected.is_archived ? 'Unarchive record' : 'Archive record'}
              </button>
            </div> : <div className="empty-cell">Select a record to inspect details.</div>}
          </div>
        </div>
        <Pagination page={page} totalPages={Math.max(1, Math.ceil(((data as any)?.total ?? 0) / ((data as any)?.per_page ?? 20)))} onChange={setPage} disabled={isFetching} />
      </SectionCard>
    </div>
  );
}
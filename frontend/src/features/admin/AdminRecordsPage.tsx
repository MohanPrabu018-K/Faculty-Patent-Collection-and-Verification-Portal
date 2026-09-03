import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { SectionCard, StatusBadge, downloadFile } from '../../components/ui';
import { useToast } from '../../stores/toast';

function readable(value: unknown) {
  if (value === null || value === undefined || value === '') return 'Not available';
  return String(value);
}

export function AdminRecordsPage() {
  const { notify } = useToast();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [exporting, setExporting] = useState(false);

  const runExport = async () => {
    setExporting(true);
    try {
      const job = await api.createExport('csv');
      await downloadFile(api.exportDownloadUrl(job.job_id), `ip-records-${job.job_id}.csv`);
      notify('success', 'CSV export downloaded');
    } catch (e) {
      notify('error', e instanceof Error ? e.message : 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  const params = useMemo(() => {
    const query = new URLSearchParams();
    if (status) query.set('verification_status', status);
    return query.toString() ? `?${query.toString()}` : '';
  }, [status]);

  const { data, isLoading, error, refetch, isFetching } = useQuery({ queryKey: ['admin-records', params], queryFn: () => api.adminRecords(params) });
  const records = (data as { records?: Array<Record<string, unknown>> })?.records ?? [];
  const filtered = records.filter((record) => {
    const haystack = [record.title, record.patent_number, record.design_number, record.application_number, record.ip_type, record.processing_status, record.verification_status].map(readable).join(' ').toLowerCase();
    return !search || haystack.includes(search.toLowerCase());
  });
  const selected = filtered.find((record) => String(record.id) === selectedId) ?? filtered[0];
  const detail = useQuery({ queryKey: ['admin-record-detail', selected?.id], queryFn: () => api.adminRecordDetail(String(selected?.id)), enabled: Boolean(selected?.id) });

  if (isLoading) return <div className="page-center">Loading IP records...</div>;
  if (error) return <div className="alert alert-error">{String(error)}</div>;

  return (
    <div className="stack-lg">
      <SectionCard
        title="IP Records"
        subtitle="Search, filter, and inspect records from the backend."
        actions={<button className="btn btn-sm btn-secondary" disabled={exporting} onClick={runExport}>{exporting ? 'Exporting…' : 'Export CSV'}</button>}
      >
        <div className="toolbar">
          <input className="toolbar-input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by title, number, type, or status" aria-label="Search records" />
          <select className="toolbar-input" value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Filter by verification status">
            <option value="">All verification statuses</option>
            <option value="UNVERIFIED">Unverified</option>
            <option value="VERIFICATION_REQUIRED">Verification required</option>
            <option value="VERIFIED">Verified</option>
            <option value="REJECTED">Rejected</option>
          </select>
        </div>
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
          <div className="muted">{filtered.length} record{filtered.length === 1 ? '' : 's'} shown{status ? ` ? filtered by ${status}` : ''}</div>
          <button className="btn btn-secondary" onClick={() => { setSearch(''); setStatus(''); setSelectedId(''); void refetch(); }} disabled={isFetching}>Clear filters</button>
        </div>
        <div className="admin-record-layout">
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Record</th><th>Faculty</th><th>Document type</th><th>Processing</th><th>Verification</th><th>Updated</th></tr></thead>
              <tbody>
                {filtered.length === 0 ? <tr><td colSpan={6} className="empty-cell">No records match the current filters.</td></tr> : filtered.map((record) => <tr key={String(record.id)} onClick={() => setSelectedId(String(record.id))} className={selectedId === String(record.id) ? 'row-selected' : ''} style={{ cursor: 'pointer' }}><td><div><strong className="link">{readable(record.title || record.patent_number || record.design_number || record.application_number || record.id)}</strong><div className="muted">{readable(record.id)}</div></div></td><td>{readable(record.faculty_name || record.uploader_name || record.uploader_id)}</td><td>{readable(record.ip_type)}</td><td><StatusBadge value={String(record.processing_status || 'UNKNOWN')} /></td><td><StatusBadge value={String(record.verification_status || 'UNKNOWN')} /></td><td>{readable(record.updated_at || record.created_at)}</td></tr>)}
              </tbody>
            </table>
          </div>
          <div className="compact-card admin-detail-panel">
            <div className="section-head"><h2>Record details</h2><p>Selected record information from the backend.</p></div>
            {detail.isLoading ? <div className="page-center">Loading details...</div> : detail.error ? <div className="alert alert-error">{String(detail.error)}</div> : selected ? <div className="stack">
              <div className="detail-field"><span>Title</span><strong>{readable((detail.data as Record<string, unknown>)?.title || selected.title)}</strong></div>
              <div className="detail-field"><span>Record ID</span><strong>{readable((detail.data as Record<string, unknown>)?.id || selected.id)}</strong></div>
              <div className="detail-field"><span>Faculty</span><strong>{readable(selected.faculty_name || selected.uploader_name || selected.uploader_id)}</strong></div>
              <div className="detail-field"><span>Document type</span><strong>{readable(selected.ip_type)}</strong></div>
              <div className="detail-field"><span>Processing status</span><strong><StatusBadge value={String((detail.data as Record<string, unknown>)?.processing_status || selected.processing_status || 'UNKNOWN')} /></strong></div>
              <div className="detail-field"><span>Verification status</span><strong><StatusBadge value={String((detail.data as Record<string, unknown>)?.verification_status || selected.verification_status || 'UNKNOWN')} /></strong></div>
              <div className="detail-field"><span>Created</span><strong>{readable(selected.created_at)}</strong></div>
              <div className="detail-field"><span>Updated</span><strong>{readable(selected.updated_at)}</strong></div>
            </div> : <div className="empty-cell">Select a record to inspect details.</div>}
          </div>
        </div>
      </SectionCard>
    </div>
  );
}

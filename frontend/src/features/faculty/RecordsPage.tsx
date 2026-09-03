import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { SectionCard, StatusBadge } from '../../components/ui';

export function RecordsPage() {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const { data, isLoading, error } = useQuery({ queryKey: ['faculty-records'], queryFn: () => api.facultyRecords('') });
  const records = data?.records ?? [];
  const filtered = useMemo(() => records.filter((row: any) => {
    const haystack = `${row.title || ''} ${row.patent_number || ''} ${row.design_number || ''} ${row.ip_type || ''}`.toLowerCase();
    return (!search || haystack.includes(search.toLowerCase())) && (!statusFilter || String(row.processing_status || '') === statusFilter);
  }), [records, search, statusFilter]);

  if (isLoading) return <div className="page-center">Loading records...</div>;
  if (error) return <div className="alert alert-error">{String(error)}</div>;
  return (
    <SectionCard title="My Records" subtitle="Search and filter your submissions.">
      <div className="toolbar">
        <input aria-label="Search records" className="toolbar-input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by title, number, type" />
        <select aria-label="Filter by processing status" className="toolbar-input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          <option value="QUEUED">Queued</option>
          <option value="PROCESSING">Processing</option>
          <option value="AWAITING_REVIEW">Awaiting review</option>
          <option value="COMPLETED">Completed</option>
          <option value="FAILED">Failed</option>
        </select>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Title / Document</th><th>IP Type</th><th>Processing</th><th>Verification</th><th>Actions</th></tr></thead>
          <tbody>
            {filtered.length === 0 ? <tr><td colSpan={5} className="empty-cell">No records match your filters</td></tr> : filtered.map((row: any) => <tr key={row.id}><td><Link className="link" to={`/faculty/records/${row.id}`}>{row.title || row.patent_number || row.design_number || row.id}</Link></td><td>{row.ip_type}</td><td><StatusBadge value={String(row.processing_status || 'UNKNOWN')} /></td><td><StatusBadge value={String(row.verification_status || 'UNKNOWN')} /></td><td><Link className="link" to={`/faculty/records/${row.id}`}>View details</Link></td></tr>)}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { SectionCard, StatusBadge } from '../../components/ui';

const FAILED_STATUSES = new Set(['FAILED', 'COMPLETED_WITH_ERRORS']);

function FailureDetails({ record }: { record: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);
  const isFailed = FAILED_STATUSES.has(String(record.processing_status || ''));
  const jobs = (record.jobs ?? []) as Array<Record<string, unknown>>;
  const failedJobs = jobs.filter(j => String(j.status) === 'FAILED' || j.error_message) ?? [];

  if (!isFailed && failedJobs.length === 0) return null;

  const workflowState = String(record.workflow_state || '');
  const evidence = record.evidence as Record<string, unknown> | undefined;
  const finalVerification = evidence?.final_verification as Record<string, unknown> | undefined;
  const missingConditions = finalVerification?.missing_conditions as string[] | undefined;

  return (
    <div style={{ marginTop: 8 }}>
      <button className="btn btn-ghost btn-sm" onClick={() => setExpanded(v => !v)}>
        {expanded ? 'Hide' : 'Show'} Failure Details
      </button>
      {expanded && (
        <div className="section-card compact-card" style={{ marginTop: 8, background: '#fef2f2', border: '1px solid #fecaca' }}>
          <div className="stack" style={{ gap: 8 }}>
            {String(record.processing_status || '') && (
              <div className="detail-field"><span>Processing Status</span><strong>{String(record.processing_status)}</strong></div>
            )}
            {workflowState && (
              <div className="detail-field"><span>Workflow State</span><strong>{workflowState.replace(/_/g, ' ')}</strong></div>
            )}
            {failedJobs.map((job, i) => (
              <div key={i} style={{ padding: '8px 0', borderTop: i > 0 ? '1px solid #fecaca' : 'none' }}>
                <div className="detail-field"><span>Failed Stage</span><strong>{String(job.job_type || 'Unknown')}</strong></div>
                {String(job.error_message || '') && (
                  <div className="detail-field"><span>Error</span><strong style={{ color: '#991b1b' }}>{String(job.error_message)}</strong></div>
                )}
                {String(job.completed_at || '') && (
                  <div className="detail-field"><span>Failed At</span><strong>{String(job.completed_at)}</strong></div>
                )}
              </div>
            ))}
            {missingConditions && missingConditions.length > 0 && (
              <div style={{ marginTop: 4 }}>
                <div className="detail-field"><span>Verification Blocked By</span></div>
                <ul style={{ margin: '4px 0 0 16px', fontSize: 13 }}>
                  {missingConditions.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </div>
            )}
            {!failedJobs.length && !missingConditions?.length && (
              <div className="detail-field"><span>Details</span><strong>This record requires review. Please contact your department administrator.</strong></div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function RecordsPage() {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const { data, isLoading, error } = useQuery({ queryKey: ['faculty-records'], queryFn: () => api.facultyRecords('') });
  const records = data?.records ?? [];
  const filtered = useMemo(() => records.filter((row: any) => {
    const haystack = `${row.title || ''} ${row.patent_number || ''} ${row.design_number || ''} ${row.ip_type || ''}`.toLowerCase();
    return (!search || haystack.includes(search.toLowerCase())) && (!statusFilter || String(row.processing_status || '') === statusFilter);
  }), [records, search, statusFilter]);

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading records…</span></div>;
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
            {filtered.length === 0 ? <tr><td colSpan={5} className="empty-cell">No records match your filters</td></tr> : filtered.map((row: any) => (
              <tr key={row.id}>
                <td>
                  <Link className="link" to={`/faculty/records/${row.id}`}>{row.title || row.patent_number || row.design_number || row.id}</Link>
                  <FailureDetails record={row} />
                </td>
                <td>{row.ip_type}</td>
                <td><StatusBadge value={String(row.processing_status || 'UNKNOWN')} /></td>
                <td><StatusBadge value={String(row.verification_status || 'UNKNOWN')} /></td>
                <td><Link className="link" to={`/faculty/records/${row.id}`}>View details</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}

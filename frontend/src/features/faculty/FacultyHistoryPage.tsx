import { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, type HistoryEvent } from '../../api/client';
import { SectionCard, ErrorBlock, EmptyState, Pagination, formatDateTime } from '../../components/ui';

const ACTION_LABELS: Record<string, string> = {
  UPLOAD: 'Document uploaded',
  RECORD_REVIEWED: 'Review / correction submitted',
  DUPLICATE_DETECTED: 'Possible duplicate detected',
  DUPLICATE_RESOLVED: 'Duplicate case resolved',
  CONFLICT_DETECTED: 'Data conflict detected',
  VERIFICATION_ATTEMPT: 'Verification attempted',
  ASSOCIATION_REQUEST_CREATED: 'Association request sent',
  ASSOCIATION_REQUESTED: 'Association requested',
  ASSOCIATION_REQUEST_ACCEPTED: 'Association accepted',
  ASSOCIATION_REQUEST_APPROVED: 'Association approved',
  ASSOCIATION_REQUEST_REJECTED: 'Association rejected',
  ASSOCIATION_REQUEST_NOT_ME: "Association marked 'not me'",
  ASSOCIATION_REQUEST_CLARIFICATION_REQUESTED: 'Clarification requested',
  ASSOCIATION_CLARIFICATION_PROVIDED: 'Clarification provided',
  EXCEL_IMPORT_COMPLETED: 'Imported from spreadsheet',
};

function label(action: string) {
  return ACTION_LABELS[action] || action.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (m) => m.toUpperCase());
}

export function FacultyHistoryPage() {
  const [page, setPage] = useState(1);
  const params = `?page=${page}&per_page=25`;
  const { data, isLoading, error, isFetching, refetch } = useQuery({
    queryKey: ['faculty-history', params],
    queryFn: ({ signal }) => api.facultyHistory(params, signal),
    placeholderData: keepPreviousData,
  });

  const events = data?.events ?? [];
  const totalPages = data?.total_pages ?? 1;

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading history…</span></div>;
  if (error && !data) return <ErrorBlock error={error} />;

  return (
    <SectionCard title="Activity History" subtitle="Every recorded action on your account and submissions.">
      {error && data ? (
        <div className="alert alert-error" role="alert" style={{ marginBottom: 12 }}>
          Refresh failed: {error instanceof Error ? error.message : String(error)}{' '}
          <button className="btn btn-sm btn-secondary" onClick={() => void refetch()} disabled={isFetching}>Retry</button>
        </div>
      ) : null}
      {events.length === 0 && !isFetching ? (
        <EmptyState message="No recorded activity yet." />
      ) : (
        <div className="timeline">
          {events.map((e, i) => (
            <div key={e.id} className="timeline-item">
              <div className="timeline-dot">{(page - 1) * 25 + i + 1}</div>
              <div>
                <strong>{label(e.action)}</strong>
                <div className="muted">{formatDateTime(e.created_at)}</div>
                <div className="muted timeline-badge">{describe(e)}</div>
              </div>
            </div>
          ))}
        </div>
      )}
      <Pagination page={page} totalPages={totalPages} onChange={setPage} disabled={isFetching} />
    </SectionCard>
  );
}

function describe(e: HistoryEvent): React.ReactNode {
  const parts: React.ReactNode[] = [];
  if (e.entity_type === 'ip_record' && e.entity_id) {
    parts.push(<Link key="rec" className="link" to={`/faculty/records/${e.entity_id}`}>View record</Link>);
  }
  const nv = e.new_value as Record<string, unknown> | null;
  if (nv && Array.isArray(nv.fields)) parts.push(<span key="f">Fields: {(nv.fields as string[]).join(', ')}</span>);
  else if (nv && typeof nv.filename === 'string') parts.push(<span key="fn">{nv.filename}</span>);
  else if (nv && typeof nv.status === 'string') parts.push(<span key="s">Status: {nv.status}</span>);
  if (parts.length === 0) return e.entity_type || '—';
  return parts.reduce((acc: React.ReactNode[], p, idx) => (idx === 0 ? [p] : [...acc, ' · ', p]), []);
}

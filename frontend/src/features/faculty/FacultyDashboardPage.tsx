import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { StatCard, SectionCard, StatusBadge } from '../../components/ui';

function display(value: unknown) {
  if (value === null || value === undefined || value === '') return 'Not available';
  return String(value);
}

export function FacultyDashboardPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['faculty-dashboard'], queryFn: api.facultyDashboard });

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading dashboard…</span></div>;
  if (error) return <div className="alert alert-error">{String(error)}</div>;

  const summary = data?.records_summary ?? { total: 0, pending: 0, processing: 0, completed: 0, awaiting_review: 0, failed: 0 };
  const records = data?.recent_records ?? [];

  return (
    <div className="stack-lg">
      <div className="hero-card hero-card-tight">
        <div>
          <div className="eyebrow">Dashboard</div>
          <h2>Faculty submission overview</h2>
          <p>Live counts and recent submissions from the backend.</p>
        </div>
        <div className="quick-actions">
          <Link className="btn btn-primary" to="/faculty/upload">Upload document</Link>
          <Link className="btn btn-secondary" to="/faculty/records">My records</Link>
        </div>
      </div>
      <SectionCard title="Summary">
        <div className="grid stats-grid">
          <StatCard label="Total submissions" value={summary.total} />
          <StatCard label="Pending" value={summary.pending} />
          <StatCard label="Processing" value={summary.processing} />
          <StatCard label="Awaiting review" value={summary.awaiting_review} />
          <StatCard label="Verified" value={summary.completed} />
          <StatCard label="Failed" value={summary.failed} />
        </div>
      </SectionCard>
      <SectionCard title="Recent submissions" subtitle="Click any row to open the full detail view.">
        {records.length === 0 ? <div className="empty-cell">No submissions have been uploaded yet.</div> : <div className="table-wrap"><table className="data-table"><thead><tr><th>Record</th><th>Type</th><th>Processing</th><th>Verification</th><th>Created</th></tr></thead><tbody>{records.map((row: any) => <tr key={row.id}><td><Link className="link" to={`/faculty/records/${row.id}`}>{row.title || row.patent_number || row.design_number || row.id}</Link></td><td>{display(row.ip_type)}</td><td><StatusBadge value={String(row.processing_status || 'UNKNOWN')} /></td><td><StatusBadge value={String(row.verification_status || 'UNKNOWN')} /></td><td>{display(row.created_at)}</td></tr>)}</tbody></table></div>}
      </SectionCard>
    </div>
  );
}

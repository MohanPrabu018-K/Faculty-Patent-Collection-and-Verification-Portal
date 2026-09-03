import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { SectionCard, StatusBadge } from '../../components/ui';

function display(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Not available';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function AdminMasterRecordsPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['admin-master-records'], queryFn: () => api.adminMasterRecords() });

  if (isLoading) return <div className="page-center">Loading master IP records...</div>;
  if (error) return <div className="alert alert-error">{String(error)}</div>;

  const records = (data as { master_ip_records?: Array<Record<string, unknown>> })?.master_ip_records ?? [];

  return (
    <div className="stack-lg">
      <SectionCard title="Master IP Records" subtitle="Deduplicated canonical patent/design records linked from submissions.">
        {records.length === 0 ? <div className="empty-cell">No master IP records have been created yet.</div> : <div className="table-wrap"><table className="data-table"><thead><tr><th>Identifier</th><th>Type</th><th>Title</th><th>Workflow</th><th>Verification</th><th>Contributors</th></tr></thead><tbody>{records.map((record) => <tr key={String(record.id)}><td>{display(record.patent_number || record.design_number || record.application_number)}</td><td>{display(record.ip_type)}</td><td>{display(record.title)}</td><td><StatusBadge value={String(record.workflow_state || 'UPLOADED')} /></td><td><StatusBadge value={String(record.official_verification_status || 'UNVERIFIED')} /></td><td>{Array.isArray(record.contributors) ? (record.contributors as Array<Record<string, unknown>>).map((c) => display(c.name)).join(', ') : '—'}</td></tr>)}</tbody></table></div>}
      </SectionCard>
    </div>
  );
}

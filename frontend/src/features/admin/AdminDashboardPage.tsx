import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { SectionCard, StatCard } from '../../components/ui';

export function AdminDashboardPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['admin-dashboard'], queryFn: api.adminDashboard });
  const activity = useQuery({ queryKey: ['admin-activity'], queryFn: () => api.adminDashboard() });
  if (isLoading) return <div className="page-center">Loading admin dashboard...</div>;
  if (error) return <div className="alert alert-error">{String(error)}</div>;
  const kpis = data?.kpis ?? {};
  return (
    <div className="stack-lg">
      <SectionCard title="Admin Dashboard" subtitle="Live backend counters and recent activity.">
        <div className="grid stats-grid">
          <StatCard label="Total faculty" value={kpis.total_faculty ?? 0} />
          <StatCard label="Total IP records" value={kpis.total_ip_records ?? 0} />
          <StatCard label="Awaiting review" value={kpis.pending_records ?? 0} />
          <StatCard label="Verified" value={kpis.verified_records ?? 0} />
          <StatCard label="Pending verifications" value={kpis.pending_verifications ?? 0} />
          <StatCard label="Pending duplicates" value={kpis.pending_duplicates ?? 0} />
          <StatCard label="Pending conflicts" value={kpis.open_conflicts ?? 0} />
          <StatCard label="Pending associations" value={kpis.pending_associations ?? 0} />
        </div>
      </SectionCard>
      <SectionCard title="Recent activity">
        <div className="mini-list">
          {(activity.data?.recent_activity ?? []).slice(0, 5).map((item: any, index: number) => <div key={index} className="mini-card"><strong>{item.title || item.ip_type || item.id || 'Activity'}</strong><div className="muted">{item.processing_status || item.status || '?'}</div></div>)}
        </div>
      </SectionCard>
    </div>
  );
}

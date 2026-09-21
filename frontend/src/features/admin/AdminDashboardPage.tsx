import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { SectionCard, StatCard } from '../../components/ui';

export function AdminDashboardPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['admin-dashboard'], queryFn: api.adminDashboard });
  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading admin dashboard…</span></div>;
  if (error) return <div className="alert alert-error">{String(error)}</div>;
  const kpis = data?.kpis ?? {};
  const recent = data?.recent_activity ?? [];
  return (
    <div className="stack-lg">
      <SectionCard title="Admin Dashboard" subtitle="Live backend counters and recent uploads. All values from /api/v1/admin/dashboard.">
        <div className="grid stats-grid">
          <StatCard label="Total faculty" value={kpis.total_faculty ?? 0} hint={`${kpis.active_faculty ?? 0} active`} />
          <StatCard label="Total HODs" value={kpis.total_hods ?? 0} />
          <StatCard label="Total IP records" value={kpis.total_ip_records ?? 0} hint={`${kpis.uploads_this_month ?? 0} this month`} />
          <StatCard label="Patents" value={kpis.total_patents ?? 0} />
          <StatCard label="Designs" value={kpis.total_designs ?? 0} />
          <StatCard label="Awaiting review" value={kpis.pending_records ?? 0} />
          <StatCard label="Verified (official)" value={kpis.verified_records ?? 0} />
          <StatCard label="Pending verifications" value={kpis.pending_verifications ?? 0} />
          <StatCard label="Pending duplicates" value={kpis.pending_duplicates ?? 0} />
          <StatCard label="Open conflicts" value={kpis.open_conflicts ?? 0} />
          <StatCard label="Pending associations" value={kpis.pending_associations ?? 0} />
        </div>
      </SectionCard>
      <SectionCard title="Recent uploads" subtitle="Latest 10 IP records by creation date.">
        <div className="mini-list">
          {recent.length === 0 ? <div className="muted">No uploads yet.</div> : recent.slice(0, 5).map((item: any, index: number) => <div key={String(item.id ?? index)} className="mini-card"><strong>{item.title || item.ip_type || 'Untitled record'}</strong><div className="muted">{item.processing_status || '?'} · {item.ip_type || ''} · {item.created_at ? new Date(item.created_at).toLocaleString() : ''}</div></div>)}
        </div>
      </SectionCard>
    </div>
  );
}

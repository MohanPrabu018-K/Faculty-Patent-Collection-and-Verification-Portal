import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import {
  SectionCard, StatCard, LoadingBlock, ErrorBlock, EmptyState,
  TableWrap, Pagination, MiniBars, display,
} from '../../components/ui';

function monthLabel(d: string) {
  const dt = new Date(d);
  return Number.isNaN(dt.getTime()) ? d : dt.toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
}

export function AdminReportsPage() {
  const [facPage, setFacPage] = useState(1);
  const [deptPage, setDeptPage] = useState(1);

  const overview = useQuery({ queryKey: ['analytics-overview'], queryFn: api.analyticsOverview });
  const byFaculty = useQuery({ queryKey: ['analytics-by-faculty', facPage], queryFn: () => api.analyticsByFaculty(`?page=${facPage}&per_page=10`) });
  const byDept = useQuery({ queryKey: ['analytics-by-department', deptPage], queryFn: () => api.analyticsByDepartment(`?page=${deptPage}&per_page=10`) });

  if (overview.isLoading) return <LoadingBlock label="Loading analytics…" />;
  if (overview.error) return <ErrorBlock error={overview.error} />;
  const o = overview.data!;

  const uploadTrend = Object.fromEntries((o.upload_trend ?? []).map((t) => [monthLabel(t.date), t.value]));
  const verifTrend = Object.fromEntries((o.verification_trend ?? []).map((t) => [monthLabel(t.date), t.value]));

  const facRows = byFaculty.data?.faculty ?? [];
  const deptRows = byDept.data?.departments ?? [];
  const facPages = byFaculty.data ? Math.max(1, Math.ceil(byFaculty.data.total / byFaculty.data.per_page)) : 1;
  const deptPages = byDept.data ? Math.max(1, Math.ceil(byDept.data.total / byDept.data.per_page)) : 1;

  return (
    <div className="stack-lg">
      <SectionCard title="Institution Overview" subtitle="Live analytics across every department and faculty.">
        <div className="grid stats-grid">
          <StatCard label="Faculty" value={o.total_faculty} hint={`${o.active_faculty} active`} />
          <StatCard label="IP records" value={o.total_ip_records} />
          <StatCard label="Verified" value={o.verified_records} />
          <StatCard label="Pending verification" value={o.pending_verification} />
          <StatCard label="Pending processing" value={o.pending_processing} />
          <StatCard label="Collaborative" value={o.collaborative_records} />
          <StatCard label="External contributors" value={o.external_contributions} />
        </div>
      </SectionCard>

      <div className="grid detail-grid">
        <SectionCard title="By IP type"><MiniBars data={o.by_ip_type} /></SectionCard>
        <SectionCard title="By verification status"><MiniBars data={o.by_verification_status} /></SectionCard>
        <SectionCard title="By processing status"><MiniBars data={o.by_processing_status} /></SectionCard>
        <SectionCard title="By department"><MiniBars data={o.by_department} formatLabel={(k) => k} /></SectionCard>
      </div>

      <div className="grid detail-grid">
        <SectionCard title="Uploads by year"><MiniBars data={o.by_year} formatLabel={(k) => k} /></SectionCard>
        <SectionCard title="Upload trend (monthly)"><MiniBars data={uploadTrend} formatLabel={(k) => k} /></SectionCard>
      </div>

      <SectionCard title="Verification trend (monthly)">
        {Object.keys(verifTrend).length === 0 ? <EmptyState message="No verification attempts recorded." /> : <MiniBars data={verifTrend} formatLabel={(k) => k} />}
      </SectionCard>

      <SectionCard title="Faculty statistics" subtitle="Records, verification and pending work per faculty member.">
        {byFaculty.isLoading ? <LoadingBlock /> : facRows.length === 0 ? <EmptyState message="No faculty." /> : (
          <TableWrap>
            <table className="data-table">
              <thead><tr><th>Faculty</th><th>ID</th><th>Records</th><th>Verified</th><th>Pending</th><th>Collaborative</th></tr></thead>
              <tbody>
                {facRows.map((r) => (
                  <tr key={String(r.faculty_id)}>
                    <td><strong>{display(r.faculty_name)}</strong></td>
                    <td>{display(r.faculty_id)}</td>
                    <td>{display(r.total_records)}</td>
                    <td>{display(r.verified_records)}</td>
                    <td>{display(r.pending_records)}</td>
                    <td>{display(r.collaborative_count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
        <Pagination page={facPage} totalPages={facPages} onChange={setFacPage} disabled={byFaculty.isFetching} />
      </SectionCard>

      <SectionCard title="Department statistics" subtitle="Records and verification per department.">
        {byDept.isLoading ? <LoadingBlock /> : deptRows.length === 0 ? <EmptyState message="No departments." /> : (
          <TableWrap>
            <table className="data-table">
              <thead><tr><th>Department</th><th>Faculty</th><th>Records</th><th>Verified</th></tr></thead>
              <tbody>
                {deptRows.map((r) => (
                  <tr key={String(r.department_id)}>
                    <td><strong>{display(r.department_name)}</strong></td>
                    <td>{display(r.total_faculty)}</td>
                    <td>{display(r.total_records)}</td>
                    <td>{display(r.verified_records)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
        <Pagination page={deptPage} totalPages={deptPages} onChange={setDeptPage} disabled={byDept.isFetching} />
      </SectionCard>
    </div>
  );
}

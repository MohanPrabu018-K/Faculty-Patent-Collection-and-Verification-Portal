import { useState } from 'react';
import { keepPreviousData, useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import {
  SectionCard, StatCard, StatusBadge, ErrorBlock, EmptyState,
  TableWrap, Pagination, MiniBars, display, downloadFile,
} from '../../components/ui';
import { useToast } from '../../stores/toast';

function monthLabel(d: string) {
  const dt = new Date(d);
  return Number.isNaN(dt.getTime()) ? d : dt.toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
}

export function AdminReportsPage() {
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const [facPage, setFacPage] = useState(1);
  const [deptPage, setDeptPage] = useState(1);
  const [exportFormat, setExportFormat] = useState<'csv' | 'excel' | 'pdf' | 'docx' | 'txt'>('csv');
  const [exporting, setExporting] = useState(false);

  const overview = useQuery({ queryKey: ['analytics-overview'], queryFn: api.analyticsOverview });
  const byFaculty = useQuery({ queryKey: ['analytics-by-faculty', facPage], queryFn: ({ signal }) => api.analyticsByFaculty(`?page=${facPage}&per_page=10`, signal), placeholderData: keepPreviousData });
  const byDept = useQuery({ queryKey: ['analytics-by-department', deptPage], queryFn: ({ signal }) => api.analyticsByDepartment(`?page=${deptPage}&per_page=10`, signal), placeholderData: keepPreviousData });
  const dashboard = useQuery({ queryKey: ['admin-dashboard'], queryFn: api.adminDashboard });
  const [assocPage, setAssocPage] = useState(1);
  const pendingAssoc = useQuery({
    queryKey: ['admin-pending-associations', assocPage],
    queryFn: ({ signal }) => api.pendingAssociationsReport(`?page=${assocPage}&per_page=10`, signal),
    placeholderData: keepPreviousData,
  });

  const runExport = async (fmtOverride?: string) => {
    const fmt = fmtOverride || exportFormat;
    setExporting(true);
    try {
      const job = await api.createExport(fmt as never);
      const extMap: Record<string, string> = { csv: 'csv', excel: 'xlsx', pdf: 'pdf', docx: 'docx', txt: 'txt' };
      await downloadFile(api.exportDownloadUrl(job.job_id), `analytics-report-${job.job_id}.${extMap[fmt] ?? fmt}`);
      notify('success', `${fmt.toUpperCase()} export downloaded`);
    } catch (e) {
      notify('error', e instanceof Error ? e.message : 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  if (overview.isLoading && !overview.data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading analytics…</span></div>;
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
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12 }}>
          <label className="label-xs">Export analytics</label>
          <select className="input-sm" value={exportFormat} onChange={(e) => setExportFormat(e.target.value as typeof exportFormat)}>
            <option value="csv">CSV</option>
            <option value="excel">Excel</option>
            <option value="pdf">PDF</option>
            <option value="docx">DOCX</option>
            <option value="txt">TXT</option>
          </select>
          <button className="btn btn-primary btn-sm" onClick={() => void runExport()} disabled={exporting}>{exporting ? 'Exporting…' : 'Export report'}</button>
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

      <SectionCard title="Workflow & review queues" subtitle="Live counts from review queues. Institutional verification is human HOD review; official IP India verification stays separate.">
        <div className="grid stats-grid">
          <StatCard label="Pending duplicates" value={dashboard.data?.kpis.pending_duplicates ?? 0} />
          <StatCard label="Open conflicts" value={dashboard.data?.kpis.open_conflicts ?? 0} />
          <StatCard label="Pending associations" value={dashboard.data?.kpis.pending_associations ?? 0} />
          <StatCard label="Pending verifications" value={dashboard.data?.kpis.pending_verifications ?? 0} />
        </div>
        <p className="muted">Official IP India verification: unavailable (no fake VERIFIED). HOD institutional decisions are recorded per-record with audit.</p>
      </SectionCard>

      <SectionCard title="Pending associations" subtitle={`Faculty — record pairs awaiting action. ${pendingAssoc.data?.pending_count ?? 0} pending.`}>
        {pendingAssoc.isLoading && !pendingAssoc.data ? <div className="loading-inline"><span className="spinner" /><span>Loading…</span></div>
          : pendingAssoc.error && !pendingAssoc.data ? <ErrorBlock error={pendingAssoc.error} />
            : (pendingAssoc.data?.associations ?? []).length === 0 && !pendingAssoc.isFetching ? <EmptyState message="No pending associations." />
              : (
                <TableWrap>
                  <table className="data-table">
                    <thead><tr><th>Faculty</th><th>Record</th><th>Status</th><th>Since</th></tr></thead>
                    <tbody>
                      {(pendingAssoc.data?.associations ?? []).map((a) => {
                        const req = (a.requester ?? {}) as Record<string, unknown>;
                        const tgt = (a.target ?? {}) as Record<string, unknown>;
                        const rec = (a.record ?? {}) as Record<string, unknown>;
                        const facultyLabel = display(tgt.full_name || tgt.faculty_id || tgt.email);
                        const recordLabel = display(rec.title || rec.patent_number || rec.design_number || rec.application_number || rec.id);
                        return (
                          <tr key={String(a.id)}>
                            <td><strong>{facultyLabel}</strong><div className="muted">{display(req.full_name || req.email)} → {display(tgt.full_name || tgt.email)}</div></td>
                            <td>{recordLabel}<div className="muted">{display(rec.ip_type)}</div></td>
                            <td><StatusBadge value={String(a.status || 'PENDING')} /></td>
                            <td>{display(a.created_at)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </TableWrap>
              )}
        <Pagination page={assocPage} totalPages={pendingAssoc.data ? Math.max(1, Math.ceil(pendingAssoc.data.total / pendingAssoc.data.per_page)) : 1} onChange={setAssocPage} disabled={pendingAssoc.isFetching} />
      </SectionCard>

      <SectionCard title="Faculty statistics" subtitle="Records, verification and pending work per faculty member.">
        {byFaculty.isLoading && !byFaculty.data ? <div className="loading-inline"><span className="spinner" /><span>Loading…</span></div> : facRows.length === 0 && !byFaculty.isFetching ? <EmptyState message="No faculty." /> : (
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
        {byDept.isLoading && !byDept.data ? <div className="loading-inline"><span className="spinner" /><span>Loading…</span></div> : deptRows.length === 0 && !byDept.isFetching ? <EmptyState message="No departments." /> : (
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

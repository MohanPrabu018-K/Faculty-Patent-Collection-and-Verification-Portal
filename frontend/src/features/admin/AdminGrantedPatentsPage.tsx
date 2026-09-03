import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import {
  SectionCard, StatusBadge, LoadingBlock, ErrorBlock, EmptyState,
  Toolbar, TableWrap, Pagination, formatDate, display, downloadFile,
} from '../../components/ui';
import { useToast } from '../../stores/toast';

export function AdminGrantedPatentsPage() {
  const navigate = useNavigate();
  const { notify } = useToast();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [verification, setVerification] = useState('');
  const [exporting, setExporting] = useState(false);

  const runExport = async () => {
    setExporting(true);
    try {
      const job = await api.createExport('csv');
      await downloadFile(api.exportDownloadUrl(job.job_id), `patents-${job.job_id}.csv`);
      notify('success', 'CSV export downloaded');
    } catch (e) {
      notify('error', e instanceof Error ? e.message : 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  const params = useMemo(() => {
    const q = new URLSearchParams({ page: String(page), per_page: '20', ip_type: 'PATENT' });
    if (verification) q.set('verification_status', verification);
    return `?${q.toString()}`;
  }, [page, verification]);

  const { data, isLoading, error, isFetching } = useQuery({ queryKey: ['admin-granted-patents', params], queryFn: () => api.adminRecords(params) });

  if (isLoading) return <LoadingBlock label="Loading granted patents…" />;
  if (error) return <ErrorBlock error={error} />;

  const all = data?.records ?? [];
  const rows = all.filter((r) => {
    if (!search) return true;
    const hay = [r.title, r.patent_number, r.application_number, r.contributor_name, r.applicant].map(display).join(' ').toLowerCase();
    return hay.includes(search.toLowerCase());
  });
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.per_page)) : 1;

  return (
    <SectionCard
      title="Granted Patents"
      subtitle={`${data?.total ?? 0} patent records. OCR extracts title, inventors, dates and numbers automatically.`}
      actions={
        <>
          <button className="btn btn-sm btn-secondary" disabled={exporting} onClick={runExport}>{exporting ? 'Exporting…' : 'Export CSV'}</button>
          <button className="btn btn-sm btn-primary" onClick={() => navigate('/admin/patent-upload')}>Add patent</button>
        </>
      }
    >
      <Toolbar>
        <input className="toolbar-input" placeholder="Search title, number, inventor" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search patents" />
        <select className="toolbar-input" value={verification} onChange={(e) => { setVerification(e.target.value); setPage(1); }} aria-label="Verification filter">
          <option value="">All verification states</option>
          <option value="VERIFIED">Verified</option>
          <option value="VERIFICATION_REQUIRED">Verification required</option>
          <option value="UNVERIFIED">Unverified</option>
          <option value="MISMATCH">Mismatch</option>
        </select>
      </Toolbar>

      {rows.length === 0 ? (
        <EmptyState message="No patent records match your filters." action={<button className="btn btn-primary" onClick={() => navigate('/admin/patent-upload')}>Add the first patent</button>} />
      ) : (
        <TableWrap>
          <table className="data-table">
            <thead>
              <tr><th>Patent no.</th><th>Title</th><th>Inventor(s)</th><th>Applicant</th><th>Filing date</th><th>Processing</th><th>Verification</th><th></th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={String(r.id)}>
                  <td><strong>{display(r.patent_number || r.application_number)}</strong></td>
                  <td>{display(r.title)}</td>
                  <td>{display(r.contributor_name)}</td>
                  <td>{display(r.applicant || r.patentee)}</td>
                  <td>{r.filing_date ? formatDate(r.filing_date) : '—'}</td>
                  <td><StatusBadge value={String(r.processing_status || 'UNKNOWN')} /></td>
                  <td><StatusBadge value={String(r.verification_status || 'UNKNOWN')} /></td>
                  <td><Link className="link" to={`/faculty/records/${r.id}`}>Open</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
      <Pagination page={page} totalPages={totalPages} onChange={setPage} disabled={isFetching} />
    </SectionCard>
  );
}

import { useMemo, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { SectionCard, StatusBadge, Toolbar, TableWrap, Pagination, EmptyState } from '../../components/ui';
import { useDebounce } from '../../hooks/useDebounce';

function display(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Not available';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function AdminMasterRecordsPage() {
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 400);
  const [ipType, setIpType] = useState('');
  const [page, setPage] = useState(1);

  const params = useMemo(() => {
    const q = new URLSearchParams({ page: String(page), per_page: '20' });
    if (debouncedSearch.trim()) q.set('search', debouncedSearch.trim());
    if (ipType) q.set('ip_type', ipType);
    return `?${q.toString()}`;
  }, [page, debouncedSearch, ipType]);

  const { data, isLoading, error, isFetching, refetch } = useQuery({ queryKey: ['admin-master-records', params], queryFn: ({ signal }) => api.adminMasterRecords(params, signal), placeholderData: keepPreviousData });

  const records = (data as { master_ip_records?: Array<Record<string, unknown>>; total?: number })?.master_ip_records ?? [];
  const total = (data as any)?.total ?? records.length;
  const totalPages = Math.max(1, Math.ceil(total / ((data as any)?.per_page ?? 20)));

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading master IP records…</span></div>;
  if (error && !data) return <div className="alert alert-error">{String(error)}</div>;

  return (
    <div className="stack-lg">
      <SectionCard title="Master IP Records" subtitle="Canonical underlying IP (1 master ← N uploaded IP Records/versions). IP Records = uploaded documents; Master = deduplicated canonical entity.">
        <Toolbar>
          <input className="toolbar-input" placeholder="Search title or number (debounced 400ms)" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} aria-label="Search masters" />
          <select className="toolbar-input" value={ipType} onChange={(e) => { setIpType(e.target.value); setPage(1); }} aria-label="Filter IP type">
            <option value="">All types</option>
            <option value="PATENT">Patent</option>
            <option value="DESIGN_REGISTRATION">Design</option>
          </select>
          <button className="btn btn-secondary" onClick={() => { setSearch(''); setIpType(''); setPage(1); }}>Clear</button>
        </Toolbar>
        <div className="muted" style={{ marginBottom: 10 }}>{isFetching ? 'Searching…' : `${total} canonical masters`}</div>
        {error && data ? (
          <div className="alert alert-error" role="alert" style={{ marginBottom: 12 }}>
            Refresh failed: {String(error)}{' '}
            <button className="btn btn-sm btn-secondary" onClick={() => void refetch()} disabled={isFetching}>Retry</button>
          </div>
        ) : null}
        {records.length === 0 && !isFetching ? <EmptyState message="No master IP records match your filters." /> : <div className={isFetching && data ? 'table-fetching' : ''}>{isFetching && data ? <div className="table-fetching-indicator"><span className="spinner" /> Updating…</div> : null}<TableWrap><table className="data-table"><thead><tr><th>Identifier</th><th>Type</th><th>Title</th><th>Linked records</th><th>Workflow</th><th>Verification</th><th>Contributors</th></tr></thead><tbody>{records.map((record) => <tr key={String(record.id)}><td>{display(record.patent_number || record.design_number || record.application_number)}</td><td>{display(record.ip_type)}</td><td>{display(record.title)}</td><td><strong>{display((record as any).linked_records ?? '?')}</strong></td><td><StatusBadge value={String(record.workflow_state || 'UPLOADED')} /></td><td><StatusBadge value={String(record.official_verification_status || 'UNVERIFIED')} /></td><td>{Array.isArray(record.contributors) ? (record.contributors as Array<Record<string, unknown>>).map((c) => display(c.name)).join(', ') : '—'}</td></tr>)}</tbody></table></TableWrap></div>}
        <Pagination page={page} totalPages={totalPages} onChange={setPage} disabled={isFetching} />
      </SectionCard>
    </div>
  );
}

import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import {
  SectionCard, StatusBadge, ErrorBlock, EmptyState,
  Toolbar, TableWrap, Pagination, formatDate, display,
} from '../../components/ui';
import { useAuth } from '../../stores/auth';
import { useDebounce } from '../../hooks/useDebounce';

export function SearchPage() {
  const { user } = useAuth();
  const [term, setTerm] = useState('');
  const [ipType, setIpType] = useState('');
  const [verification, setVerification] = useState('');
  const [page, setPage] = useState(1);
  const debounced = useDebounce(term, 350);

  useEffect(() => { setPage(1); }, [debounced, ipType, verification]);

  const params = useMemo(() => {
    const q = new URLSearchParams({ page: String(page), per_page: '20' });
    if (debounced.trim()) q.set('query', debounced.trim());
    if (ipType) q.set('ip_type', ipType);
    if (verification) q.set('verification_status', verification);
    return `?${q.toString()}`;
  }, [debounced, ipType, verification, page]);

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['search', params],
    queryFn: ({ signal }) => api.search(params, signal),
    placeholderData: keepPreviousData,
  });

  const scopeNote =
    user?.role === 'super_admin' ? 'Institution-wide search.'
      : user?.role === 'hod_admin' ? 'Scoped to your department.'
        : 'Scoped to your own records.';

  const rows = data?.results ?? [];

  return (
    <SectionCard
      title="Search"
      subtitle={`Title, applicant, inventor, patent / design / application number, faculty name. ${scopeNote}`}
    >
      <Toolbar>
        <input
          className="toolbar-input"
          style={{ flex: '2 1 280px' }}
          placeholder="Search records…"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          aria-label="Search"
          autoFocus
        />
        <select className="toolbar-input" value={ipType} onChange={(e) => setIpType(e.target.value)} aria-label="Type filter">
          <option value="">All types</option>
          <option value="PATENT">Patent</option>
          <option value="DESIGN_REGISTRATION">Design</option>
          <option value="UNKNOWN_OTHER">Other</option>
        </select>
        <select className="toolbar-input" value={verification} onChange={(e) => setVerification(e.target.value)} aria-label="Verification filter">
          <option value="">Any verification</option>
          <option value="VERIFIED">Verified</option>
          <option value="VERIFICATION_REQUIRED">Verification required</option>
          <option value="UNVERIFIED">Unverified</option>
          <option value="MISMATCH">Mismatch</option>
        </select>
      </Toolbar>

      <div className="muted" style={{ marginBottom: 10 }}>
        {isFetching ? 'Searching…' : data ? `${data.total} result${data.total === 1 ? '' : 's'} · ${data.query_time_ms} ms` : ''}
      </div>

      {isLoading && !data ? (
        <div className="loading-inline" style={{ padding: '16px 0' }}><span className="spinner" /><span>Searching…</span></div>
      ) : error && !data ? (
        <ErrorBlock error={error} />
      ) : rows.length === 0 && !isFetching ? (
        <EmptyState message={debounced.trim() || ipType || verification ? 'No records match your search.' : 'Type to search across records you can access.'} />
      ) : (
        <>
          {error && data ? (
            <div className="alert alert-error" role="alert" style={{ marginBottom: 12 }}>
              Refresh failed: {error instanceof Error ? error.message : String(error)}{' '}
              <button className="btn btn-sm btn-secondary" onClick={() => void refetch()} disabled={isFetching}>Retry</button>
            </div>
          ) : null}
          <div className={isFetching && data ? 'table-fetching' : ''}>
            {isFetching && data ? <div className="table-fetching-indicator"><span className="spinner" /> Updating…</div> : null}
            <TableWrap>
            <table className="data-table">
              <thead>
                <tr><th>Record</th><th>Type</th><th>Number</th><th>Faculty</th><th>Department</th><th>Verification</th><th>Created</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link className="link" to={`/faculty/records/${r.id}`}>
                        {display(r.title || r.applicant || r.id)}
                      </Link>
                      {r.is_collaborative ? <div className="muted">{r.contributor_count} contributors</div> : null}
                    </td>
                    <td>{display(r.ip_type)}</td>
                    <td>{display(r.patent_number || r.design_number || r.application_number)}</td>
                    <td>{display(r.faculty_name)}<div className="muted">{display(r.faculty_id)}</div></td>
                    <td>{display(r.department)}</td>
                    <td><StatusBadge value={r.verification_status || 'UNKNOWN'} /></td>
                    <td>{formatDate(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
          </div>
          <Pagination page={page} totalPages={data?.total_pages ?? 1} onChange={setPage} disabled={isFetching} />
        </>
      )}
    </SectionCard>
  );
}

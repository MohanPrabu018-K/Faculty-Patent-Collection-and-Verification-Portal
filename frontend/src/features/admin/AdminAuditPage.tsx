import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, type AuditLogRow } from '../../api/client';
import {
  SectionCard, StatCard, StatusBadge, LoadingBlock, ErrorBlock, EmptyState,
  Toolbar, TableWrap, Pagination, Modal, formatDateTime, display,
} from '../../components/ui';

const ACTION_OPTIONS = [
  '', 'UPLOAD', 'RECORD_REVIEWED', 'DUPLICATE_DETECTED', 'DUPLICATE_RESOLVED',
  'CONFLICT_DETECTED', 'CONFLICT_RESOLVED', 'ASSOCIATION_REQUEST_CREATED',
  'ASSOCIATION_REQUEST_ACCEPTED', 'ASSOCIATION_REQUEST_REJECTED', 'ASSOCIATION_REQUEST_NOT_ME',
  'ASSOCIATION_REQUEST_CLARIFICATION_REQUESTED', 'ASSOCIATION_CLARIFICATION_PROVIDED',
  'EXCEL_IMPORT_STARTED', 'EXCEL_IMPORT_COMPLETED',
  'FACULTY_CREATED', 'FACULTY_UPDATED', 'FACULTY_ACTIVATED', 'FACULTY_DEACTIVATED',
  'FACULTY_CREDENTIAL_RESET', 'HOD_REMINDER_CREATED', 'PROFILE_UPDATED',
];

const ENTITY_OPTIONS = ['', 'ip_record', 'duplicate_case', 'conflict_case', 'association_request', 'user', 'department', 'import_job'];

export function AdminAuditPage() {
  const [page, setPage] = useState(1);
  const [action, setAction] = useState('');
  const [entityType, setEntityType] = useState('');
  const [actorId, setActorId] = useState('');
  const [entityId, setEntityId] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [detail, setDetail] = useState<AuditLogRow | null>(null);

  const params = useMemo(() => {
    const q = new URLSearchParams({ page: String(page), per_page: '25' });
    if (action) q.set('action', action);
    if (entityType) q.set('entity_type', entityType);
    if (actorId.trim()) q.set('actor_id', actorId.trim());
    if (entityId.trim()) q.set('entity_id', entityId.trim());
    if (startDate) q.set('start_date', startDate);
    if (endDate) q.set('end_date', endDate);
    return `?${q.toString()}`;
  }, [page, action, entityType, actorId, entityId, startDate, endDate]);

  const list = useQuery({ queryKey: ['admin-audit', params], queryFn: () => api.adminAuditLogs(params) });
  const stats = useQuery({ queryKey: ['admin-audit-stats'], queryFn: api.adminAuditStats });

  if (list.isLoading) return <LoadingBlock label="Loading audit trail…" />;
  if (list.error) return <ErrorBlock error={list.error} />;

  const rows = list.data?.audit_logs ?? [];
  const totalPages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.per_page)) : 1;

  const reset = () => { setAction(''); setEntityType(''); setActorId(''); setEntityId(''); setStartDate(''); setEndDate(''); setPage(1); };

  return (
    <div className="stack-lg">
      <SectionCard title="Audit Trail" subtitle="Immutable, institution-wide record of every important action.">
        <div className="grid stats-grid">
          <StatCard label="Total audit events" value={stats.data?.total_audit_logs ?? list.data?.total ?? 0} />
          <StatCard label="Security events" value={stats.data?.total_security_events ?? 0} />
          <StatCard label="Shown (page)" value={rows.length} />
          <StatCard label="Filters active" value={[action, entityType, actorId, entityId, startDate, endDate].filter(Boolean).length} />
        </div>
      </SectionCard>

      <SectionCard
        title="Events"
        subtitle={`${list.data?.total ?? 0} events`}
        actions={<button className="btn btn-sm btn-secondary" onClick={reset}>Clear filters</button>}
      >
        <Toolbar>
          <select className="toolbar-input" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} aria-label="Filter action">
            {ACTION_OPTIONS.map((a) => <option key={a} value={a}>{a ? a.replace(/_/g, ' ') : 'All actions'}</option>)}
          </select>
          <select className="toolbar-input" value={entityType} onChange={(e) => { setEntityType(e.target.value); setPage(1); }} aria-label="Filter entity type">
            {ENTITY_OPTIONS.map((a) => <option key={a} value={a}>{a ? a.replace(/_/g, ' ') : 'All entity types'}</option>)}
          </select>
          <input className="toolbar-input" placeholder="Actor / user id" value={actorId} onChange={(e) => { setActorId(e.target.value); setPage(1); }} aria-label="Filter actor" />
          <input className="toolbar-input" placeholder="Entity / target id" value={entityId} onChange={(e) => { setEntityId(e.target.value); setPage(1); }} aria-label="Filter entity id" />
          <input className="toolbar-input" type="date" value={startDate} onChange={(e) => { setStartDate(e.target.value); setPage(1); }} aria-label="Start date" />
          <input className="toolbar-input" type="date" value={endDate} onChange={(e) => { setEndDate(e.target.value); setPage(1); }} aria-label="End date" />
        </Toolbar>

        {rows.length === 0 ? (
          <EmptyState message="No audit events match the current filters." />
        ) : (
          <TableWrap>
            <table className="data-table">
              <thead>
                <tr><th>Timestamp</th><th>Actor</th><th>Role</th><th>Department</th><th>Action</th><th>Entity</th><th>Target</th><th></th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{formatDateTime(r.created_at)}</td>
                    <td>{display(r.actor_name || r.actor_id)}{r.actor_name ? <div className="muted">{display(r.actor_id)}</div> : null}</td>
                    <td>{display(r.actor_role ? r.actor_role.replace('_', ' ') : null)}</td>
                    <td>{display(r.actor_department)}</td>
                    <td><StatusBadge value={r.action} /></td>
                    <td>{display(r.entity_type)}<div className="muted">{String(r.entity_id || '').slice(0, 10)}</div></td>
                    <td>{display(r.target_type || '—')}<div className="muted">{String(r.target_id || '').slice(0, 10)}</div></td>
                    <td><button className="btn btn-sm btn-secondary" onClick={() => setDetail(r)}>View</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
        <Pagination page={page} totalPages={totalPages} onChange={setPage} disabled={list.isFetching} />
      </SectionCard>

      {detail && (
        <Modal title="Audit event" onClose={() => setDetail(null)}>
          <div className="kv-grid">
            {[
              ['Timestamp', formatDateTime(detail.created_at)],
              ['Action', detail.action],
              ['Actor', detail.actor_name || detail.actor_id],
              ['Actor id', detail.actor_id],
              ['Role', detail.actor_role],
              ['Department', detail.actor_department],
              ['IP address', detail.ip_address],
              ['Entity type', detail.entity_type],
              ['Entity id', detail.entity_id],
              ['Target type', detail.target_type],
              ['Target id', detail.target_id],
              ['Reason', detail.reason],
            ].map(([k, v]) => <div key={String(k)} className="detail-field"><span>{String(k)}</span><strong>{display(v)}</strong></div>)}
          </div>
          {Boolean(detail.previous_value || detail.new_value) && (
            <div className="stack" style={{ marginTop: 8 }}>
              <div><span className="muted">Before</span><pre className="inline-json">{JSON.stringify(detail.previous_value ?? detail.before_state ?? {}, null, 2)}</pre></div>
              <div><span className="muted">After</span><pre className="inline-json">{JSON.stringify(detail.new_value ?? detail.after_state ?? {}, null, 2)}</pre></div>
            </div>
          )}
          {(detail.extra || detail.details) ? (
            <div><span className="muted">Extra</span><pre className="inline-json">{JSON.stringify(detail.extra ?? detail.details ?? {}, null, 2)}</pre></div>
          ) : null}
        </Modal>
      )}
    </div>
  );
}

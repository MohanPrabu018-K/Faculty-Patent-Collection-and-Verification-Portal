import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type NotificationRow } from '../../api/client';
import { SectionCard, StatusBadge, ErrorBlock, EmptyState, Pagination, formatDateTime } from '../../components/ui';
import { useToast } from '../../stores/toast';

export function NotificationsPage() {
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [page, setPage] = useState(1);
  const client = useQueryClient();
  const { notify } = useToast();
  const navigate = useNavigate();

  const params = `?page=${page}&per_page=20${unreadOnly ? '&unread_only=true' : ''}`;
  const { data, isLoading, error, isFetching, refetch } = useQuery({
    queryKey: ['notifications', params],
    queryFn: ({ signal }) => api.notifications(params, signal),
    placeholderData: keepPreviousData,
  });

  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['notifications'] }),
      client.invalidateQueries({ queryKey: ['notifications-unread'] }),
    ]);
  };

  const markRead = useMutation({ mutationFn: (id: string) => api.markNotificationRead(id), onSuccess: refresh });
  const markAll = useMutation({
    mutationFn: () => api.markAllNotificationsRead(),
    onSuccess: async (r) => { notify('success', `Marked ${(r as { marked_read?: number }).marked_read ?? 0} as read`); await refresh(); },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteNotification(id),
    onSuccess: async () => { notify('success', 'Notification removed'); await refresh(); },
    onError: () => notify('error', 'Failed to remove'),
  });

  const items = data?.notifications ?? [];
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.per_page)) : 1;

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading notifications…</span></div>;
  if (error && !data) return <ErrorBlock error={error} />;

  const open = (n: NotificationRow) => {
    if (!n.is_read) markRead.mutate(n.id);
    if (n.action_url) navigate(n.action_url.startsWith('/') ? n.action_url : `/${n.action_url}`);
  };

  return (
    <SectionCard
      title="Notifications"
      subtitle={`${data?.unread_count ?? 0} unread`}
      actions={
        <div className="pill-row">
          <label className="pill-row" style={{ gap: 6 }}>
            <input type="checkbox" checked={unreadOnly} onChange={(e) => { setUnreadOnly(e.target.checked); setPage(1); }} />
            <span className="muted">Unread only</span>
          </label>
          <button className="btn btn-sm btn-secondary" disabled={markAll.isPending || (data?.unread_count ?? 0) === 0} onClick={() => markAll.mutate()}>Mark all read</button>
        </div>
      }
    >
      {error && data ? (
        <div className="alert alert-error" role="alert" style={{ marginBottom: 12 }}>
          Refresh failed: {error instanceof Error ? error.message : String(error)}{' '}
          <button className="btn btn-sm btn-secondary" onClick={() => void refetch()} disabled={isFetching}>Retry</button>
        </div>
      ) : null}
      {items.length === 0 && !isFetching ? (
        <EmptyState message={unreadOnly ? 'No unread notifications.' : 'No notifications yet.'} />
      ) : (
        <div className="stack">
          {items.map((n) => (
            <div key={n.id} className={`assoc-card ${n.is_read ? '' : 'unread'}`}>
              <div className="assoc-card-head">
                <div>
                  <strong>{n.title}</strong>
                  <div className="muted">{n.message}</div>
                </div>
                <StatusBadge value={n.priority} />
              </div>
              <div className="assoc-meta">
                <div className="detail-field"><span>Type</span><strong>{n.type.replace(/_/g, ' ')}</strong></div>
                <div className="detail-field"><span>Received</span><strong>{formatDateTime(n.created_at)}</strong></div>
                <div className="detail-field"><span>Status</span><strong>{n.is_read ? 'Read' : 'Unread'}</strong></div>
              </div>
              <div className="btn-row">
                {n.action_url && <button className="btn btn-sm btn-primary" onClick={() => open(n)}>{n.action_label || 'Open'}</button>}
                {!n.is_read && <button className="btn btn-sm btn-secondary" disabled={markRead.isPending} onClick={() => markRead.mutate(n.id)}>Mark read</button>}
                <button className="btn btn-sm btn-ghost" disabled={remove.isPending} onClick={() => remove.mutate(n.id)}>Remove</button>
              </div>
            </div>
          ))}
        </div>
      )}
      <Pagination page={page} totalPages={totalPages} onChange={setPage} disabled={isFetching} />
    </SectionCard>
  );
}

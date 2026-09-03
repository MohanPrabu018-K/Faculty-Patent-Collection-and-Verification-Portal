import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type NotificationRow } from '../../api/client';
import { formatDateTime } from '../../components/ui';

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const navigate = useNavigate();
  const client = useQueryClient();

  const unread = useQuery({
    queryKey: ['notifications-unread'],
    queryFn: api.notificationsUnreadCount,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });

  const list = useQuery({
    queryKey: ['notifications', 'recent'],
    queryFn: () => api.notifications('?per_page=8'),
    enabled: open,
  });

  const markRead = useMutation({
    mutationFn: (id: string) => api.markNotificationRead(id),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['notifications-unread'] }),
        client.invalidateQueries({ queryKey: ['notifications'] }),
      ]);
    },
  });

  const markAll = useMutation({
    mutationFn: () => api.markAllNotificationsRead(),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['notifications-unread'] }),
        client.invalidateQueries({ queryKey: ['notifications'] }),
      ]);
    },
  });

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener('mousedown', onClick);
    return () => window.removeEventListener('mousedown', onClick);
  }, [open]);

  const count = unread.data?.unread_count ?? 0;
  const items = list.data?.notifications ?? [];

  const openItem = (n: NotificationRow) => {
    if (!n.is_read) markRead.mutate(n.id);
    setOpen(false);
    if (n.action_url) navigate(n.action_url.startsWith('/') ? n.action_url : `/${n.action_url}`);
    else navigate('/notifications');
  };

  return (
    <div className="notif-bell" ref={wrapRef}>
      <button className="btn btn-secondary notif-bell-btn" aria-label={`Notifications${count ? `, ${count} unread` : ''}`} onClick={() => setOpen((v) => !v)}>
        <Bell size={16} />
        {count > 0 && <span className="count-badge">{count > 99 ? '99+' : count}</span>}
      </button>
      {open && (
        <div className="notif-panel">
          <div className="notif-head">
            <strong>Notifications</strong>
            <div className="btn-row">
              {count > 0 && <button className="btn btn-sm btn-secondary" disabled={markAll.isPending} onClick={() => markAll.mutate()}>Mark all read</button>}
              <button className="btn btn-sm btn-secondary" onClick={() => { setOpen(false); navigate('/notifications'); }}>View all</button>
            </div>
          </div>
          {list.isLoading ? (
            <div className="notif-item"><span className="notif-msg">Loading…</span></div>
          ) : items.length === 0 ? (
            <div className="notif-item"><span className="notif-msg">You're all caught up.</span></div>
          ) : (
            items.map((n) => (
              <div key={n.id} className={`notif-item ${n.is_read ? '' : 'unread'}`} onClick={() => openItem(n)}>
                <span className="notif-title">{n.title}</span>
                <span className="notif-msg">{n.message}</span>
                <span className="notif-time">{n.type.replace(/_/g, ' ')} · {formatDateTime(n.created_at)}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

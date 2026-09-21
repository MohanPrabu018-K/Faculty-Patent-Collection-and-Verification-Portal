import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, api, type AssociationAction, type AssociationRow } from '../../api/client';
import { SectionCard, StatusBadge, ErrorBlock, EmptyState, Modal, formatDateTime } from '../../components/ui';
import { useAuth } from '../../stores/auth';
import { useToast } from '../../stores/toast';

const RESPONDABLE = new Set(['PENDING', 'CLARIFICATION_REQUESTED']);

export function AssociationsPage() {
  const { user } = useAuth();
  const { notify } = useToast();
  const client = useQueryClient();
  const [filter, setFilter] = useState<'all' | 'incoming' | 'outgoing'>('all');
  const [clarifyFor, setClarifyFor] = useState<AssociationRow | null>(null);
  const [notMeFor, setNotMeFor] = useState<AssociationRow | null>(null);
  const [reason, setReason] = useState('');

  const { data, isLoading, error } = useQuery({ queryKey: ['associations'], queryFn: api.associations });

  const respond = useMutation({
    mutationFn: ({ id, action, text }: { id: string; action: AssociationAction; text?: string }) => api.respondAssociation(id, action, text),
    onSuccess: async (_r, vars) => {
      notify('success', `Request ${vars.action.replace('_', ' ')}`);
      await refreshAll();
      setClarifyFor(null); setNotMeFor(null); setReason('');
    },
    onError: (e) => notify('error', e instanceof ApiError ? friendly(e) : 'Action failed'),
  });

  const clarify = useMutation({
    mutationFn: ({ id, message }: { id: string; message: string }) => api.clarifyAssociation(id, message),
    onSuccess: async () => { notify('success', 'Clarification sent'); await refreshAll(); setClarifyFor(null); setReason(''); },
    onError: (e) => notify('error', e instanceof ApiError ? friendly(e) : 'Failed to send clarification'),
  });

  const cancel = useMutation({
    mutationFn: (id: string) => api.cancelAssociation(id),
    onSuccess: async () => { notify('success', 'Request cancelled'); await refreshAll(); },
    onError: (e) => notify('error', e instanceof ApiError ? friendly(e) : 'Failed to cancel'),
  });

  async function refreshAll() {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['associations'] }),
      client.invalidateQueries({ queryKey: ['notifications'] }),
      client.invalidateQueries({ queryKey: ['notifications-unread'] }),
      client.invalidateQueries({ queryKey: ['faculty-dashboard'] }),
    ]);
  }

  const rows = useMemo(() => {
    const all = data?.associations ?? [];
    if (filter === 'incoming') return all.filter((r) => r.recipient_id === user?.id);
    if (filter === 'outgoing') return all.filter((r) => r.requester_id === user?.id);
    return all;
  }, [data, filter, user?.id]);

  const busy = respond.isPending || clarify.isPending || cancel.isPending;

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading associations…</span></div>;
  if (error) return <ErrorBlock error={error} />;

  const incomingPending = (data?.associations ?? []).filter((r) => r.recipient_id === user?.id && RESPONDABLE.has(r.status)).length;

  return (
    <SectionCard
      title="Association Requests"
      subtitle="Requests to link you (or that you sent) to a patent/design record."
      actions={
        <div className="pill-row">
          {(['all', 'incoming', 'outgoing'] as const).map((f) => (
            <button key={f} className={`btn btn-sm ${filter === f ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setFilter(f)}>
              {f === 'incoming' ? `Incoming${incomingPending ? ` (${incomingPending})` : ''}` : f[0].toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      }
    >
      {rows.length === 0 ? (
        <EmptyState message="No association requests to show." />
      ) : (
        <div className="stack">
          {rows.map((r) => {
            const isRecipient = r.recipient_id === user?.id;
            const isRequester = r.requester_id === user?.id;
            const canRespond = isRecipient && RESPONDABLE.has(r.status);
            const canClarifyBack = isRequester && r.status === 'CLARIFICATION_REQUESTED';
            const canCancel = isRequester && r.status === 'PENDING';
            return (
              <div key={r.id} className="assoc-card">
                <div className="assoc-card-head">
                  <div>
                    <strong>{r.record_title || r.record_id || 'Patent/Design record'}</strong>
                    <div className="muted">
                      {isRecipient ? `From ${r.requester_name || r.requester_id}` : `To ${r.recipient_name || r.recipient_id}`}
                    </div>
                  </div>
                  <StatusBadge value={r.status} />
                </div>
                <div className="assoc-meta">
                  <Meta label="Reason / message" value={r.reason || r.message || '—'} />
                  <Meta label="Clarification" value={r.clarification_message || r.response_reason || '—'} />
                  <Meta label="Created" value={formatDateTime(r.created_at)} />
                  <Meta label="Responded" value={r.responded_at ? formatDateTime(r.responded_at) : '—'} />
                </div>

                {canRespond && (
                  <div className="btn-row">
                    <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => respond.mutate({ id: r.id, action: 'accepted' })}>Accept</button>
                    <button className="btn btn-danger btn-sm" disabled={busy} onClick={() => respond.mutate({ id: r.id, action: 'rejected' })}>Reject</button>
                    <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => { setNotMeFor(r); setReason(''); }}>Not me</button>
                    <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => { setClarifyFor(r); setReason(''); }}>Request clarification</button>
                  </div>
                )}
                {canClarifyBack && (
                  <div className="btn-row">
                    <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => { setClarifyFor(r); setReason(''); }}>Provide clarification</button>
                  </div>
                )}
                {canCancel && (
                  <div className="btn-row">
                    <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => cancel.mutate(r.id)}>Cancel request</button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {clarifyFor && (
        <Modal
          title={clarifyFor.recipient_id === user?.id ? 'Request clarification' : 'Provide clarification'}
          onClose={() => setClarifyFor(null)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => setClarifyFor(null)}>Cancel</button>
              <button
                className="btn btn-primary"
                disabled={busy || reason.trim().length === 0}
                onClick={() => {
                  if (clarifyFor.recipient_id === user?.id) respond.mutate({ id: clarifyFor.id, action: 'clarification_requested', text: reason.trim() });
                  else clarify.mutate({ id: clarifyFor.id, message: reason.trim() });
                }}
              >
                Send
              </button>
            </>
          }
        >
          <label className="field">
            <span>{clarifyFor.recipient_id === user?.id ? 'What do you need clarified?' : 'Your response'}</span>
            <textarea className="toolbar-input" rows={4} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Type a message…" />
          </label>
        </Modal>
      )}

      {notMeFor && (
        <Modal
          title="Mark as 'Not me'"
          onClose={() => setNotMeFor(null)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => setNotMeFor(null)}>Cancel</button>
              <button className="btn btn-danger" disabled={busy} onClick={() => respond.mutate({ id: notMeFor.id, action: 'not_me', text: reason.trim() || undefined })}>Confirm — this isn't me</button>
            </>
          }
        >
          <p>Confirm that the record in this request does <strong>not</strong> belong to you. The requester will be notified to correct the contributor.</p>
          <label className="field">
            <span>Optional note</span>
            <textarea className="toolbar-input" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. same name, different person" />
          </label>
        </Modal>
      )}
    </SectionCard>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return <div className="detail-field"><span>{label}</span><strong>{value}</strong></div>;
}

function friendly(e: ApiError): string {
  if (e.status === 403) return 'Only the recipient may respond to this request.';
  if (e.status === 409) return 'This request was already handled.';
  return e.message || 'Action failed';
}

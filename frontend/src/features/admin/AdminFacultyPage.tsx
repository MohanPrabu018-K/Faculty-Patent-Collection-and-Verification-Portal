import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import {
  SectionCard, StatusBadge, LoadingBlock, ErrorBlock, EmptyState,
  Toolbar, TableWrap, Pagination, Modal, formatDate, display,
} from '../../components/ui';
import { useToast } from '../../stores/toast';

type FacultyRow = Record<string, unknown>;

const EMPTY_FORM = { full_name: '', email: '', official_email: '', faculty_id: '', department_id: '', designation_id: '', joining_date: '', is_active: true };

export function AdminFacultyPage() {
  const client = useQueryClient();
  const { notify } = useToast();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [dept, setDept] = useState('');
  const [active, setActive] = useState('');
  const [viewing, setViewing] = useState<string | null>(null);
  const [editing, setEditing] = useState<FacultyRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<Record<string, unknown>>(EMPTY_FORM);

  const params = useMemo(() => {
    const q = new URLSearchParams({ page: String(page), per_page: '20' });
    if (search) q.set('search', search);
    if (dept) q.set('department_id', dept);
    if (active) q.set('is_active', active);
    return `?${q.toString()}`;
  }, [page, search, dept, active]);

  const list = useQuery({ queryKey: ['admin-faculty', params], queryFn: () => api.adminFaculty(params) });
  const departments = useQuery({ queryKey: ['admin-departments'], queryFn: api.adminDepartments });
  const designations = useQuery({ queryKey: ['admin-designations'], queryFn: api.adminDesignations });
  const detail = useQuery({ queryKey: ['admin-faculty-detail', viewing], queryFn: () => api.adminFacultyDetail(viewing as string), enabled: Boolean(viewing) });

  const refresh = () => client.invalidateQueries({ queryKey: ['admin-faculty'] });

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.adminCreateFaculty(clean(body)),
    onSuccess: async () => { notify('success', 'Faculty created'); setCreating(false); setForm(EMPTY_FORM); await refresh(); },
    onError: (e) => notify('error', e instanceof Error ? e.message : 'Create failed'),
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api.adminUpdateFaculty(id, clean(body)),
    onSuccess: async () => { notify('success', 'Faculty updated'); setEditing(null); await refresh(); },
    onError: (e) => notify('error', e instanceof Error ? e.message : 'Update failed'),
  });
  const toggleActive = useMutation({
    mutationFn: ({ id, activate }: { id: string; activate: boolean }) => (activate ? api.adminActivateFaculty(id) : api.adminDeactivateFaculty(id)),
    onSuccess: async () => { notify('success', 'Status updated'); await refresh(); },
    onError: () => notify('error', 'Failed to update status'),
  });

  if (list.isLoading) return <LoadingBlock label="Loading faculty…" />;
  if (list.error) return <ErrorBlock error={list.error} />;

  const rows = list.data?.faculty ?? [];
  const totalPages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.per_page)) : 1;
  const deptList = departments.data?.departments ?? [];
  const desigList = designations.data?.designations ?? [];

  const openEdit = (r: FacultyRow) => {
    setEditing(r);
    setForm({
      full_name: r.full_name ?? '', email: r.email ?? '', official_email: r.official_email ?? '',
      faculty_id: r.faculty_id ?? '', department_id: r.department_id ?? '', designation_id: r.designation_id ?? '',
      joining_date: r.joining_date ? String(r.joining_date).slice(0, 10) : '', is_active: r.is_active ?? true,
    });
  };

  return (
    <SectionCard
      title="Faculty Management"
      subtitle={`${list.data?.total ?? 0} faculty in the institution.`}
      actions={<button className="btn btn-sm btn-primary" onClick={() => { setForm(EMPTY_FORM); setCreating(true); }}>Add faculty</button>}
    >
      <Toolbar>
        <input className="toolbar-input" placeholder="Search name, ID, email" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} aria-label="Search faculty" />
        <select className="toolbar-input" value={dept} onChange={(e) => { setDept(e.target.value); setPage(1); }} aria-label="Filter department">
          <option value="">All departments</option>
          {deptList.map((d) => <option key={String(d.id)} value={String(d.id)}>{String(d.name)}</option>)}
        </select>
        <select className="toolbar-input" value={active} onChange={(e) => { setActive(e.target.value); setPage(1); }} aria-label="Filter status">
          <option value="">Any status</option>
          <option value="true">Active</option>
          <option value="false">Inactive</option>
        </select>
      </Toolbar>

      {rows.length === 0 ? (
        <EmptyState message="No faculty match your filters." />
      ) : (
        <TableWrap>
          <table className="data-table">
            <thead>
              <tr><th>Name</th><th>Faculty ID</th><th>Department</th><th>Designation</th><th>Email</th><th>Patents</th><th>Documents</th><th>Status</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const c = (r.counts ?? {}) as Record<string, number>;
                return (
                  <tr key={String(r.id)}>
                    <td><strong>{display(r.full_name)}</strong></td>
                    <td>{display(r.faculty_id)}</td>
                    <td>{display(r.department_name)}</td>
                    <td>{display(r.designation_name)}</td>
                    <td>{display(r.email)}</td>
                    <td>{c.patents ?? 0}</td>
                    <td>{c.documents ?? 0}</td>
                    <td><StatusBadge value={r.is_active ? 'ACTIVE' : 'INACTIVE'} /></td>
                    <td>
                      <div className="btn-row">
                        <button className="btn btn-sm btn-secondary" onClick={() => setViewing(String(r.id))}>View</button>
                        <button className="btn btn-sm btn-secondary" onClick={() => openEdit(r)}>Edit</button>
                        <button className="btn btn-sm btn-ghost" disabled={toggleActive.isPending} onClick={() => toggleActive.mutate({ id: String(r.id), activate: !r.is_active })}>
                          {r.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
      )}
      <Pagination page={page} totalPages={totalPages} onChange={setPage} disabled={list.isFetching} />

      {viewing && (
        <Modal title="Faculty profile" onClose={() => setViewing(null)}>
          {detail.isLoading ? <LoadingBlock /> : detail.error ? <ErrorBlock error={detail.error} /> : detail.data ? (
            <div className="kv-grid">
              {[
                ['Full name', detail.data.full_name], ['Faculty ID', detail.data.faculty_id],
                ['Email', detail.data.email], ['Official email', detail.data.official_email],
                ['Department', detail.data.department_name], ['Designation', detail.data.designation_name],
                ['Joined', detail.data.joining_date ? formatDate(detail.data.joining_date) : '—'],
                ['Status', detail.data.status],
              ].map(([k, v]) => <div key={String(k)} className="detail-field"><span>{String(k)}</span><strong>{display(v)}</strong></div>)}
            </div>
          ) : null}
        </Modal>
      )}

      {(creating || editing) && (
        <Modal
          title={creating ? 'Add faculty' : 'Edit faculty'}
          onClose={() => { setCreating(false); setEditing(null); }}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => { setCreating(false); setEditing(null); }}>Cancel</button>
              <button
                className="btn btn-primary"
                disabled={create.isPending || update.isPending || !form.full_name || !form.email}
                onClick={() => {
                  if (creating) create.mutate(form);
                  else if (editing) update.mutate({ id: String(editing.id), body: form });
                }}
              >
                {creating ? 'Create' : 'Save changes'}
              </button>
            </>
          }
        >
          <FormField label="Full name *"><input className="toolbar-input" value={String(form.full_name ?? '')} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></FormField>
          <FormField label="Email *"><input className="toolbar-input" type="email" value={String(form.email ?? '')} onChange={(e) => setForm({ ...form, email: e.target.value })} /></FormField>
          <FormField label="Official email"><input className="toolbar-input" value={String(form.official_email ?? '')} onChange={(e) => setForm({ ...form, official_email: e.target.value })} /></FormField>
          <FormField label="Faculty ID"><input className="toolbar-input" value={String(form.faculty_id ?? '')} onChange={(e) => setForm({ ...form, faculty_id: e.target.value })} placeholder="auto-generated if blank" /></FormField>
          <FormField label="Department">
            <select className="toolbar-input" value={String(form.department_id ?? '')} onChange={(e) => setForm({ ...form, department_id: e.target.value })}>
              <option value="">—</option>
              {deptList.map((d) => <option key={String(d.id)} value={String(d.id)}>{String(d.name)}</option>)}
            </select>
          </FormField>
          <FormField label="Designation">
            <select className="toolbar-input" value={String(form.designation_id ?? '')} onChange={(e) => setForm({ ...form, designation_id: e.target.value })}>
              <option value="">—</option>
              {desigList.map((d) => <option key={String(d.id)} value={String(d.id)}>{String(d.name || d.title)}</option>)}
            </select>
          </FormField>
          <FormField label="Joining date"><input className="toolbar-input" type="date" value={String(form.joining_date ?? '')} onChange={(e) => setForm({ ...form, joining_date: e.target.value })} /></FormField>
          <label className="pill-row" style={{ gap: 6 }}>
            <input type="checkbox" checked={Boolean(form.is_active)} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
            <span>Active</span>
          </label>
        </Modal>
      )}
    </SectionCard>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="field"><span>{label}</span>{children}</label>;
}

function clean(body: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(body)) {
    if (v === '' || v === undefined) continue;
    out[k] = v;
  }
  return out;
}

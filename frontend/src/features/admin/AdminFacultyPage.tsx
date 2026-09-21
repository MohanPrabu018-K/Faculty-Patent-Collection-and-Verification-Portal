import { useMemo, useState } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import {
  SectionCard, StatusBadge, ErrorBlock, EmptyState,
  Toolbar, TableWrap, Pagination, Modal, formatDate, display,
} from '../../components/ui';
import { useToast } from '../../stores/toast';
import { useDebounce } from '../../hooks/useDebounce';

type FacultyRow = Record<string, unknown>;

const REQUIRED_DEPTS = [
  "Artificial Intelligence and Data Science",
  "Computer Science and Engineering",
  "Cyber Security",
  "Information and Technology",
  "Electronics and Communication Engineering",
  "Electrical and Electronics Engineering",
  "Mechanical Engineering",
  "Artificial Intelligence and Machine Learning",
];

const EMPTY_FORM = { full_name: '', email: '', official_email: '', faculty_id: '', department_id: '', designation_id: '', joining_date: '', is_active: true, password: '' };

export function AdminFacultyPage() {
  const client = useQueryClient();
  const { notify } = useToast();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 400);
  const [dept, setDept] = useState('');
  const [active, setActive] = useState('');
  const [viewing, setViewing] = useState<string | null>(null);
  const [editing, setEditing] = useState<FacultyRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<Record<string, unknown>>(EMPTY_FORM);
  const [createdTempPassword, setCreatedTempPassword] = useState<string | null>(null);

  const params = useMemo(() => {
    const q = new URLSearchParams({ page: String(page), per_page: '20' });
    if (debouncedSearch.trim()) q.set('search', debouncedSearch.trim());
    if (dept) q.set('department_id', dept);
    if (active) q.set('is_active', active);
    return `?${q.toString()}`;
  }, [page, debouncedSearch, dept, active]);

  const list = useQuery({ queryKey: ['admin-faculty', params], queryFn: ({ signal }) => api.adminFaculty(params, signal), placeholderData: keepPreviousData });
  const departments = useQuery({ queryKey: ['admin-departments'], queryFn: api.adminDepartments });
  const designations = useQuery({ queryKey: ['admin-designations'], queryFn: api.adminDesignations });
  const detail = useQuery({ queryKey: ['admin-faculty-detail', viewing], queryFn: () => api.adminFacultyDetail(viewing as string), enabled: Boolean(viewing) });

  const refresh = () => client.invalidateQueries({ queryKey: ['admin-faculty'] });

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.adminCreateFaculty(clean(body)),
    onSuccess: async (data) => {
      if (data?.temporary_password && data.temporary_password_generated) {
        setCreatedTempPassword(data.temporary_password);
      } else {
        notify('success', 'Faculty created');
      }
      setCreating(false);
      setForm(EMPTY_FORM);
      await refresh();
    },
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

  const rows = list.data?.faculty ?? [];

  if (list.error && rows.length === 0) return <ErrorBlock error={list.error} />;
  const totalPages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.per_page)) : 1;
  const rawDeptList = departments.data?.departments ?? [];
  const rawDesigList = designations.data?.designations ?? [];
  // MUST contain exactly required departments; filter to canonical 8; fallback to raw if seed missing
  const deptList = rawDeptList.filter((d: any) => REQUIRED_DEPTS.includes(String(d.name))) .length === 8
    ? rawDeptList.filter((d: any) => REQUIRED_DEPTS.includes(String(d.name))).sort((a: any, b: any) => REQUIRED_DEPTS.indexOf(String(a.name)) - REQUIRED_DEPTS.indexOf(String(b.name)))
    : rawDeptList;
  const allowedDesigs = rawDesigList.filter((d: any) => ["Faculty", "HOD"].includes(String(d.title || d.name)));
  const desigList = allowedDesigs.length >= 2 ? allowedDesigs.filter((d: any) => ["Faculty", "HOD"].includes(String(d.title || d.name))) : rawDesigList.filter((d: any) => ["Faculty", "HOD"].includes(String(d.title)));
  // If still empty (e.g. seed not loaded yet), synthesize from required list for UI correctness
  const displayDeptList = deptList.length ? deptList : REQUIRED_DEPTS.map((n, i) => ({ id: `dept-${i}`, name: n }));
  const displayDesigList = desigList.length ? desigList : [{ id: 'desig-faculty', title: 'Faculty', name: 'Faculty' }, { id: 'desig-hod', title: 'HOD', name: 'HOD' }];

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
        <input className="toolbar-input" placeholder="Search name, ID, email (debounced 400ms)" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} aria-label="Search faculty" />
        <select className="toolbar-input" value={dept} onChange={(e) => { setDept(e.target.value); setPage(1); }} aria-label="Filter department">
          <option value="">All departments</option>
          {displayDeptList.map((d: any) => <option key={String((d as any).id)} value={String((d as any).id)}>{String((d as any).name)}</option>)}
        </select>
        <select className="toolbar-input" value={active} onChange={(e) => { setActive(e.target.value); setPage(1); }} aria-label="Filter status">
          <option value="">Any status</option>
          <option value="true">Active</option>
          <option value="false">Inactive</option>
        </select>
      </Toolbar>

      {list.error && rows.length > 0 ? (
        <div className="alert alert-error" role="alert" style={{ marginBottom: 12 }}>
          Search failed: {list.error instanceof Error ? list.error.message : String(list.error)}{' '}
          <button className="btn btn-sm btn-secondary" onClick={() => void list.refetch()} disabled={list.isFetching}>Retry</button>
        </div>
      ) : null}

      {list.isLoading && rows.length === 0 ? (
        <div className="loading-inline" style={{ padding: '16px 0' }}><span className="spinner" /><span>Loading faculty…</span></div>
      ) : rows.length === 0 ? (
        <EmptyState message="No faculty match your filters." />
      ) : (
        <div className={list.isFetching ? 'table-fetching' : ''}>
          {list.isFetching && <div className="table-fetching-indicator"><span className="spinner" /> Updating…</div>}
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
        </div>
      )}
      <Pagination page={page} totalPages={totalPages} onChange={setPage} disabled={list.isFetching} />

      {viewing && (
        <Modal title="Faculty profile" onClose={() => setViewing(null)}>
          {detail.isLoading ? <div className="loading-inline"><span className="spinner" /><span>Loading profile…</span></div> : detail.error ? <ErrorBlock error={detail.error} /> : detail.data ? (
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
          {creating && <FormField label="Initial Password"><input className="toolbar-input" type="password" value={String(form.password ?? '')} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="Optional — a temporary password is generated if left blank" /></FormField>}
          <FormField label="Department">
            <select className="toolbar-input" value={String(form.department_id ?? '')} onChange={(e) => setForm({ ...form, department_id: e.target.value })}>
              <option value="">—</option>
              {displayDeptList.map((d: any) => <option key={String(d.id)} value={String(d.id)}>{String(d.name)}</option>)}
            </select>
          </FormField>
          <FormField label="Designation (Faculty=HOD gives HOD permissions)">
            <select className="toolbar-input" value={String(form.designation_id ?? '')} onChange={(e) => setForm({ ...form, designation_id: e.target.value })}>
              <option value="">—</option>
              {displayDesigList.map((d: any) => <option key={String(d.id)} value={String(d.id)}>{String(d.title || d.name)}</option>)}
            </select>
          </FormField>
          <FormField label="Joining date"><input className="toolbar-input" type="date" value={String(form.joining_date ?? '')} onChange={(e) => setForm({ ...form, joining_date: e.target.value })} /></FormField>
          <label className="pill-row" style={{ gap: 6 }}>
            <input type="checkbox" checked={Boolean(form.is_active)} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
            <span>Active</span>
          </label>
        </Modal>
      )}
      {createdTempPassword && (
        <Modal
          title="Account created — save the temporary password"
          onClose={() => setCreatedTempPassword(null)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => { void navigator.clipboard?.writeText(createdTempPassword); }}>Copy password</button>
              <button className="btn btn-primary" onClick={() => setCreatedTempPassword(null)}>Done</button>
            </>
          }
        >
          <p className="alert alert-info" style={{ marginBottom: 12 }}>
            Account created. A temporary password was generated. Copy it now and securely share it with the faculty member. It will not be shown again.
          </p>
          <FormField label="Temporary password">
            <code className="toolbar-input" style={{ display: 'block', userSelect: 'all', wordBreak: 'break-all' }}>{createdTempPassword}</code>
          </FormField>
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

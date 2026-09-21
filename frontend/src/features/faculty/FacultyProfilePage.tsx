import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { SectionCard, StatCard, ErrorBlock, formatDate, display } from '../../components/ui';

export function FacultyProfilePage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['faculty-profile'], queryFn: api.facultyProfile });

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading profile…</span></div>;
  if (error) return <ErrorBlock error={error} />;
  if (!data) return <ErrorBlock error="Profile unavailable" />;

  const c = data.counts;

  return (
    <div className="stack-lg">
      <SectionCard title="My Profile" subtitle="Account details from the institution's faculty master.">
        <div className="kv-grid">
          <Field label="Full name" value={data.full_name} />
          <Field label="Faculty ID" value={data.faculty_id} />
          <Field label="Email" value={data.email} />
          <Field label="Official email" value={data.official_email} />
          <Field label="Department" value={data.department_name || data.department_id} />
          <Field label="Designation" value={data.designation_name || data.designation_id} />
          <Field label="Role" value={data.role} />
          <Field label="Account status" value={data.status} />
          <Field label="Joined" value={data.joining_date ? formatDate(data.joining_date) : '—'} />
          <Field label="Created" value={data.created_at ? formatDate(data.created_at) : '—'} />
        </div>
        <p className="muted" style={{ marginTop: 14 }}>
          Profile fields are managed by your department admin. Contact them to request a change.
        </p>
      </SectionCard>

      {c && (
        <SectionCard title="My Portfolio" subtitle="Live counts across your submissions.">
          <div className="grid stats-grid">
            <StatCard label="Total documents" value={c.total_documents} />
            <StatCard label="Patents" value={c.patents} />
            <StatCard label="Designs" value={c.designs} />
            <StatCard label="Verified" value={c.verified} />
            <StatCard label="Awaiting review" value={c.awaiting_review} />
            <StatCard label="Pending verification" value={c.pending_verification} />
          </div>
        </SectionCard>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: unknown }) {
  return <div className="detail-field"><span>{label}</span><strong>{display(value)}</strong></div>;
}

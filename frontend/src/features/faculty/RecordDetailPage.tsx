import { useParams } from 'react-router-dom';
import { isValidElement, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { SectionCard, StatusBadge } from '../../components/ui';

function display(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Not available';
  if (Array.isArray(value)) return value.length ? value.map(display).join(', ') : 'Not available';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function SectionField({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="detail-field"><span>{label}</span><strong>{value}</strong></div>;
}

function renderValue(value: unknown): React.ReactNode {
  return isValidElement(value) ? value : display(value);
}

function SectionList({ items }: { items: Array<{ label: string; value: unknown }> }) {
  return <div className="grid detail-grid">{items.map((item) => <SectionField key={item.label} label={item.label} value={renderValue(item.value)} />)}</div>;
}

function Timeline({ jobs }: { jobs: Array<Record<string, unknown>> }) {
  if (jobs.length === 0) return <div className="empty-cell">No processing timeline is available yet.</div>;
  return <div className="timeline">{jobs.map((job, index) => <div key={`${String(job.job_type || index)}`} className="timeline-item"><div className="timeline-dot">{index + 1}</div><div><strong>{display(job.job_type || `Stage ${index + 1}`)}</strong><div className="muted">Status: {display(job.status)}</div><div className="muted">Updated: {display(job.completed_at || job.created_at)}</div></div></div>)}</div>;
}

function KeyValueBlock({ title, value }: { title: string; value: unknown }) {
  return <div className="mini-card"><div className="muted">{title}</div><strong>{renderValue(value)}</strong></div>;
}

export function RecordDetailPage() {
  const { recordId } = useParams();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const { data, isLoading, error } = useQuery({ queryKey: ['faculty-record', recordId], queryFn: () => api.facultyRecordStatus(recordId || ''), enabled: Boolean(recordId) });

  const review = useMutation({
    mutationFn: (corrections: Record<string, unknown>) => api.facultyRecordReview(recordId || '', corrections),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['faculty-record', recordId] }),
  });

  if (isLoading) return <div className="page-center">Loading record details...</div>;
  if (error) return <div className="alert alert-error">{String(error)}</div>;

  const record = (data ?? {}) as Record<string, unknown>;
  const jobs = Array.isArray(record.jobs) ? record.jobs as Array<Record<string, unknown>> : [];
  const contributors = Array.isArray(record.contributors) ? record.contributors as Array<Record<string, unknown>> : [];
  const files = Array.isArray(record.files) ? record.files as Array<Record<string, unknown>> : [];
  const provenance = Array.isArray(record.field_provenance) ? record.field_provenance as Array<Record<string, unknown>> : [];
  const evidence = record.evidence && typeof record.evidence === 'object' ? record.evidence as Record<string, unknown> : {};
  const qrData = Array.isArray(record.qr_data) ? record.qr_data : [];

  const reviewableFields: Array<{ key: string; label: string; value: unknown }> = [
    { key: 'title', label: 'Title', value: record.title },
    { key: 'applicant', label: 'Applicant', value: record.applicant },
    { key: 'patentee', label: 'Patentee', value: record.patentee },
    { key: 'patent_number', label: 'Patent number', value: record.patent_number },
    { key: 'design_number', label: 'Design number', value: record.design_number },
    { key: 'application_number', label: 'Application number', value: record.application_number },
    { key: 'serial_number', label: 'Serial number', value: record.serial_number },
    { key: 'filing_date', label: 'Filing date', value: record.filing_date },
    { key: 'grant_date', label: 'Grant date', value: record.grant_date },
    { key: 'published_date', label: 'Published date', value: record.published_date },
  ];

  return (
    <div className="stack-lg">
      <SectionCard title="Document Information" subtitle="Core submission metadata from the backend.">
        <SectionList items={[
          { label: 'Record ID', value: record.record_id || record.id },
          { label: 'Document title', value: record.title },
          { label: 'IP type', value: record.ip_type },
          { label: 'Patent number', value: record.patent_number },
          { label: 'Design number', value: record.design_number },
          { label: 'Application number', value: record.application_number },
          { label: 'Serial number', value: record.serial_number },
          { label: 'Certificate type', value: record.certificate_type },
        ]} />
      </SectionCard>

      <SectionCard title="Processing Status" subtitle="Live processing and verification state.">
        <div className="grid stats-grid">
          <KeyValueBlock title="Processing" value={<StatusBadge value={String(record.processing_status || 'PENDING')} />} />
          <KeyValueBlock title="Verification" value={<StatusBadge value={String(record.verification_status || 'UNVERIFIED')} />} />
          <KeyValueBlock title="Created" value={record.created_at} />
          <KeyValueBlock title="Updated" value={record.updated_at} />
        </div>
      </SectionCard>

      <SectionCard title="Extracted Information" subtitle="Structured values parsed from the uploaded document.">
        <SectionList items={[
          { label: 'Applicant', value: record.applicant },
          { label: 'Patentee', value: record.patentee },
          { label: 'Contributor name', value: record.contributor_name },
          { label: 'Contributor designation', value: record.contributor_designation },
          { label: 'Contributor department', value: record.contributor_department },
          { label: 'Contributor country', value: record.contributor_country },
          { label: 'Filing date', value: record.filing_date },
          { label: 'Grant date', value: record.grant_date },
          { label: 'Published date', value: record.published_date },
          { label: 'QR data', value: qrData.length ? qrData.join(', ') : null },
        ]} />
      </SectionCard>

      <SectionCard title="Faculty Information" subtitle="Faculty-linked data available for this record.">
        <SectionList items={[
          { label: 'Faculty name', value: record.faculty_name },
          { label: 'Faculty ID', value: record.faculty_id },
          { label: 'Department', value: record.department_name || record.department_id },
          { label: 'Designation', value: record.designation_name || record.designation_id },
          { label: 'Uploader', value: record.uploader_name || record.uploader_id },
          { label: 'Source reference', value: record.source_reference },
        ]} />
      </SectionCard>

      <SectionCard title="Contributors / Associations" subtitle="Associated contributors and linked request records.">
        {contributors.length === 0 ? <div className="empty-cell">No contributors are available yet.</div> : <div className="stack">{contributors.map((contributor) => <div key={String(contributor.id || contributor.name)} className="mini-card"><strong>{display(contributor.name)}</strong><div className="muted">{display(contributor.designation)} ? {display(contributor.department)}</div><div className="muted">{contributor.is_external ? 'External contributor' : 'Internal contributor'} ? Order {display(contributor.contributor_order)}</div></div>)}</div>}
      </SectionCard>

      <SectionCard title="Verification" subtitle="Backend verification evidence and state.">
        <SectionList items={[
          { label: 'Verification status', value: <StatusBadge value={String(record.verification_status || 'UNVERIFIED')} /> },
          { label: 'Evidence type', value: evidence.evidence_type },
          { label: 'Matched source', value: evidence.source },
          { label: 'Confidence', value: evidence.confidence },
          { label: 'Evidence notes', value: evidence.notes },
        ]} />
      </SectionCard>

      <SectionCard title="Workflow & Master Record" subtitle="Where this submission sits in the verification lifecycle.">
        <SectionList items={[
          { label: 'Workflow state', value: record.workflow_state ? <StatusBadge value={String(record.workflow_state)} /> : null },
          { label: 'Master IP record', value: record.master_ip_id },
          { label: 'Department (at upload)', value: record.department_name || record.department_id },
        ]} />
      </SectionCard>

      <SectionCard title="Duplicate Detection" subtitle="Duplicate flags from backend processing.">
        <SectionList items={[
          { label: 'Duplicate status', value: record.duplicate_status ? <StatusBadge value={String(record.duplicate_status)} /> : 'None detected' },
          { label: 'Duplicate case ID', value: record.duplicate_case_id },
          { label: 'Match confidence', value: record.duplicate_confidence != null ? `${Math.round(Number(record.duplicate_confidence) * 100)}%` : null },
          { label: 'Duplicate of record', value: record.duplicate_of_record_id },
        ]} />
      </SectionCard>

      <SectionCard title="Conflict Detection" subtitle="Conflict flags and resolution status.">
        <SectionList items={[
          { label: 'Conflict status', value: record.conflict_status ? <StatusBadge value={String(record.conflict_status)} /> : 'None detected' },
          { label: 'Conflict type', value: record.conflict_type },
          { label: 'Conflict description', value: record.conflict_description },
        ]} />
      </SectionCard>

      <SectionCard title="Review & Confirm" subtitle="Confirm or correct the extracted fields. Corrections are stored with full provenance.">
        {review.isSuccess ? <div className="alert alert-success">Review submitted successfully.</div> : review.isError ? <div className="alert alert-error">{String(review.error)}</div> : null}
        <div className="stack">
          {reviewableFields.map((field) => (
            <label key={field.key} className="field">
              <span>{field.label}</span>
              <input
                className="toolbar-input"
                defaultValue={display(field.value)}
                placeholder="Not available"
                onChange={(event) => {
                  const value = event.target.value;
                  setDraft((prev) => {
                    const next = { ...prev };
                    if (value === '' || value === 'Not available') delete next[field.key];
                    else next[field.key] = value;
                    return next;
                  });
                }}
              />
            </label>
          ))}
          <button
            type="button"
            className="btn btn-primary"
            disabled={review.isPending || Object.keys(draft).length === 0}
            onClick={() => review.mutate(draft)}
          >
            {review.isPending ? 'Submitting…' : 'Submit review'}
          </button>
        </div>
      </SectionCard>

      <SectionCard title="Field Provenance" subtitle="Source-of-truth for each extracted field.">
        {provenance.length === 0 ? <div className="empty-cell">No provenance records are available yet.</div> : <div className="table-wrap"><table className="data-table"><thead><tr><th>Field</th><th>Value</th><th>Source</th><th>Confidence</th><th>Status</th></tr></thead><tbody>{provenance.map((p) => <tr key={String(p.id)}><td>{display(p.field_name)}</td><td>{display(p.value)}</td><td>{display(p.source)}</td><td>{display(p.confidence)}</td><td><StatusBadge value={String(p.status || 'PENDING')} /></td></tr>)}</tbody></table></div>}
      </SectionCard>

      <SectionCard title="Processing Timeline" subtitle="Task activity and stage progression.">
        <Timeline jobs={jobs} />
      </SectionCard>

      <SectionCard title="Processing / Agent Summary" subtitle="Per-task results when the backend exposes them.">
        {jobs.length === 0 ? <div className="empty-cell">No processing summary is available yet.</div> : <div className="stack">{jobs.map((job, index) => <div key={String(job.job_type || index)} className="mini-card"><strong>{display(job.job_type || `Job ${index + 1}`)}</strong><div className="muted">Status: {display(job.status)}</div><div className="muted">Result: {display(job.result)}</div><div className="muted">Error: {display(job.error_message)}</div></div>)}</div>}
      </SectionCard>

      <SectionCard title="Files" subtitle="Uploaded source files linked to this record.">
        {files.length === 0 ? <div className="empty-cell">No file metadata is available.</div> : <div className="stack">{files.map((file) => <div key={String(file.id)} className="mini-card"><strong>{display(file.original_filename)}</strong><div className="muted">{display(file.mime_type)} ? {display(file.file_size_bytes)} bytes</div><div className="muted">Pages: {display(file.page_count)} ? Upload status: {display(file.upload_status)}</div></div>)}</div>}
      </SectionCard>
    </div>
  );
}



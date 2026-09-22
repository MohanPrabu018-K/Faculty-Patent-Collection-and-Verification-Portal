import { useParams } from 'react-router-dom';
import { isValidElement, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, api } from '../../api/client';
import { useAuth } from '../../stores/auth';
import { SectionCard, StatusBadge } from '../../components/ui';
import { associationSendState } from './associationEligibility';

function display(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Not available';
  if (Array.isArray(value)) return value.length ? value.map(display).join(', ') : 'Not available';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function displayApplicant(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Not clearly identified in document';
  if (typeof value === 'string' && value.trim().startsWith('{"')) return 'Not clearly identified in document';
  return display(value);
}

function shortRef(value: unknown): string {
  const text = String(value ?? '');
  return text.length > 8 ? `${text.slice(0, 8)}…` : display(value);
}

function workflowGuidance(state: unknown): string | null {
  switch (String(state ?? '')) {
    case 'FACULTY_APPROVAL_PENDING':
      return 'What you need to do: ask each listed internal faculty member to accept the association request.';
    case 'DUPLICATE_REVIEW':
      return 'What you need to do: compare with the existing record below. No action is needed unless the records are unrelated.';
    case 'NEEDS_REVIEW':
      return 'What you need to do: confirm or correct the extracted fields in Review & Confirm.';
    case 'VERIFIED':
      return 'This record has completed verification.';
    default:
      return null;
  }
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
  const { user } = useAuth();
  const showTechnicalDetails = user?.role !== 'faculty';
  const [draft, setDraft] = useState<Record<string, string>>({});
  const { data, isLoading, error } = useQuery({ queryKey: ['faculty-record', recordId], queryFn: () => api.facultyRecordStatus(recordId || ''), enabled: Boolean(recordId) });

  const review = useMutation({
    mutationFn: (corrections: Record<string, unknown>) => api.facultyRecordReview(recordId || '', corrections),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['faculty-record', recordId] }),
  });

  const [downloadError, setDownloadError] = useState('');
  const downloadFile = async (fileId: string, filename: string) => {
    setDownloadError('');
    try {
      await api.downloadRecordFile(recordId || '', fileId, filename);
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : 'Download failed');
    }
  };

  // Uploader-only association requests. Hooks must stay above the early
  // returns. Creation always goes through the existing POST /associations/
  // endpoint (backend enforces uploader authorization + duplicate
  // prevention); the query only loads the uploader's own sent requests.
  const assocRecord = (data ?? {}) as Record<string, unknown>;
  const assocUploaderId = typeof assocRecord.uploader_id === 'string' ? assocRecord.uploader_id : null;
  const assocViewerIsUploader = Boolean(user?.id && assocUploaderId && user.id === assocUploaderId);
  const { data: assocData } = useQuery({ queryKey: ['associations'], queryFn: api.associations, enabled: Boolean(recordId) && assocViewerIsUploader });
  const [assocFeedback, setAssocFeedback] = useState<{ kind: 'success' | 'error'; text: string } | null>(null);
  const sendAssoc = useMutation({
    mutationFn: ({ facultyId }: { facultyId: string; name: string; ckey: string }) =>
      api.sendAssociation(facultyId, { record_id: String(recordId || ''), reason: 'Please confirm your contribution to this record.' }),
    onSuccess: async (_res, vars) => {
      setAssocFeedback({ kind: 'success', text: `Association request sent to ${vars.name}.` });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['associations'] }),
        queryClient.invalidateQueries({ queryKey: ['faculty-record', recordId] }),
      ]);
    },
    onError: async (err, vars) => {
      if (err instanceof ApiError && err.status === 409) {
        // A live request already exists: adopt the pending state, no duplicate.
        setAssocFeedback({ kind: 'success', text: `A request already exists for ${vars.name} — showing as sent.` });
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ['associations'] }),
          queryClient.invalidateQueries({ queryKey: ['faculty-record', recordId] }),
        ]);
        return;
      }
      setAssocFeedback({ kind: 'error', text: err instanceof Error ? `Could not send request to ${vars.name}: ${err.message}` : `Could not send request to ${vars.name}.` });
    },
  });

  if (isLoading && !data) return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading record details…</span></div>;
  if (error) return <div className="alert alert-error">{String(error)}</div>;

  const record = (data ?? {}) as Record<string, unknown>;
  const jobs = Array.isArray(record.jobs) ? record.jobs as Array<Record<string, unknown>> : [];
  const contributors = Array.isArray(record.contributors) ? record.contributors as Array<Record<string, unknown>> : [];
  const assocRows = assocData?.associations ?? [];
  const files = Array.isArray(record.files) ? record.files as Array<Record<string, unknown>> : [];
  const provenance = Array.isArray(record.field_provenance) ? record.field_provenance as Array<Record<string, unknown>> : [];
  const evidence = record.evidence && typeof record.evidence === 'object' ? record.evidence as Record<string, unknown> : {};
  const qrData = Array.isArray(record.qr_data) ? record.qr_data : [];
  const isDesign = record.ip_type === 'DESIGN_REGISTRATION';
  const sharedIdentifier = record.design_number || record.application_number || record.patent_number;
  const guidance = workflowGuidance(record.workflow_state);
  const hasDuplicate = Boolean(record.duplicate_case_id || record.duplicate_status);
  const hasConflict = Boolean(record.conflict_status);

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

  // Uploader-only review: the backend enforces `record.uploader_id == current_user.id`
  // (see POST /faculty/{record_id}/review → 403 "Only the uploader may review this record").
  // The "Faculty Information" card shows the *uploader*, not the viewer — so compare the
  // authenticated user against the record's uploader before offering an editable form.
  // Non-uploaders (e.g. admin/HOD viewing via queue links, or contributors) get an honest
  // read-only explanation instead of an enabled button guaranteed to fail with 403.
  const uploaderId = typeof record.uploader_id === 'string' ? record.uploader_id : null;
  const currentUserId = user?.id ?? null;
  const isUploader = Boolean(currentUserId && uploaderId && currentUserId === uploaderId);
  const uploaderDisplayName = display(record.faculty_name) !== 'Not available'
    ? display(record.faculty_name)
    : (uploaderId ? `Uploader ${shortRef(uploaderId)}` : 'The uploader');

  return (
    <div className="stack-lg">
      <SectionCard title="Document Information" subtitle="What this uploaded document represents.">
        <SectionList items={[
          { label: 'Document title', value: record.title },
          { label: 'IP type', value: record.ip_type },
          ...(isDesign
            ? [
              { label: 'Design number', value: record.design_number },
              { label: 'Serial number', value: record.serial_number },
              ...(record.application_number
                ? [{ label: 'Application number', value: record.application_number }]
                : []),
            ]
            : [
              { label: 'Patent number', value: record.patent_number },
              { label: 'Application number', value: record.application_number },
            ]),
          { label: 'Document type', value: record.certificate_type },
          { label: 'Uploaded', value: record.created_at },
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

      <SectionCard title="Extracted Information" subtitle="Important information read from the uploaded document.">
        <SectionList items={[
          { label: 'Applicant', value: displayApplicant(record.applicant) },
          { label: 'Patentee', value: record.patentee },
          ...(isDesign
            ? [
              { label: 'Design number', value: record.design_number },
              { label: 'Serial number', value: record.serial_number },
            ]
            : [
              { label: 'Patent number', value: record.patent_number },
              { label: 'Application number', value: record.application_number },
            ]),
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
        ]} />
      </SectionCard>

      <SectionCard title="Contributors & Associations" subtitle="Everyone named in the document, and their college association state.">
        {assocFeedback ? <div className={assocFeedback.kind === 'success' ? 'alert alert-success' : 'alert alert-error'}>{assocFeedback.text}</div> : null}
        {contributors.length === 0 ? <div className="empty-cell">No contributors are available yet.</div> : <div className="stack">{contributors.map((contributor) => {
          const ckey = String(contributor.id || contributor.name);
          const assocState = associationSendState(contributor, { currentUserId, isUploader, recordId: String(recordId || ''), requests: assocRows });
          const isSending = sendAssoc.isPending && sendAssoc.variables?.ckey === ckey;
          const contributorName = String(contributor.name || 'contributor');
          return (
            <div key={ckey} className="mini-card">
              <strong>{display(contributor.name)}</strong>
              <div className="muted">{contributor.is_external ? 'External contributor — not college faculty' : `Internal faculty${contributor.faculty_id ? ` · ${display(contributor.faculty_id)}` : ''}`}</div>
              <div className="muted">Association: {display(contributor.match_status)}</div>
              {assocState === 'sendable' ? (
                <div style={{ marginTop: 8 }}>
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    disabled={isSending}
                    aria-label={`Send association request to ${contributorName}`}
                    onClick={() => sendAssoc.mutate({ facultyId: String(contributor.faculty_id), name: contributorName, ckey })}
                  >
                    {isSending ? 'Sending…' : 'Send Association Request'}
                  </button>
                </div>
              ) : null}
              {assocState === 'pending' ? <div className="muted" style={{ marginTop: 8 }}>Request Sent · Pending recipient decision</div> : null}
              {assocState === 'accepted' ? <div className="muted" style={{ marginTop: 8 }}>Association Accepted</div> : null}
            </div>
          );
        })}</div>}
      </SectionCard>

      <SectionCard title="Official Verification" subtitle="Automated check against the official IP source. Automated IP India verification is unavailable, so this stays VERIFICATION_REQUIRED until an official source verifies — HOD manual review is recorded separately below, never as an automated pass.">
        <SectionList items={[
          { label: 'Automated official status', value: <StatusBadge value={String(record.verification_status || 'UNVERIFIED')} /> },
          ...((!record.verification_status || record.verification_status === 'VERIFICATION_REQUIRED')
            ? [{ label: 'Reason', value: 'Official IP India automated verification unavailable (government site/session/CAPTCHA limits).' }]
            : []),
          ...(showTechnicalDetails
            ? [
              { label: 'Evidence type', value: evidence.evidence_type },
              { label: 'Matched source', value: evidence.source },
              { label: 'Confidence', value: evidence.confidence },
              { label: 'Evidence notes', value: evidence.notes },
            ]
            : []),
        ]} />
      </SectionCard>

      <InstitutionalVerificationCard recordId={String(recordId || '')} canVerify={user?.role === 'hod_admin' || user?.role === 'super_admin'} />

      <SectionCard title="Workflow & Master Record" subtitle="Where this submission stands, and the master record it belongs to.">
        <SectionList items={[
          { label: 'Workflow state', value: record.workflow_state ? <StatusBadge value={String(record.workflow_state)} /> : null },
          { label: 'Master record', value: record.master_ip_id ? `${shortRef(record.master_ip_id)} · shared by all versions of this IP` : 'Not linked yet' },
        ]} />
        {guidance ? <p className="muted">{guidance}</p> : null}
      </SectionCard>

      {hasDuplicate ? (
        <SectionCard title="Duplicate Review" subtitle="Another submission with the same identifier was found.">
          <SectionList items={[
            { label: 'Result', value: 'Possible duplicate found' },
            { label: 'Shared identifier', value: sharedIdentifier },
            { label: 'Existing record', value: record.duplicate_of_record_id ? shortRef(record.duplicate_of_record_id) : null },
            { label: 'Match', value: record.duplicate_confidence != null ? `${Math.round(Number(record.duplicate_confidence) * 100)}%` : null },
            { label: 'Status', value: record.duplicate_status ? <StatusBadge value={String(record.duplicate_status)} /> : 'Review Required' },
          ]} />
          <p className="muted">Versions of the same design stay linked to one master record. Nothing is verified automatically because of this.</p>
        </SectionCard>
      ) : null}

      {hasConflict && !(hasDuplicate && record.conflict_type === 'duplicate_record') ? (
        <SectionCard title="Conflict Details" subtitle="A data conflict needs attention.">
          <SectionList items={[
            { label: 'Conflict status', value: record.conflict_status ? <StatusBadge value={String(record.conflict_status)} /> : 'None detected' },
            { label: 'Conflict type', value: record.conflict_type },
            { label: 'Conflict description', value: record.conflict_description },
          ]} />
        </SectionCard>
      ) : null}

      <SectionCard title="Review & Confirm" subtitle="Confirm or correct the extracted fields. Corrections are stored with full provenance.">
        {isUploader ? (
          <>
            {review.isSuccess ? <div className="alert alert-success">Review submitted successfully.</div> : review.isError ? <div className="alert alert-error">{String(review.error)}</div> : null}
            <p className="muted">Submit without changes to confirm the extracted values, or edit a field first to submit a correction.</p>
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
                disabled={review.isPending}
                onClick={() => review.mutate(draft)}
              >
                {review.isPending ? 'Submitting…' : 'Submit review'}
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="muted">This record was uploaded by {uploaderDisplayName}. Only the uploader can confirm or correct the extracted fields.</p>
            <div className="stack">
              {reviewableFields.map((field) => (
                <label key={field.key} className="field">
                  <span>{field.label}</span>
                  <input
                    className="toolbar-input"
                    value={display(field.value)}
                    placeholder="Not available"
                    readOnly
                    disabled
                    aria-readonly="true"
                  />
                </label>
              ))}
            </div>
          </>
        )}
      </SectionCard>

      {provenance.length === 0 ? null : (
        <SectionCard title="Field History" subtitle="Corrections recorded for this record.">
          <div className="table-wrap"><table className="data-table"><thead><tr><th>Field</th><th>Value</th><th>Source</th><th>Status</th></tr></thead><tbody>{provenance.map((p) => <tr key={String(p.id)}><td>{display(p.field_name)}</td><td>{display(p.value)}</td><td>{display(p.source)}</td><td><StatusBadge value={String(p.status || 'PENDING')} /></td></tr>)}</tbody></table></div>
        </SectionCard>
      )}

      <SectionCard title="Processing Timeline" subtitle="Where your document is in the process.">
        <Timeline jobs={jobs} />
      </SectionCard>

      {showTechnicalDetails ? (
        <SectionCard title="Processing / Agent Summary" subtitle="Per-task results when the backend exposes them.">
          {jobs.length === 0 ? <div className="empty-cell">No processing summary is available yet.</div> : <div className="stack">{jobs.map((job, index) => <div key={String(job.job_type || index)} className="mini-card"><strong>{display(job.job_type || `Job ${index + 1}`)}</strong><div className="muted">Status: {display(job.status)}</div><div className="muted">Result: {display(job.result)}</div><div className="muted">Error: {display(job.error_message)}</div></div>)}</div>}
        </SectionCard>
      ) : null}

      <SectionCard title="Original File" subtitle="The document you uploaded.">
        {downloadError ? <div className="alert alert-error">{downloadError}</div> : null}
        {files.length === 0 ? <div className="empty-cell">No file metadata is available.</div> : <div className="stack">{files.map((file) => <div key={String(file.id)} className="mini-card"><strong>{display(file.original_filename)}</strong><div className="muted">{display(file.mime_type)} ? {display(file.file_size_bytes)} bytes</div><div className="muted">Pages: {display(file.page_count)} ? Upload status: {display(file.upload_status)}</div><button type="button" className="btn btn-secondary" onClick={() => void downloadFile(String(file.id), String(file.original_filename || 'document'))}>Download</button></div>)}</div>}
      </SectionCard>
    </div>
  );
}

function InstitutionalVerificationCard({ recordId, canVerify }: { recordId: string; canVerify: boolean }) {
  const queryClient = useQueryClient();
  const [decision, setDecision] = useState<'verify' | 'reject' | 'clarification'>('verify');
  const [remarks, setRemarks] = useState('');
  const [evidenceRef, setEvidenceRef] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [result, setResult] = useState<{ final_verification_status: string; workflow_state: string; official_verification_status: string; missing_conditions: string[] } | null>(null);
  const { data, isLoading, error } = useQuery({ queryKey: ['institutional', recordId], queryFn: () => api.institutionalStatus(recordId), enabled: Boolean(recordId) });
  const submit = useMutation({
    mutationFn: () => api.institutionalVerify(recordId, { decision, remarks: remarks || undefined, evidence_ref: evidenceRef || undefined }),
    onSuccess: async (res) => {
      setRemarks(''); setEvidenceRef(''); setConfirmed(false);
      setResult({ final_verification_status: res.final_verification_status, workflow_state: res.workflow_state, official_verification_status: res.official_verification_status, missing_conditions: res.missing_conditions ?? [] });
      await queryClient.invalidateQueries({ queryKey: ['institutional', recordId] });
      await queryClient.invalidateQueries({ queryKey: ['faculty-record', recordId] });
    },
  });
  const inst = (data?.institutional ?? null) as Record<string, unknown> | null;
  const final = (data?.final_verification ?? null) as Record<string, unknown> | null;
  const needsManualCheck = String(data?.official_verification_status || 'VERIFICATION_REQUIRED') === 'VERIFICATION_REQUIRED' && (!inst || inst.decision !== 'verify');
  return (
    <SectionCard title="Institutional Verification (HOD)" subtitle="Human department review — distinct from official IP India verification. Official state is never overwritten.">
      {isLoading ? <div className="muted">Loading institutional state…</div> : error ? <div className="alert alert-error">{String(error)}</div> : (
        <div className="stack">
          <SectionList items={[
            { label: 'Official verification (automated)', value: <StatusBadge value={String(data?.official_verification_status || 'VERIFICATION_REQUIRED')} /> },
            { label: 'Institutional verification (HOD manual check)', value: inst ? <StatusBadge value={String((inst.decision as string) === 'verify' ? 'INSTITUTIONALLY_VERIFIED' : String(inst.decision).toUpperCase())} /> : 'Pending HOD review' },
            { label: 'Final verification', value: <StatusBadge value={String((final?.status as string) || data?.verification_status || 'VERIFICATION_REQUIRED')} /> },
            ...(inst ? [{ label: 'Decided by (HOD)', value: display((inst.hod_faculty_id as string) || (inst.hod_user_id as string)) }, { label: 'Remarks', value: display(inst.remarks) }, { label: 'Evidence ref', value: display(inst.evidence_ref) }, { label: 'Decided at', value: display(inst.created_at) }] : []),
            ...(final?.rationale ? [{ label: 'Final rationale', value: display(final.rationale) }] : []),
            ...(Array.isArray(final?.missing_conditions) && (final.missing_conditions as unknown[]).length ? [{ label: 'Blocked by', value: (final.missing_conditions as unknown[]).map(String).join('; ') }] : []),
          ]} />
          {needsManualCheck && canVerify ? (
            <div className="alert" style={{ background: '#fff7e8', border: '1px solid #f0d9a8' }}>
              Manual official verification required: check this record against the official IP portal, then record your decision below.
            </div>
          ) : null}
          {canVerify ? (
            <div className="stack">
              <div className="toolbar">
                <select className="toolbar-input" value={decision} onChange={(e) => { setDecision(e.target.value as any); setConfirmed(false); setResult(null); }} aria-label="Decision">
                  <option value="verify">Verify / Accept</option>
                  <option value="reject">Reject</option>
                  <option value="clarification">Needs clarification</option>
                </select>
              </div>
              <label className="field"><span>Remarks (optional)</span><input className="toolbar-input" value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder="Review notes" /></label>
              <label className="field"><span>Evidence / reference (optional)</span><input className="toolbar-input" value={evidenceRef} onChange={(e) => setEvidenceRef(e.target.value)} placeholder="Certificate page, register entry…" /></label>
              {decision === 'verify' ? (
                <label className="pill-row" style={{ gap: 8, alignItems: 'flex-start' }}>
                  <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} aria-label="Manual official verification confirmation" style={{ marginTop: 4 }} />
                  <span>I have checked this IP record against the official IP portal and confirm that the submitted details match.</span>
                </label>
              ) : null}
              {submit.isError ? <div className="alert alert-error">{String(submit.error)}</div> : null}
              {result ? (
                <div className="alert alert-success">
                  Decision recorded. Official: {result.official_verification_status} (unchanged) · Final: {result.final_verification_status} · Workflow: {result.workflow_state}
                  {result.missing_conditions.length ? ` · Blocked by: ${result.missing_conditions.join('; ')}` : ''}
                </div>
              ) : null}
              <button className="btn btn-primary" disabled={submit.isPending || (decision === 'verify' && !confirmed)} onClick={() => submit.mutate()}>{submit.isPending ? 'Saving…' : 'Submit institutional decision'}</button>
            </div>
          ) : <p className="muted">Only HOD (own department) or Super Admin can submit institutional verification.</p>}
        </div>
      )}
    </SectionCard>
  );
}



import { useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { useToast } from '../../stores/toast';

export function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const navigate = useNavigate();
  const { notify } = useToast();

  const preview = useMemo(() => file ? { name: file.name, sizeKb: (file.size / 1024).toFixed(1), type: file.type || 'application/octet-stream' } : null, [file]);

  const cancelFile = () => {
    setFile(null);
    setResult(null);
    setError('');
    if (inputRef.current) {
      inputRef.current.value = '';
    }
  };

  const submit = async () => {
    if (!file) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      if (!file.name.toLowerCase().match(/\.(pdf|png|jpg|jpeg)$/)) throw new Error('Please choose a PDF or image file.');
      const csrf = await api.csrf();
      const response = await api.upload(file, csrf.csrf_token);
      setResult(response);
      notify('success', 'Upload queued successfully');
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Upload failed';
      setError(message);
      notify('error', message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="stack-lg">
      <div className="hero-card hero-card-tight">
        <div>
          <div className="eyebrow">Upload</div>
          <h2>Upload your patent/IP document</h2>
          <p>Upload your patent/IP document for automated processing and verification.</p>
        </div>
        <button className="btn btn-secondary" onClick={() => inputRef.current?.click()}>Choose file</button>
      </div>
      <div className={`dropzone ${file ? 'dropzone-filled' : ''}`} onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); const dropped = e.dataTransfer.files?.[0]; if (dropped) setFile(dropped); }}>
        <input ref={inputRef} aria-label="Choose file" type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        <div className="dropzone-copy"><strong>Drag and drop a PDF or image here</strong><span>Or use the file picker to select a certificate document.</span></div>
      </div>
      {preview && (
        <div className="section-card compact-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div><strong>{preview.name}</strong><div className="muted">{preview.sizeKb} KB · {preview.type}</div></div>
            <button className="btn btn-ghost btn-sm" onClick={cancelFile}>Cancel</button>
          </div>
        </div>
      )}
      <div className="row">
        <button className="btn btn-primary" disabled={!file || loading} onClick={submit}>{loading ? 'Uploading...' : 'Submit upload'}</button>
        {result && <button className="btn btn-secondary" onClick={() => navigate(`/faculty/records/${result.ip_record_id as string}`)}>Open record</button>}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {result && <div className="alert alert-success"><strong>Upload queued.</strong><div>Record ID: {String(result.ip_record_id ?? 'pending')}</div><div>Status: {String(result.status ?? 'pending')}</div></div>}
    </div>
  );
}

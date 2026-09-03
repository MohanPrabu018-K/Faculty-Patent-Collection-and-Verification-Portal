import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type ExcelImportResult, type ExcelPreviewResponse } from '../../api/client';
import { SectionCard, StatCard, StatusBadge, ErrorBlock, TableWrap, display } from '../../components/ui';
import { useToast } from '../../stores/toast';

export function AdminExcelImportPage() {
  const { notify } = useToast();
  const client = useQueryClient();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ExcelPreviewResponse | null>(null);
  const [result, setResult] = useState<ExcelImportResult | null>(null);

  const previewMut = useMutation({
    mutationFn: (f: File) => { const fd = new FormData(); fd.append('file', f); return api.excelImportPreview(fd); },
    onSuccess: (data) => { setPreview(data); setResult(null); },
    onError: (e) => notify('error', e instanceof Error ? e.message : 'Preview failed'),
  });

  const importMut = useMutation({
    mutationFn: (f: File) => { const fd = new FormData(); fd.append('file', f); return api.excelImportRun(fd); },
    onSuccess: async (data) => {
      setResult(data);
      notify('success', `Imported ${data.imported_count} record(s)`);
      await client.invalidateQueries({ queryKey: ['admin-records'] });
      await client.invalidateQueries({ queryKey: ['admin-dashboard'] });
    },
    onError: (e) => notify('error', e instanceof Error ? e.message : 'Import failed'),
  });

  const pick = (f: File | null) => {
    setFile(f); setPreview(null); setResult(null);
    if (f) {
      if (!f.name.toLowerCase().endsWith('.xlsx')) { notify('error', 'Please choose a .xlsx file'); return; }
      previewMut.mutate(f);
    }
  };

  return (
    <div className="stack-lg">
      <SectionCard
        title="Excel Import"
        subtitle="Bulk-import legacy patent/design records from a .xlsx workbook. Required columns: title, faculty_id, document_type."
        actions={<button className="btn btn-sm btn-secondary" onClick={() => inputRef.current?.click()}>Choose .xlsx file</button>}
      >
        <div className={`dropzone ${file ? 'dropzone-filled' : ''}`} onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); pick(e.dataTransfer.files?.[0] ?? null); }}>
          <input ref={inputRef} type="file" accept=".xlsx" aria-label="Choose xlsx" onChange={(e) => pick(e.target.files?.[0] ?? null)} />
          <div className="dropzone-copy">
            <strong>{file ? file.name : 'Drop a .xlsx workbook here'}</strong>
            <span>{previewMut.isPending ? 'Validating…' : 'The workbook is validated before anything is imported.'}</span>
          </div>
        </div>
        {previewMut.error ? <ErrorBlock error={previewMut.error} /> : null}
      </SectionCard>

      {preview && !result && (
        <SectionCard
          title="Preview & validation"
          subtitle={`${preview.total_rows} data row(s). Invalid rows are never imported.`}
          actions={
            <button
              className="btn btn-sm btn-primary"
              disabled={importMut.isPending || preview.valid_rows === 0 || !file}
              onClick={() => file && importMut.mutate(file)}
            >
              {importMut.isPending ? 'Importing…' : `Confirm import (${preview.valid_rows} valid)`}
            </button>
          }
        >
          <div className="grid stats-grid">
            <StatCard label="Total rows" value={preview.total_rows} />
            <StatCard label="Valid" value={preview.valid_rows} />
            <StatCard label="Invalid" value={preview.invalid_rows} />
            <StatCard label="Unknown faculty" value={preview.unknown_faculty} />
          </div>
          <TableWrap>
            <table className="data-table">
              <thead>
                <tr><th>Row</th>{preview.headers.map((h) => <th key={h}>{h}</th>)}<th>Validation</th></tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.row_num} className={r.errors.length ? 'row-invalid' : ''}>
                    <td>{r.row_num}</td>
                    {preview.headers.map((h) => <td key={h}>{display(r.data[h.toLowerCase()])}</td>)}
                    <td>
                      {r.errors.length === 0
                        ? <StatusBadge value="VALID" />
                        : <span className="pill-row">{r.errors.map((e) => <StatusBadge key={e} value={e.replace(/\s+/g, '_').toUpperCase()} />)}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        </SectionCard>
      )}

      {result && (
        <SectionCard
          title="Import complete"
          actions={<Link className="btn btn-sm btn-secondary" to="/admin/ip-records">View records</Link>}
        >
          <div className="grid stats-grid">
            <StatCard label="Imported" value={result.imported_count} />
            <StatCard label="Skipped" value={result.skipped_count} />
            <StatCard label="Failed" value={result.failed_count} />
            <StatCard label="Duplicates" value={result.duplicate_count} />
          </div>
          <button className="btn btn-secondary" style={{ marginTop: 14 }} onClick={() => { setFile(null); setPreview(null); setResult(null); }}>Import another file</button>
        </SectionCard>
      )}
    </div>
  );
}

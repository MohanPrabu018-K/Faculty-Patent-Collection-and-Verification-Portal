const RAW_API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/+$/, '');
// Every path in this client is relative to the API's /api/v1 mount (e.g. '/auth/me').
// Accept VITE_API_BASE_URL with or without the '/api/v1' suffix so a deployment
// env set to the bare API origin doesn't turn every request into a 404.
const API_BASE = /\/api\/v\d+$/.test(RAW_API_BASE) ? RAW_API_BASE : `${RAW_API_BASE}/api/v1`;

export class ApiError extends Error {
  status: number;
  payload: string;

  constructor(status: number, payload: string) {
    super(payload || `Request failed: ${status}`);
    this.status = status;
    this.payload = payload;
  }
}

export type AuthUser = { id: string; email: string; full_name: string; role: string; faculty_id?: string | null; department_id?: string | null };

export type AssociationRow = {
  id: string;
  record_id?: string | null;
  record_title?: string | null;
  requester_id?: string | null;
  requester_name?: string | null;
  requester_email?: string | null;
  recipient_id?: string | null;
  recipient_name?: string | null;
  recipient_email?: string | null;
  reason?: string | null;
  message?: string | null;
  status: string;
  response_reason?: string | null;
  clarification_message?: string | null;
  responded_at?: string | null;
  reminder_sent_at?: string | null;
  created_at?: string | null;
};
export type AssociationListResponse = { associations: AssociationRow[]; count: number };
export type AssociationAction = 'accepted' | 'approved' | 'rejected' | 'not_me' | 'clarification_requested';

export type NotificationRow = {
  id: string;
  type: string;
  priority: string;
  title: string;
  message: string;
  related_entity_type?: string | null;
  related_entity_id?: string | null;
  action_url?: string | null;
  action_label?: string | null;
  is_read: boolean;
  read_at?: string | null;
  created_at: string;
  expires_at?: string | null;
  metadata?: Record<string, unknown> | null;
};
export type NotificationListResponse = {
  notifications: NotificationRow[];
  total: number;
  page: number;
  per_page: number;
  unread_count: number;
};

export type FacultyProfileResponse = {
  id: string;
  email: string;
  official_email?: string | null;
  full_name: string;
  role: string;
  faculty_id?: string | null;
  department_id?: string | null;
  department_name?: string | null;
  designation_id?: string | null;
  designation_name?: string | null;
  joining_date?: string | null;
  status?: string;
  is_active?: boolean;
  created_at?: string | null;
  counts?: {
    total_documents: number;
    patents: number;
    designs: number;
    verified: number;
    pending_verification: number;
    awaiting_review: number;
  };
};

export type HistoryEvent = {
  id: string;
  action: string;
  entity_type?: string | null;
  entity_id?: string | null;
  target_type?: string | null;
  target_id?: string | null;
  actor_id?: string | null;
  previous_value?: unknown;
  new_value?: unknown;
  created_at?: string | null;
};
export type FacultyHistoryResponse = { events: HistoryEvent[]; total: number; page: number; per_page: number; total_pages: number };
export type FacultyDashboardResponse = { records_summary: { total: number; pending: number; processing: number; completed: number; awaiting_review: number; failed: number }; recent_records: Array<Record<string, unknown>> };
export type FacultyRecordsResponse = { records: Array<Record<string, unknown>>; total: number; count: number };
export type RecordStatusResponse = Record<string, unknown>;
export type AdminDashboardResponse = { kpis: Record<string, number>; recent_activity: Array<Record<string, unknown>> };
export type QueueRow = Record<string, unknown>;
export type AdminIpRecord = Record<string, unknown>;
export type HodDashboardResponse = { department_id: string; kpis: Record<string, number> };

function readCsrfToken(): string | undefined {
  if (typeof document === 'undefined') return undefined;
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : undefined;
}

// In-memory auth material for cross-site deployments.
//
// The API sets httpOnly cookies, but cross-site cookies require
// SameSite=None; Secure and are dropped entirely when the browser blocks
// third-party cookies. The login/refresh responses also carry the JWT (and
// CSRF token) in the body, so keep them in memory and send them as an
// Authorization: Bearer fallback alongside credentials: 'include'.
// Memory-only (never localStorage) so a token never persists to disk.
// The backend already accepts Bearer in get_current_user and exempts a
// valid Bearer from the cookie double-submit CSRF check (a Bearer token
// is not ambient authority, unlike cookies).
let memAccessToken: string | null = null;
let memCsrfToken: string | null = null;

function readStoredCsrfToken(): string | undefined {
  // The CSRF cookie is the source of truth for the double-submit check
  // (the backend compares the header against this exact cookie value), so
  // prefer it over the in-memory copy, which can go stale when another tab
  // re-logs-in or refreshes the token. Fall back to memory for cross-site
  // deployments where third-party cookies are blocked.
  return readCsrfToken() || memCsrfToken || undefined;
}

function withAuthHeader(headers: Record<string, string>): Record<string, string> {
  if (memAccessToken && !headers['Authorization']) headers['Authorization'] = `Bearer ${memAccessToken}`;
  return headers;
}

/** Bearer header for raw fetch() call sites (e.g. blob downloads) that cannot go through request(). */
export function authHeader(): Record<string, string> {
  return withAuthHeader({});
}

function isCsrfFailure(status: number, body: string): boolean {
  return status === 400 && body.includes('CSRF_TOKEN_INVALID');
}

async function request<T>(path: string, init: RequestInit = {}, retryCsrf = true): Promise<T> {
  const { headers: _headers, ...rest } = init;
  const method = (init.method || 'GET').toUpperCase();
  const headers: Record<string, string> = withAuthHeader({
    ...(_headers as Record<string, string> | undefined),
  });
  if (method !== 'GET') headers['Content-Type'] = headers['Content-Type'] ?? 'application/json';
  if (method !== 'GET' && !path.startsWith('/auth/')) {
    const csrf = readStoredCsrfToken();
    if (csrf && !headers['X-CSRF-Token']) headers['X-CSRF-Token'] = csrf;
  }
  const send = (hdrs: Record<string, string>) =>
    fetch(`${API_BASE}${path}`, {
      ...rest,
      credentials: 'include',
      headers: hdrs,
    });
  try {
    const response = await send(headers);
    if (!response.ok) {
      const body = await response.text();
      // Recoverable CSRF desync (stale in-memory token, rotated/expired
      // cookie after refresh or long-idle page): bootstrap a fresh CSRF pair
      // and retry exactly once. Never retried for /auth/* itself, so this
      // cannot loop. If the session itself is expired the retry surfaces the
      // backend's 401 and the caller shows the sign-in prompt as before.
      if (
        retryCsrf &&
        method !== 'GET' &&
        !path.startsWith('/auth/') &&
        isCsrfFailure(response.status, body)
      ) {
        try {
          const fresh = await api.csrf();
          if (fresh?.csrf_token) {
            const retryResponse = await send({ ...headers, 'X-CSRF-Token': fresh.csrf_token });
            if (retryResponse.ok) {
              if (retryResponse.status === 204) return undefined as T;
              return retryResponse.json() as Promise<T>;
            }
            throw new ApiError(retryResponse.status, (await retryResponse.text()) || `Request failed with status ${retryResponse.status}`);
          }
        } catch (retryErr) {
          if (retryErr instanceof ApiError) throw retryErr;
          // Bootstrap failed (offline / cookies blocked): fall through and
          // report the original CSRF failure below.
        }
      }
      throw new ApiError(response.status, body || `Request failed with status ${response.status}`);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof TypeError && err.message === 'Failed to fetch') {
      throw new ApiError(0, 'Unable to connect to the server. Please check your network connection and try again.');
    }
    throw new ApiError(0, err instanceof Error ? err.message : 'A network error occurred');
  }
}

async function requestWithBody<T>(path: string, body: unknown, init: RequestInit = {}): Promise<T> {
  return request<T>(path, { ...init, body: JSON.stringify(body) });
}

async function multipartRequest<T>(path: string, formData: FormData, csrfToken?: string, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = withAuthHeader({});
  const csrf = csrfToken || readStoredCsrfToken();
  if (csrf) headers['X-CSRF-Token'] = csrf;
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      credentials: 'include',
      headers,
      body: formData,
      signal,
    });
    if (!response.ok) {
      const body = await response.text();
      throw new ApiError(response.status, body || `Upload failed with status ${response.status}`);
    }
    return response.json() as Promise<T>;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if ((err as Error)?.name === 'AbortError') throw err;
    if (err instanceof TypeError && err.message === 'Failed to fetch') {
      throw new ApiError(0, 'Unable to connect to the server. Please check your network connection and try again.');
    }
    throw new ApiError(0, err instanceof Error ? err.message : 'A network error occurred');
  }
}

export type LoginResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  csrf_token: string;
  user: AuthUser;
};

export const api = {
  login: async (email: string, password: string, csrfToken?: string) => {
    const res = await requestWithBody<LoginResponse>('/auth/login', { email, password }, { method: 'POST', headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : undefined });
    if (res?.access_token) memAccessToken = res.access_token;
    if (res?.csrf_token) memCsrfToken = res.csrf_token;
    return res;
  },
  logout: async () => {
    try {
      return await request('/auth/logout', { method: 'POST' });
    } finally {
      memAccessToken = null;
      memCsrfToken = null;
    }
  },
  refresh: async () => {
    const res = await request<LoginResponse>('/auth/refresh', { method: 'POST' });
    if ((res as LoginResponse)?.access_token) memAccessToken = (res as LoginResponse).access_token;
    if ((res as LoginResponse)?.csrf_token) memCsrfToken = (res as LoginResponse).csrf_token;
    return res;
  },
  me: () => request<AuthUser>('/auth/me'),
  csrf: async () => {
    const res = await request<{ csrf_token: string }>('/auth/csrf', { method: 'POST' });
    if (res?.csrf_token) memCsrfToken = res.csrf_token;
    return res;
  },
  forgotPassword: (email: string) => requestWithBody<{ message: string }>('/auth/forgot-password', { email }, { method: 'POST' }),
  resetPassword: (token: string, newPassword: string) => requestWithBody<{ message: string }>('/auth/reset-password', { token, new_password: newPassword }, { method: 'POST' }),
  facultyDashboard: () => request<FacultyDashboardResponse>('/faculty/dashboard'),
  facultyRecords: (params = '', signal?: AbortSignal) => request<FacultyRecordsResponse>(`/faculty/my-records${params}`, { signal }),
  facultyRecordStatus: (recordId: string) => request<RecordStatusResponse>(`/faculty/${recordId}/status`),
  facultyRecordReview: (recordId: string, corrections: Record<string, unknown>) => requestWithBody(`/faculty/${recordId}/review`, { corrections }, { method: 'POST' }),
  recordFileUrl: (recordId: string, fileId?: string) => `${API_BASE}/ip-records/${recordId}/file${fileId ? `?file_id=${encodeURIComponent(fileId)}` : ''}`,
  downloadRecordFile: async (recordId: string, fileId: string, filename: string) => {
    const dlHeaders: Record<string, string> = withAuthHeader({});
    const response = await fetch(`${API_BASE}/ip-records/${recordId}/file?file_id=${encodeURIComponent(fileId)}`, { credentials: 'include', headers: dlHeaders });
    if (!response.ok) throw new ApiError(response.status, await response.text());
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  },
  upload: async (file: File, csrfToken?: string, signal?: AbortSignal) => {
    const form = new FormData();
    form.append('file', file);
    return multipartRequest<Record<string, unknown>>('/uploads/', form, csrfToken, signal);
  },
  // Bug 12: effective upload limit for the signed-in user (any role). The
  // backend computes it from the Super Admin runtime override over the
  // deployed default — the frontend never hardcodes the limit.
  uploadConfig: () => request<{ max_upload_bytes: number; max_upload_mb: number; allowed_extensions: string[] }>('/uploads/config'),
  facultyProfile: () => request<FacultyProfileResponse>('/faculty/profile'),
  facultyHistory: (params = '', signal?: AbortSignal) => request<FacultyHistoryResponse>(`/faculty/history${params}`, { signal }),
  associations: () => request<AssociationListResponse>('/associations/'),
  associationsPending: () => request<{ requests: AssociationRow[]; count: number }>('/associations/pending'),
  sendAssociation: (recipientFacultyId: string, body: { record_id: string; reason?: string; message?: string }) => requestWithBody(`/associations/?recipient_faculty_id=${encodeURIComponent(recipientFacultyId)}`, body, { method: 'POST' }),
  respondAssociation: (requestId: string, action: AssociationAction, reason?: string) => requestWithBody(`/associations/${requestId}/respond?action=${action}`, { reason }, { method: 'POST' }),
  clarifyAssociation: (requestId: string, message: string) => requestWithBody(`/associations/${requestId}/clarify`, { message }, { method: 'POST' }),
  cancelAssociation: (requestId: string) => request(`/associations/${requestId}/cancel`, { method: 'POST' }),
  notifications: (params = '', signal?: AbortSignal) => request<NotificationListResponse>(`/notifications/${params}`, { signal }),
  notificationsUnreadCount: (signal?: AbortSignal) => request<{ unread_count: number }>('/notifications/unread-count', { signal }),
  markNotificationRead: (id: string) => request(`/notifications/${id}/read`, { method: 'POST' }),
  markAllNotificationsRead: () => request<{ marked_read: number }>('/notifications/read-all', { method: 'POST' }),
  deleteNotification: (id: string) => request(`/notifications/${id}`, { method: 'DELETE' }),
  adminDashboard: () => request<AdminDashboardResponse>('/admin/dashboard'),
  adminFaculty: (params = '', signal?: AbortSignal) => request<{ faculty: Array<Record<string, unknown>>; total: number; page: number; per_page: number }>(`/admin/faculty${params}`, { signal }),
  adminFacultyDetail: (id: string) => request<Record<string, unknown>>(`/admin/faculty/${id}`),
  adminCreateFaculty: (body: Record<string, unknown>) => requestWithBody<{ id: string; email: string; faculty_id: string; message: string; temporary_password?: string; temporary_password_generated?: boolean }>('/admin/faculty', body, { method: 'POST' }),
  adminUpdateFaculty: (id: string, body: Record<string, unknown>) => requestWithBody(`/admin/faculty/${id}`, body, { method: 'PATCH' }),
  adminActivateFaculty: (id: string) => request(`/admin/faculty/${id}/activate`, { method: 'POST' }),
  adminDeactivateFaculty: (id: string) => request(`/admin/faculty/${id}/deactivate`, { method: 'POST' }),
  adminDepartments: () => request<{ departments: Array<Record<string, unknown>>; total: number }>('/admin/departments?per_page=100'),
  adminDesignations: () => request<{ designations: Array<Record<string, unknown>>; total: number }>('/admin/designations?per_page=100'),
  adminRecords: (params = '', signal?: AbortSignal) => request<{ records: Array<Record<string, unknown>>; total: number; page: number; per_page: number }>(`/admin/ip-records${params}`, { signal }),
  adminMasterRecords: (params = '', signal?: AbortSignal) => request(`/admin/master-ip-records${params}`, { signal }),
  adminRecordDetail: (recordId: string) => request<AdminIpRecord>(`/admin/ip-records/${recordId}`),
  adminUpdateRecord: (recordId: string, body: Record<string, unknown>) => requestWithBody(`/admin/ip-records/${recordId}`, body, { method: 'PATCH' }),
  adminGrantPatent: (recordId: string) => requestWithBody(`/admin/ip-records/${recordId}/grant`, {}, { method: 'POST' }),
  adminVerifications: (params = '') => request<{ verifications: Array<Record<string, unknown>>; total: number; page: number; per_page: number }>(`/admin/verifications${params}`),
  adminAuditLogs: (params = '', signal?: AbortSignal) => request<AuditLogResponse>(`/audit/${params}`, { signal }),
  adminAuditStats: () => request<Record<string, number>>('/audit/stats'),
  adminSettings: () => request<AdminSettingsResponse>('/admin/settings'),
  search: (params = '', signal?: AbortSignal) => request<SearchResponse>(`/search/${params}`, { signal }),
  searchSuggestions: (q: string) => request<{ suggestions: string[] }>(`/search/suggestions?q=${encodeURIComponent(q)}`),
  adminDuplicates: (params = '') => request<{ duplicates: Array<Record<string, unknown>>; total: number; page: number; per_page: number }>(`/admin/duplicates${params}`),
  adminConflicts: (params = '') => request<{ conflicts: Array<Record<string, unknown>>; total: number; page: number; per_page: number }>(`/admin/conflicts${params}`),
  adminAssociations: (params = '') => request<{ associations: Array<Record<string, unknown>>; total: number; page: number; per_page: number }>(`/admin/associations${params}`),
  adminResolveVerification: (attemptId: string) => request(`/verification/attempts/${attemptId}/retry`, { method: 'POST' }),
  adminResolveDuplicate: (caseId: string, keepRecordId: string, notes?: string, action: 'resolve' | 'dismiss' = 'resolve') => requestWithBody(`/admin/duplicates/${caseId}/resolve`, { action, kept_record_id: keepRecordId, notes }, { method: 'POST' }),
  adminResolveConflict: (conflictId: string, resolution: string, notes?: string) => requestWithBody(`/admin/conflicts/${conflictId}/resolve`, { action: 'resolve', resolution, notes }, { method: 'POST' }),
  hodDashboard: () => request<HodDashboardResponse>('/hod/dashboard'),
  hodFaculty: (params = '', signal?: AbortSignal) => request<{ faculty: Array<Record<string, unknown>>; count: number; department_id: string }>(`/hod/faculty${params}`, { signal }),
  hodDocuments: (params = '', signal?: AbortSignal) => request<{ documents: Array<Record<string, unknown>>; total: number; page: number; per_page: number; total_pages: number }>(`/hod/documents${params}`, { signal }),
  hodDuplicates: () => request<{ duplicates: Array<Record<string, unknown>>; count: number }>('/hod/duplicates'),
  hodConflicts: () => request<{ conflicts: Array<Record<string, unknown>>; count: number }>('/hod/conflicts'),
  hodReports: () => request<Record<string, unknown>>('/hod/reports'),
  hodAudit: (params = '', signal?: AbortSignal) => request<{ audit_entries: Array<Record<string, unknown>>; total: number; page: number; per_page: number; total_pages: number }>(`/hod/audit${params}`, { signal }),
  hodReminders: (body: { kind?: string }) => requestWithBody('/hod/reminders', body, { method: 'POST' }),
  resolveDuplicate: (caseId: string, keepRecordId: string, action: 'resolve' | 'dismiss' = 'resolve', notes?: string) =>
    requestWithBody(`/duplicates/${caseId}/resolve?keep_record_id=${encodeURIComponent(keepRecordId)}`, { action, notes }, { method: 'POST' }),
  resolveConflict: (conflictId: string, action: 'resolve' | 'dismiss' = 'resolve', notes?: string) =>
    requestWithBody(`/conflicts/${conflictId}/resolve?resolution=${action}`, { action, notes }, { method: 'POST' }),
  excelImportPreview: (formData: FormData) => multipartRequest<ExcelPreviewResponse>('/admin/excel-import/preview', formData),
  excelImportRun: (formData: FormData) => multipartRequest<ExcelImportResult>('/admin/excel-import/import', formData),
  analyticsOverview: () => request<AnalyticsOverview>('/analytics/overview'),
  analyticsByFaculty: (params = '', signal?: AbortSignal) => request<{ faculty: Array<Record<string, unknown>>; total: number; page: number; per_page: number }>(`/analytics/by-faculty${params}`, { signal }),
  analyticsByDepartment: (params = '', signal?: AbortSignal) => request<{ departments: Array<Record<string, unknown>>; total: number; page: number; per_page: number }>(`/analytics/by-department${params}`, { signal }),
  analyticsTrends: (params = '') => request<{ trends: Array<{ date: string; value: number }> }>(`/analytics/trends${params}`),
  createExport: (format = 'csv', filters?: Record<string, unknown>, selectedFields?: string[]) =>
    requestWithBody<{ job_id: string; format: string; status: string; created_at: string }>(`/exports/?format=${format}`, { filters: filters ?? {}, selected_fields: selectedFields ?? null }, { method: 'POST' }),
  exportStatus: (jobId: string) => request<Record<string, unknown>>(`/exports/${jobId}`),
  exportDownloadUrl: (jobId: string) => `${API_BASE}/exports/${jobId}/download`,
  institutionalStatus: (recordId: string) => request<{ record_id: string; official_verification_status: string; verification_status: string; workflow_state: string; final_verification: Record<string, unknown> | null; institutional: Record<string, unknown> | null; history: Array<Record<string, unknown>>; pending_approvals?: string[] }>(`/verification/institutional/${recordId}`),
  institutionalVerify: (recordId: string, body: { decision: 'verify' | 'reject' | 'clarification'; remarks?: string; evidence_ref?: string }) => requestWithBody<{ record_id: string; decision: string; institutional_status: string; official_verification_status: string; final_verification_status: string; workflow_state: string; missing_conditions: string[]; attempt_id: string }>(`/verification/institutional/${recordId}`, body, { method: 'POST' }),
  pendingAssociationsReport: (params = '', signal?: AbortSignal) => request<{ associations: Array<Record<string, unknown>>; total: number; pending_count: number; by_status: Record<string, number>; page: number; per_page: number }>(`/admin/reports/pending-associations${params}`, { signal }),
  adminUpdateSettings: (body: Record<string, unknown>) => requestWithBody<{ max_upload_mb: number; message: string }>('/admin/settings', body, { method: 'PATCH' }),
};

export type ExcelPreviewRow = { row_num: number; data: Record<string, string>; errors: string[]; unknown_faculty: boolean };
export type ExcelPreviewResponse = {
  headers: string[];
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  unknown_faculty: number;
  rows: ExcelPreviewRow[];
};
export type ExcelImportResult = { imported_count: number; skipped_count: number; failed_count: number; duplicate_count: number };

export type AuditLogRow = {
  id: string;
  actor_id?: string | null;
  actor_name?: string | null;
  actor_role?: string | null;
  actor_department?: string | null;
  action: string;
  entity_type?: string | null;
  entity_id?: string | null;
  target_type?: string | null;
  target_id?: string | null;
  previous_value?: unknown;
  new_value?: unknown;
  before_state?: unknown;
  after_state?: unknown;
  details?: unknown;
  extra?: unknown;
  ip_address?: string | null;
  reason?: string | null;
  created_at?: string | null;
};
export type AuditLogResponse = { audit_logs: AuditLogRow[]; total: number; page: number; per_page: number };

export type AdminSettingsResponse = {
  editable: boolean;
  application: Record<string, unknown>;
  ocr: Record<string, unknown>;
  qr: Record<string, unknown>;
  verification: Record<string, unknown>;
  uploads: Record<string, unknown>;
  session: Record<string, unknown>;
};

export type SearchResultRow = {
  id: string;
  ip_type: string;
  patent_number?: string | null;
  design_number?: string | null;
  application_number?: string | null;
  title?: string | null;
  applicant?: string | null;
  inventors?: string[];
  filing_date?: string | null;
  grant_date?: string | null;
  verification_status?: string;
  processing_status?: string;
  faculty_name?: string | null;
  faculty_id?: string | null;
  department?: string | null;
  contributor_count?: number;
  is_collaborative?: boolean;
  created_at?: string | null;
};
export type SearchResponse = {
  results: SearchResultRow[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
  query_time_ms: number;
  facets: Record<string, Record<string, number>>;
};

export type AnalyticsOverview = {
  total_faculty: number;
  active_faculty: number;
  total_ip_records: number;
  verified_records: number;
  pending_verification: number;
  pending_processing: number;
  by_ip_type: Record<string, number>;
  by_verification_status: Record<string, number>;
  by_processing_status: Record<string, number>;
  by_department: Record<string, number>;
  by_year: Record<string, number>;
  collaborative_records: number;
  external_contributions: number;
  upload_trend: Array<{ date: string; value: number }>;
  verification_trend: Array<{ date: string; value: number }>;
};

import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '../stores/auth';
import { ToastProvider } from '../stores/toast';
import { AppShell } from './AppShell';
import { ProtectedRoute, RequireRole } from './ProtectedRoute';

const LoginPage = lazy(() => import('../features/auth/LoginPage').then(m => ({ default: m.LoginPage })));
const FacultyDashboardPage = lazy(() => import('../features/faculty/FacultyDashboardPage').then(m => ({ default: m.FacultyDashboardPage })));
const UploadPage = lazy(() => import('../features/faculty/UploadPage').then(m => ({ default: m.UploadPage })));
const RecordsPage = lazy(() => import('../features/faculty/RecordsPage').then(m => ({ default: m.RecordsPage })));
const RecordDetailPage = lazy(() => import('../features/faculty/RecordDetailPage').then(m => ({ default: m.RecordDetailPage })));
const AssociationsPage = lazy(() => import('../features/faculty/AssociationsPage').then(m => ({ default: m.AssociationsPage })));
const FacultyProfilePage = lazy(() => import('../features/faculty/FacultyProfilePage').then(m => ({ default: m.FacultyProfilePage })));
const FacultyHistoryPage = lazy(() => import('../features/faculty/FacultyHistoryPage').then(m => ({ default: m.FacultyHistoryPage })));
const NotificationsPage = lazy(() => import('../features/notifications/NotificationsPage').then(m => ({ default: m.NotificationsPage })));
const AdminDashboardPage = lazy(() => import('../features/admin/AdminDashboardPage').then(m => ({ default: m.AdminDashboardPage })));
const AdminRecordsPage = lazy(() => import('../features/admin/AdminRecordsPage').then(m => ({ default: m.AdminRecordsPage })));
const AdminFacultyPage = lazy(() => import('../features/admin/AdminFacultyPage').then(m => ({ default: m.AdminFacultyPage })));
const AdminQueuesPage = lazy(() => import('../features/admin/AdminQueuesPage').then(m => ({ default: m.AdminQueuesPage })));
const AdminMasterRecordsPage = lazy(() => import('../features/admin/AdminMasterRecordsPage').then(m => ({ default: m.AdminMasterRecordsPage })));
const AdminGrantedPatentsPage = lazy(() => import('../features/admin/AdminGrantedPatentsPage').then(m => ({ default: m.AdminGrantedPatentsPage })));
const AdminReportsPage = lazy(() => import('../features/admin/AdminReportsPage').then(m => ({ default: m.AdminReportsPage })));
const AdminExcelImportPage = lazy(() => import('../features/admin/AdminExcelImportPage').then(m => ({ default: m.AdminExcelImportPage })));
const AdminAuditPage = lazy(() => import('../features/admin/AdminAuditPage').then(m => ({ default: m.AdminAuditPage })));
const AdminSettingsPage = lazy(() => import('../features/admin/AdminSettingsPage').then(m => ({ default: m.AdminSettingsPage })));
const SearchPage = lazy(() => import('../features/search/SearchPage').then(m => ({ default: m.SearchPage })));

const HodDashboardPage = lazy(() => import('../features/hod/HodPages').then(m => ({ default: m.HodDashboardPage })));
const HodFacultyPage = lazy(() => import('../features/hod/HodPages').then(m => ({ default: m.HodFacultyPage })));
const HodDocumentsPage = lazy(() => import('../features/hod/HodPages').then(m => ({ default: m.HodDocumentsPage })));
const HodDuplicatesPage = lazy(() => import('../features/hod/HodPages').then(m => ({ default: m.HodDuplicatesPage })));
const HodConflictsPage = lazy(() => import('../features/hod/HodPages').then(m => ({ default: m.HodConflictsPage })));
const HodReportsPage = lazy(() => import('../features/hod/HodPages').then(m => ({ default: m.HodReportsPage })));
const HodAuditPage = lazy(() => import('../features/hod/HodPages').then(m => ({ default: m.HodAuditPage })));

function PageFallback() {
  return <div className="loading-inline" style={{ padding: '24px 0' }}><span className="spinner" /><span>Loading…</span></div>;
}

export function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<ProtectedRoute />}>
              <Route element={<AppShell />}>
                <Route path="/" element={<Navigate to="/faculty/dashboard" replace />} />
                <Route path="/faculty/dashboard" element={<FacultyDashboardPage />} />
                <Route path="/faculty/profile" element={<FacultyProfilePage />} />
                <Route path="/faculty/upload" element={<UploadPage />} />
                <Route path="/faculty/records" element={<RecordsPage />} />
                <Route path="/faculty/records/:recordId" element={<RecordDetailPage />} />
                <Route path="/faculty/associations" element={<AssociationsPage />} />
                <Route path="/faculty/history" element={<FacultyHistoryPage />} />
                <Route path="/notifications" element={<NotificationsPage />} />
                <Route path="/search" element={<SearchPage />} />
                <Route element={<RequireRole roles={['hod_admin', 'super_admin']} />}>
                  <Route path="/hod/dashboard" element={<HodDashboardPage />} />
                  <Route path="/hod/faculty" element={<HodFacultyPage />} />
                  <Route path="/hod/documents" element={<HodDocumentsPage />} />
                  <Route path="/hod/upload" element={<UploadPage />} />
                  <Route path="/hod/duplicates" element={<HodDuplicatesPage />} />
                  <Route path="/hod/conflicts" element={<HodConflictsPage />} />
                  <Route path="/hod/reports" element={<HodReportsPage />} />
                  <Route path="/hod/audit" element={<HodAuditPage />} />
                  <Route path="/hod/profile" element={<FacultyProfilePage />} />
                </Route>
                <Route element={<RequireRole roles={['super_admin']} />}>
                  <Route path="/admin/dashboard" element={<AdminDashboardPage />} />
                  <Route path="/admin/faculty" element={<AdminFacultyPage />} />
                  <Route path="/admin/granted-patents" element={<AdminGrantedPatentsPage />} />
                  <Route path="/admin/patent-upload" element={<UploadPage />} />
                  <Route path="/admin/ip-records" element={<AdminRecordsPage />} />
                  <Route path="/admin/master-records" element={<AdminMasterRecordsPage />} />
                  <Route path="/admin/queues" element={<AdminQueuesPage />} />
                  <Route path="/admin/reports" element={<AdminReportsPage />} />
                  <Route path="/admin/excel-import" element={<AdminExcelImportPage />} />
                  <Route path="/admin/audit" element={<AdminAuditPage />} />
                  <Route path="/admin/settings" element={<AdminSettingsPage />} />
                </Route>
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </ToastProvider>
    </AuthProvider>
  );
}

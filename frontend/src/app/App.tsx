import { Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '../stores/auth';
import { ToastProvider } from '../stores/toast';
import { AppShell } from './AppShell';
import { LoginPage } from '../features/auth/LoginPage';
import { FacultyDashboardPage } from '../features/faculty/FacultyDashboardPage';
import { UploadPage } from '../features/faculty/UploadPage';
import { RecordsPage } from '../features/faculty/RecordsPage';
import { RecordDetailPage } from '../features/faculty/RecordDetailPage';
import { AssociationsPage } from '../features/faculty/AssociationsPage';
import { FacultyProfilePage } from '../features/faculty/FacultyProfilePage';
import { FacultyHistoryPage } from '../features/faculty/FacultyHistoryPage';
import { NotificationsPage } from '../features/notifications/NotificationsPage';
import { AdminDashboardPage } from '../features/admin/AdminDashboardPage';
import { AdminRecordsPage } from '../features/admin/AdminRecordsPage';
import { AdminFacultyPage } from '../features/admin/AdminFacultyPage';
import { AdminQueuesPage } from '../features/admin/AdminQueuesPage';
import { AdminMasterRecordsPage } from '../features/admin/AdminMasterRecordsPage';
import { AdminGrantedPatentsPage } from '../features/admin/AdminGrantedPatentsPage';
import { AdminReportsPage } from '../features/admin/AdminReportsPage';
import { AdminExcelImportPage } from '../features/admin/AdminExcelImportPage';
import { AdminAuditPage } from '../features/admin/AdminAuditPage';
import { AdminSettingsPage } from '../features/admin/AdminSettingsPage';
import { SearchPage } from '../features/search/SearchPage';
import {
  HodDashboardPage, HodFacultyPage, HodDocumentsPage, HodDuplicatesPage,
  HodConflictsPage, HodReportsPage, HodAuditPage,
} from '../features/hod/HodPages';
import { ProtectedRoute, RequireRole } from './ProtectedRoute';

export function App() {
  return (
    <AuthProvider>
      <ToastProvider>
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
      </ToastProvider>
    </AuthProvider>
  );
}

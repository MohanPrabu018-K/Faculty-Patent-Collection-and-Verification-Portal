import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom';
import { Suspense } from 'react';
import {
  LogOut, Shield, Upload, FileText, Users, LayoutDashboard, Database, BriefcaseBusiness,
  Bell, UserCircle, History, Link2, CopyCheck, GitCompareArrows, BarChart3, ScrollText, Award, FileSpreadsheet,
  Search, Settings,
} from 'lucide-react';
import { useAuth } from '../stores/auth';
import { useToast } from '../stores/toast';
import { NotificationBell } from '../features/notifications/NotificationBell';

type LinkDef = { to: string; label: string; icon: typeof LayoutDashboard; show: boolean };

export function AppShell() {
  const { user, logout } = useAuth();
  const { notify } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const isAdmin = user?.role === 'super_admin';
  const isHod = user?.role === 'hod_admin';
  const isFaculty = user?.role === 'faculty';

  const links: LinkDef[] = [
    // Faculty (everyone has a personal workspace)
    { to: '/faculty/dashboard', label: 'Dashboard', icon: LayoutDashboard, show: isFaculty },
    { to: '/faculty/profile', label: 'My Profile', icon: UserCircle, show: isFaculty },
    { to: '/faculty/upload', label: 'Upload', icon: Upload, show: isFaculty },
    { to: '/faculty/records', label: 'My Records', icon: FileText, show: isFaculty },
    { to: '/faculty/associations', label: 'Associations', icon: Link2, show: isFaculty },
    { to: '/faculty/history', label: 'History', icon: History, show: isFaculty },

    // HOD
    { to: '/hod/dashboard', label: 'Dashboard', icon: BriefcaseBusiness, show: isHod },
    { to: '/hod/faculty', label: 'Faculty', icon: Users, show: isHod },
    { to: '/hod/documents', label: 'Documents', icon: FileText, show: isHod },
    { to: '/hod/duplicates', label: 'Duplicates', icon: CopyCheck, show: isHod },
    { to: '/hod/conflicts', label: 'Conflicts', icon: GitCompareArrows, show: isHod },
    { to: '/hod/reports', label: 'Reports', icon: BarChart3, show: isHod },
    { to: '/hod/audit', label: 'Audit', icon: ScrollText, show: isHod },
    { to: '/hod/upload', label: 'My Uploads', icon: Upload, show: isHod },

    // Super Admin
    { to: '/admin/dashboard', label: 'Dashboard', icon: Shield, show: isAdmin },
    { to: '/admin/faculty', label: 'Faculty', icon: Users, show: isAdmin },
    { to: '/admin/granted-patents', label: 'Granted Patents', icon: Award, show: isAdmin },
    { to: '/admin/ip-records', label: 'IP Records', icon: FileText, show: isAdmin },
    { to: '/admin/master-records', label: 'Master Records', icon: Database, show: isAdmin },
    { to: '/admin/queues', label: 'Review Queues', icon: CopyCheck, show: isAdmin },
    { to: '/admin/reports', label: 'Reports', icon: BarChart3, show: isAdmin },
    { to: '/admin/excel-import', label: 'Excel Import', icon: FileSpreadsheet, show: isAdmin },
    { to: '/admin/audit', label: 'Audit', icon: ScrollText, show: isAdmin },
    { to: '/admin/settings', label: 'Settings', icon: Settings, show: isAdmin },

    // Everyone
    { to: '/search', label: 'Search', icon: Search, show: true },
    { to: '/notifications', label: 'Notifications', icon: Bell, show: true },
  ];

  const visible = links.filter((l) => l.show);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">FP</div>
          <div>
            <div className="brand-title">Faculty Portal</div>
            <div className="brand-subtitle">IP management system</div>
          </div>
        </div>
        <nav className="nav">
          {visible.map((link) => {
            const Icon = link.icon;
            return (
              <NavLink key={link.to} to={link.to} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
                <Icon size={16} />
                <span>{link.label}</span>
              </NavLink>
            );
          })}
        </nav>
      </aside>
      <div className="content">
        <header className="topbar">
          <div>
            <div className="eyebrow">Faculty Profile Portal</div>
            <h1 className="page-title">Academic IP administration</h1>
          </div>
          <div className="topbar-actions">
            <NotificationBell />
            <div className="user-chip"><strong>{user?.full_name || 'User'}</strong><span>{(user?.role || 'faculty').replace('_', ' ')}</span></div>
            <button className="btn btn-secondary" onClick={async () => { await logout(); notify('info', 'Logged out'); navigate('/login'); }} aria-label="Logout"><LogOut size={16} /> Logout</button>
          </div>
        </header>
        <main className="main">
          <Suspense fallback={<div className="loading-inline" role="status" aria-live="polite"><span className="spinner" aria-hidden="true" /><span>Loading…</span></div>}>
            <div key={location.pathname} className="page-enter">
              <Outlet />
            </div>
          </Suspense>
        </main>
        <div className="mobile-nav">
          {visible.map((link) => {
            const Icon = link.icon;
            return (
              <NavLink key={link.to} to={link.to} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
                <Icon size={16} />
                <span>{link.label}</span>
              </NavLink>
            );
          })}
        </div>
      </div>
    </div>
  );
}

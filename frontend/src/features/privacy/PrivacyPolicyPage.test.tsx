// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { PrivacyPolicyPage } from './PrivacyPolicyPage';
import { LoginPage } from '../auth/LoginPage';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../../stores/auth', () => ({
  useAuth: () => ({
    user: null,
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));

afterEach(() => {
  cleanup();
});

function renderWithRouter(initialRoute = '/privacy-policy') {
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <Routes>
        <Route path="/privacy-policy" element={<PrivacyPolicyPage />} />
        <Route path="/login" element={<div>Login Target</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('PrivacyPolicyPage public route & contents', () => {
  it('renders the public Privacy Policy page without authentication', () => {
    renderWithRouter('/privacy-policy');
    expect(screen.getByRole('heading', { level: 1, name: /privacy policy/i })).toBeInTheDocument();
  });

  it('contains the institutional portal context and navigation', () => {
    renderWithRouter();
    expect(screen.getByText(/Institutional Governance & Transparency/i)).toBeInTheDocument();
    const loginLink = screen.getByRole('link', { name: /back to login/i });
    expect(loginLink).toBeInTheDocument();
    expect(loginLink).toHaveAttribute('href', '/login');
  });

  it('renders all 10 core privacy policy sections', () => {
    renderWithRouter();
    expect(screen.getByRole('heading', { level: 2, name: /1\. Scope & Purpose/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /2\. Information We Collect/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /3\. Patent Documents & Google Drive Storage/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /4\. How Information Is Accessed & Processed/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /5\. Access Controls & Role-Based Permissions/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /6\. Data Retention, Archival & Deletion/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /7\. Security Safeguards & Technical Controls/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /8\. Third-Party Services & Sub-processors/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /9\. User Privacy Rights & Choices/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /10\. Contact & Governance/i })).toBeInTheDocument();
  });

  it('details Google Drive integration and drive.file restricted scope', () => {
    renderWithRouter();
    expect(screen.getAllByText(/drive\.file/i)[0]).toBeInTheDocument();
    expect(screen.getByText(/Faculty_Patent_Documents/i)).toBeInTheDocument();
    expect(screen.getByText(/Files are never published to the public web/i)).toBeInTheDocument();
  });

  it('covers role-based access control (RBAC) tiers', () => {
    renderWithRouter();
    expect(screen.getByText('Faculty Users')).toBeInTheDocument();
    expect(screen.getByText('Head of Department (HOD)')).toBeInTheDocument();
    expect(screen.getByText('Super Administrators')).toBeInTheDocument();
    expect(screen.getByText(/Personal data and uploaded intellectual property files are never sold/i)).toBeInTheDocument();
  });

  it('lists third-party service providers and sub-processors accurately', () => {
    renderWithRouter();
    expect(screen.getAllByText(/Google Drive API/i)[0]).toBeInTheDocument();
    expect(screen.getByText(/Brevo \/ Transactional SMTP/i)).toBeInTheDocument();
    expect(screen.getByText(/Cloudflare Pages/i)).toBeInTheDocument();
    expect(screen.getByText(/Render/i)).toBeInTheDocument();
    expect(screen.getByText(/PostgreSQL/i)).toBeInTheDocument();
  });

  it('displays accurate verified contact information and institutional disclaimer', () => {
    renderWithRouter();
    const mailLink = screen.getByRole('link', { name: /mohanprabu018@gmail\.com/i });
    expect(mailLink).toHaveAttribute('href', 'mailto:mohanprabu018@gmail.com');
    expect(screen.getByText(/Deploying Institution Notice:/i)).toBeInTheDocument();
  });

  it('renders a quick table of contents linking to sections', () => {
    const { container } = renderWithRouter();
    const toc = container.querySelector('.privacy-toc');
    expect(toc).toBeInTheDocument();
    expect(toc?.querySelector('a[href="#section-1"]')).toHaveTextContent('1. Scope & Purpose');
    expect(toc?.querySelector('a[href="#section-3"]')).toHaveTextContent('3. Patent Documents & Google Drive');
    expect(toc?.querySelector('a[href="#section-10"]')).toHaveTextContent('10. Contact & Governance');
  });
});

describe('LoginPage link to Privacy Policy', () => {
  it('renders a visible link to /privacy-policy in the login card footer', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/login']}>
          <LoginPage />
        </MemoryRouter>
      </QueryClientProvider>
    );

    const privacyLink = screen.getByRole('link', { name: /privacy policy/i });
    expect(privacyLink).toBeInTheDocument();
    expect(privacyLink).toHaveAttribute('href', '/privacy-policy');
  });
});

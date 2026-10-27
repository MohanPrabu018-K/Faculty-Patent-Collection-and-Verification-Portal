import { Link } from 'react-router-dom';
import {
  Shield, Lock, FileText, Database, Server, UserCheck, HardDrive, Mail,
  ArrowLeft, CheckCircle2, AlertTriangle, KeyRound, Layers
} from 'lucide-react';

export function PrivacyPolicyPage() {
  return (
    <div className="privacy-page">
      {/* Top Navigation Bar */}
      <header className="privacy-nav">
        <div className="privacy-nav-container">
          <Link to="/" className="brand" aria-label="Faculty Portal Home">
            <div className="brand-mark">FP</div>
            <div>
              <div className="brand-title">Faculty Patent Portal</div>
              <div className="brand-subtitle">Institutional IP Management System</div>
            </div>
          </Link>
          <div className="privacy-nav-actions">
            <Link to="/login" className="btn btn-secondary btn-sm">
              <ArrowLeft size={16} />
              <span>Back to Login</span>
            </Link>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="privacy-main">
        {/* Hero Header */}
        <div className="privacy-hero">
          <div className="eyebrow">Institutional Governance & Transparency</div>
          <h1 className="privacy-title">Privacy Policy</h1>
          <p className="privacy-subtitle">
            This Privacy Policy details how the Faculty Patent Collection and Verification Portal (&ldquo;FPP&rdquo;)
            collects, processes, safeguards, and retains academic patent documents, research metadata, and account information.
          </p>
          <div className="privacy-meta-row">
            <span className="badge badge-verified">
              <CheckCircle2 size={13} style={{ marginRight: 4 }} /> Effective: October 2026
            </span>
            <span className="badge badge-unverified">Version 1.0 (Production)</span>
            <span className="badge badge-unverified">Scope: Institutional Academic IP</span>
          </div>
        </div>

        {/* Notice Callout */}
        <div className="privacy-callout">
          <Shield size={20} className="privacy-callout-icon" />
          <div>
            <strong>Institutional Academic Portal Notice</strong>
            <p>
              This portal is an institutional administrative application designed specifically for faculty patent collection,
              departmental verification, and research accreditation reporting. It is not an open public social platform.
              Access is restricted to authorized faculty members, department heads, and institutional administrators.
            </p>
          </div>
        </div>

        {/* Content Layout */}
        <div className="privacy-layout">
          {/* Table of Contents */}
          <aside className="privacy-toc" aria-label="Table of contents">
            <div className="privacy-toc-card">
              <h3 className="privacy-toc-title">Table of Contents</h3>
              <nav className="privacy-toc-nav">
                <a href="#section-1">1. Scope &amp; Purpose</a>
                <a href="#section-2">2. Information We Collect</a>
                <a href="#section-3">3. Patent Documents &amp; Google Drive</a>
                <a href="#section-4">4. How Data Is Processed</a>
                <a href="#section-5">5. Access Controls &amp; RBAC</a>
                <a href="#section-6">6. Retention &amp; Deletion</a>
                <a href="#section-7">7. Security Safeguards</a>
                <a href="#section-8">8. Third-Party Services</a>
                <a href="#section-9">9. User Privacy Rights</a>
                <a href="#section-10">10. Contact &amp; Governance</a>
              </nav>
            </div>
          </aside>

          {/* Policy Sections */}
          <article className="privacy-content">
            {/* Section 1 */}
            <section id="section-1" className="privacy-card">
              <div className="privacy-section-head">
                <div className="privacy-icon-pill"><Layers size={20} /></div>
                <h2>1. Scope &amp; Purpose</h2>
              </div>
              <p>
                The Faculty Patent Collection and Verification Portal (&ldquo;FPP&rdquo;) is an institutional web platform
                deployed to record, verify, and catalog intellectual property (IP) registrations, including published patents,
                granted patents, and industrial design certificates authored by academic faculty.
              </p>
              <p>
                The primary purpose of data processing within the portal is:
              </p>
              <ul>
                <li>Maintaining an authoritative, audit-ready institutional repository of intellectual property assets.</li>
                <li>Verifying faculty claims against official patent office registries (e.g., IPO / CGPDTM).</li>
                <li>Preventing duplicate claims and accreditation discrepancies across departments.</li>
                <li>Generating verifiable data for institutional accreditation (NAAC, NIRF) and annual research reports.</li>
              </ul>
            </section>

            {/* Section 2 */}
            <section id="section-2" className="privacy-card">
              <div className="privacy-section-head">
                <div className="privacy-icon-pill"><UserCheck size={20} /></div>
                <h2>2. Information We Collect</h2>
              </div>
              <p>
                To provide authenticated access and maintain verified IP records, the portal collects the following categories of data:
              </p>
              
              <h3>A. Account &amp; Identity Information</h3>
              <ul>
                <li><strong>Full Name &amp; Contact:</strong> Provided by your department or administrator for identification.</li>
                <li><strong>Official Email Address:</strong> Used as the unique login username and for transactional password-reset emails.</li>
                <li><strong>Institutional Metadata:</strong> Department assignment, academic designation, and institutional Faculty ID.</li>
                <li><strong>Authentication Credentials:</strong> Passwords are protected using salted cryptographic hashes (e.g., bcrypt/Argon2). Plaintext passwords are never stored, logged, or accessible to portal administrators.</li>
              </ul>

              <h3>B. Patent Documents &amp; Intellectual Property Metadata</h3>
              <ul>
                <li><strong>Certificate Files:</strong> Uploaded digital documents (PDF, PNG, JPEG) of patent filing receipts, publication journals, grant certificates, and design registration documents.</li>
                <li><strong>Bibliographic Information:</strong> Title of the invention, application number, patent/design number, filing date, publication date, grant date, status, inventor lists, and applicant entity name.</li>
                <li><strong>Cryptographic Fingerprints:</strong> SHA-256 file fingerprints calculated client-side and server-side to detect identical document uploads without exposing document content.</li>
                <li><strong>Co-inventor Associations:</strong> Internal institutional contributor linkages and contributor confirmation status.</li>
              </ul>

              <h3>C. System &amp; Security Telemetry</h3>
              <ul>
                <li><strong>Session &amp; Security Tokens:</strong> Temporary JWT tokens, HTTP-only authentication cookies, and Anti-CSRF protection tokens.</li>
                <li><strong>Access Logs &amp; IP Addresses:</strong> Client IP addresses and user agents recorded strictly for rate-limiting enforcement and security incident defense.</li>
                <li><strong>Administrative Audit Trails:</strong> Timestamped records of document submissions, status modifications, verification reviews, and data exports.</li>
              </ul>
            </section>

            {/* Section 3 */}
            <section id="section-3" className="privacy-card">
              <div className="privacy-section-head">
                <div className="privacy-icon-pill"><HardDrive size={20} /></div>
                <h2>3. Patent Documents &amp; Google Drive Storage</h2>
              </div>
              <p>
                To provide persistent cloud storage without requiring public file sharing or recurring institutional infrastructure fees,
                the portal integrates with Google Drive API v3:
              </p>
              <ul>
                <li>
                  <strong>Restricted OAuth Scope (<code>drive.file</code>):</strong> The backend connects using the Google OAuth2
                  <code>https://www.googleapis.com/auth/drive.file</code> scope. This restricted permission model ensures that the portal
                  has access <em>only</em> to the files and folders created directly by the application. The portal has zero technical access
                  to any other personal documents, spreadsheets, or folders within the connected Google account.
                </li>
                <li>
                  <strong>Private Folder Isolation:</strong> All uploaded files are stored inside a dedicated, private Google Drive
                  folder (<code>Faculty_Patent_Documents</code>). Files are never published to the public web or shared via public links.
                </li>
                <li>
                  <strong>Authenticated Backend Proxy:</strong> End users and faculty members never directly interface with Google Drive URLs.
                  All document downloads, previews, and pipeline operations are securely proxied through the authenticated backend API
                  after validating role-based authorization.
                </li>
                <li>
                  <strong>Container Wipe Resilience:</strong> Cloud documents serve as the authoritative persistent layer. If the application
                  container restarts, documents are retrieved on demand into an encrypted local cache.
                </li>
              </ul>
            </section>

            {/* Section 4 */}
            <section id="section-4" className="privacy-card">
              <div className="privacy-section-head">
                <div className="privacy-icon-pill"><FileText size={20} /></div>
                <h2>4. How Information Is Accessed &amp; Processed</h2>
              </div>
              <p>
                Data submitted to the portal is processed exclusively for institutional intellectual property governance:
              </p>
              <ul>
                <li>
                  <strong>Automated Metadata Extraction:</strong> Uploaded patent certificates are processed by deterministic
                  optical character recognition (OCR) and extraction agents to parse application numbers, grant dates, and inventor names.
                </li>
                <li>
                  <strong>Verification &amp; Review Workflow:</strong> Head of Department (HOD) reviewers and Super Administrators inspect
                  extracted data and certificate evidence against official patent office gazettes to approve verified academic records.
                </li>
                <li>
                  <strong>Duplicate &amp; Conflict Detection:</strong> Automated algorithms cross-reference application numbers and file hashes
                  to alert administrators when multiple faculty members or departments upload the same patent filing.
                </li>
                <li>
                  <strong>Institutional Accreditation Exports:</strong> Verified patent summaries are exported in standardized formats
                  (Excel, CSV, JSON) strictly by authorized administrators for academic accreditation submissions (e.g., NAAC, NIRF).
                </li>
              </ul>
            </section>

            {/* Section 5 */}
            <section id="section-5" className="privacy-card">
              <div className="privacy-section-head">
                <div className="privacy-icon-pill"><Lock size={20} /></div>
                <h2>5. Access Controls &amp; Role-Based Permissions (RBAC)</h2>
              </div>
              <p>
                Access to information within the portal is strictly governed by least-privilege Role-Based Access Control (RBAC):
              </p>
              <div className="privacy-grid">
                <div className="compact-card">
                  <strong>Faculty Users</strong>
                  <p className="muted" style={{ fontSize: '13px', margin: '6px 0 0' }}>
                    Can view and manage only their own submitted patent certificates, personal profile data, and incoming co-inventor association invitations.
                  </p>
                </div>
                <div className="compact-card">
                  <strong>Head of Department (HOD)</strong>
                  <p className="muted" style={{ fontSize: '13px', margin: '6px 0 0' }}>
                    Can review and inspect patent records and certificate files belonging exclusively to faculty within their assigned academic department.
                  </p>
                </div>
                <div className="compact-card">
                  <strong>Super Administrators</strong>
                  <p className="muted" style={{ fontSize: '13px', margin: '6px 0 0' }}>
                    Authorized institutional personnel responsible for overall IP verification queues, faculty account administration, and system audit trails.
                  </p>
                </div>
              </div>
              <p style={{ marginTop: '14px' }}>
                <strong>No Commercial Data Sharing:</strong> Personal data and uploaded intellectual property files are never sold,
                monetized, rented, or shared with commercial advertising networks or data brokers.
              </p>
            </section>

            {/* Section 6 */}
            <section id="section-6" className="privacy-card">
              <div className="privacy-section-head">
                <div className="privacy-icon-pill"><Database size={20} /></div>
                <h2>6. Data Retention, Archival &amp; Deletion</h2>
              </div>
              <ul>
                <li>
                  <strong>Retention Period:</strong> Intellectual property records and associated certificates are retained for the duration
                  of the faculty member&rsquo;s institutional affiliation and the statutory lifecycle required by institutional accreditation
                  standards and research governance guidelines.
                </li>
                <li>
                  <strong>Document Deletion:</strong> When an authorized administrator deletes a patent record or document, the system
                  performs a synchronized deletion: the local disk cache is unlinked, and the remote file is permanently deleted from
                  Google Drive storage (<code>files().delete</code>).
                </li>
                <li>
                  <strong>Audit Log Retention:</strong> Administrative actions (uploads, approvals, rejections, deletions) are recorded in
                  an immutable audit log to maintain governance accountability. Audit logs store event metadata (actor ID, action, timestamp)
                  and never store passwords or file contents.
                </li>
              </ul>
            </section>

            {/* Section 7 */}
            <section id="section-7" className="privacy-card">
              <div className="privacy-section-head">
                <div className="privacy-icon-pill"><Shield size={20} /></div>
                <h2>7. Security Safeguards &amp; Technical Controls</h2>
              </div>
              <p>
                The portal employs standard defensive engineering safeguards to protect institutional records:
              </p>
              <ul>
                <li><strong>Encryption in Transit:</strong> All HTTP traffic is strictly routed through Transport Layer Security (HTTPS / TLS 1.3). Plaintext HTTP connections are rejected.</li>
                <li><strong>Credential Protection:</strong> Passwords are encrypted using modern salted hash algorithms. Password reset tokens are single-use, cryptographically generated, and expire after 1 hour.</li>
                <li><strong>Cookie &amp; Session Security:</strong> Authentication cookies are configured with <code>HttpOnly</code>, <code>SameSite=Lax</code> (or <code>Strict</code>), and <code>Secure</code> flags to prevent cross-site scripting (XSS) extraction.</li>
                <li><strong>Cross-Site Request Forgery (CSRF) Defense:</strong> State-modifying requests require verified double-submit or header-based CSRF tokens.</li>
                <li><strong>Rate Limiting:</strong> Sensitive endpoints (login, password reset requests, file uploads) are protected with automated IP-based rate limiting to prevent brute-force attacks and abuse.</li>
                <li><strong>Path Traversal Defense:</strong> All file storage operations use sanitized keys and strict directory root boundary checks to prevent traversal attacks.</li>
              </ul>
              <div className="privacy-callout privacy-callout-muted">
                <AlertTriangle size={18} className="privacy-callout-icon" />
                <div style={{ fontSize: '13px' }}>
                  <strong>Security Transparency:</strong> While the portal implements robust engineering defenses and continuous automated testing,
                  no internet application can guarantee absolute immunity from all threats. Faculty members are responsible for maintaining strong,
                  unique passwords and promptly reporting any suspicious account activity.
                </div>
              </div>
            </section>

            {/* Section 8 */}
            <section id="section-8" className="privacy-card">
              <div className="privacy-section-head">
                <div className="privacy-icon-pill"><Server size={20} /></div>
                <h2>8. Third-Party Services &amp; Sub-processors</h2>
              </div>
              <p>
                To provide hosting, storage, and transactional communication, the portal utilizes the following third-party infrastructure:
              </p>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Service Provider</th>
                      <th>Purpose</th>
                      <th>Data Shared / Handled</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td><strong>Google Drive API (Google LLC)</strong></td>
                      <td>Persistent cloud document storage</td>
                      <td>Patent certificate files (PDF, image); restricted to private folder via <code>drive.file</code> scope</td>
                    </tr>
                    <tr>
                      <td><strong>Brevo / Transactional SMTP</strong></td>
                      <td>Transactional email delivery</td>
                      <td>Official recipient email and single-use password reset URLs</td>
                    </tr>
                    <tr>
                      <td><strong>Cloudflare Pages</strong></td>
                      <td>Static frontend web hosting &amp; CDN</td>
                      <td>Encrypted static assets, client IP for edge delivery</td>
                    </tr>
                    <tr>
                      <td><strong>Render</strong></td>
                      <td>Backend application hosting</td>
                      <td>Containerized API execution and temporary encrypted caching</td>
                    </tr>
                    <tr>
                      <td><strong>PostgreSQL (Neon / Local)</strong></td>
                      <td>Relational database storage</td>
                      <td>Account records, metadata, verification statuses, and audit logs</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            {/* Section 9 */}
            <section id="section-9" className="privacy-card">
              <div className="privacy-section-head">
                <div className="privacy-icon-pill"><KeyRound size={20} /></div>
                <h2>9. User Privacy Rights &amp; Choices</h2>
              </div>
              <p>
                As an academic faculty member or administrator, you have the following rights regarding your information:
              </p>
              <ul>
                <li><strong>Access &amp; Inspection:</strong> You may review all patent records, personal profiles, and verification logs associated with your account by navigating to your dashboard.</li>
                <li><strong>Rectification of Inaccurate Records:</strong> If patent details or inventor names were misidentified by automated OCR, you or your department head may edit or resubmit the record.</li>
                <li><strong>Association Requests:</strong> You may accept or decline contributor association requests initiated by other faculty members.</li>
                <li><strong>Account Inquiries &amp; Deactivation:</strong> You may request account deactivation or inquire about stored data by contacting your institutional portal administrator.</li>
              </ul>
            </section>

            {/* Section 10 */}
            <section id="section-10" className="privacy-card">
              <div className="privacy-section-head">
                <div className="privacy-icon-pill"><Mail size={20} /></div>
                <h2>10. Contact &amp; Governance</h2>
              </div>
              <p>
                For privacy questions, access requests, or governance inquiries regarding this portal, please direct your communication to:
              </p>
              
              <div className="compact-card" style={{ marginTop: '12px' }}>
                <strong>Portal Technical Administrator:</strong>
                <p style={{ margin: '4px 0 0' }}>
                  Project Administrator: <a href="mailto:mohanprabu018@gmail.com" className="link">mohanprabu018@gmail.com</a><br />
                  GitHub Repository: <a href="https://github.com/MohanPrabu018-K/Faculty-Patent-Collection-and-Verification-Portal" target="_blank" rel="noopener noreferrer" className="link">Faculty-Patent-Collection-and-Verification-Portal</a>
                </p>
              </div>

              <div className="privacy-callout" style={{ marginTop: '16px' }}>
                <Shield size={18} className="privacy-callout-icon" />
                <div style={{ fontSize: '13px' }}>
                  <strong>Deploying Institution Notice:</strong> When deployed in production by an academic or research institution,
                  the deploying institution&rsquo;s Office of Intellectual Property / Dean of Research serves as the primary Data Controller.
                  Institutional administrators should specify their institutional contact address and Data Protection Officer before
                  formal institutional launch.
                </div>
              </div>

              <p style={{ marginTop: '16px', fontSize: '13px' }} className="muted">
                <strong>Policy Updates:</strong> This Privacy Policy may be updated periodically to reflect changes in storage backends,
                regulatory frameworks, or portal capabilities. Changes will be posted to this URL with a revised effective date.
              </p>
            </section>
          </article>
        </div>
      </main>

      {/* Footer */}
      <footer className="privacy-footer">
        <div className="privacy-footer-container">
          <div>
            &copy; {new Date().getFullYear()} Faculty Patent Collection &amp; Verification Portal. All rights reserved.
          </div>
          <div className="privacy-footer-links">
            <Link to="/login" className="link">Portal Login</Link>
            <span className="muted">&bull;</span>
            <a href="#section-1" className="link">Top of Policy</a>
          </div>
        </div>
      </footer>
    </div>
  );
}

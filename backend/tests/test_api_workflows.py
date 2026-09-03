import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestAuthWorkflow:
    """Test authentication workflow endpoints."""

    def test_csrf_token_endpoint(self):
        response = client.post("/api/v1/auth/csrf")
        assert response.status_code == 200
        assert "csrf_token" in response.json()
        assert len(response.json()["csrf_token"]) > 0

    def test_me_endpoint_requires_auth(self):
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401  # Missing credentials -> Unauthorized

    def test_logout_endpoint(self):
        response = client.post("/api/v1/auth/logout")
        assert response.status_code == 200
        assert response.json()["message"] == "Successfully logged out"

    def test_refresh_endpoint(self):
        response = client.post("/api/v1/auth/refresh")
        assert response.status_code == 200


class TestFacultyWorkflow:
    """Test faculty workflow endpoints."""

    def test_profile_endpoint_requires_auth(self):
        response = client.get("/api/v1/faculty/profile")
        assert response.status_code == 401

    def test_dashboard_endpoint_requires_auth(self):
        response = client.get("/api/v1/faculty/dashboard")
        assert response.status_code == 401

    def test_upload_endpoint_requires_auth(self):
        # POST without CSRF token -> CSRF middleware rejects (400) before auth.
        response = client.post("/api/v1/faculty/upload", files={"file": ("test.pdf", b"test", "application/pdf")})
        assert response.status_code in (400, 401)

    def test_my_records_endpoint_requires_auth(self):
        response = client.get("/api/v1/faculty/my-records")
        assert response.status_code == 401

    def test_record_status_endpoint_requires_auth(self):
        response = client.get("/api/v1/faculty/test-record-id/status")
        assert response.status_code == 401

    def test_request_verification_endpoint_requires_auth(self):
        response = client.post("/api/v1/faculty/test-record-id/request-verification")
        assert response.status_code in (400, 401)

    def test_request_association_endpoint_requires_auth(self):
        response = client.post("/api/v1/faculty/test-record-id/associate/other-faculty-id")
        assert response.status_code in (400, 401)


class TestSearchWorkflow:
    """Test search workflow endpoints."""

    def test_search_endpoint_requires_auth(self):
        response = client.get("/api/v1/search/")
        assert response.status_code == 401

    def test_suggestions_endpoint_requires_auth(self):
        response = client.get("/api/v1/search/suggestions?q=test")
        assert response.status_code == 401


class TestAnalyticsWorkflow:
    """Test analytics workflow endpoints."""

    def test_analytics_overview_requires_auth(self):
        response = client.get("/api/v1/analytics/overview")
        assert response.status_code == 401

    def test_analytics_by_faculty_requires_auth(self):
        response = client.get("/api/v1/analytics/by-faculty")
        assert response.status_code == 401

    def test_analytics_by_department_requires_auth(self):
        response = client.get("/api/v1/analytics/by-department")
        assert response.status_code == 401

    def test_analytics_trends_requires_auth(self):
        response = client.get("/api/v1/analytics/trends")
        assert response.status_code == 401


class TestExportsWorkflow:
    """Test exports workflow endpoints."""

    def test_create_export_requires_auth(self):
        # POST without CSRF -> CSRF middleware (400) before auth check.
        response = client.post("/api/v1/exports/")
        assert response.status_code in (400, 401)

    def test_get_export_status_requires_auth(self):
        response = client.get("/api/v1/exports/test-job-id")
        assert response.status_code == 401

    def test_download_export_requires_auth(self):
        response = client.get("/api/v1/exports/test-job-id/download")
        assert response.status_code == 401


class TestAdminWorkflow:
    """Test admin workflow endpoints."""

    def test_admin_endpoints_require_super_admin(self):
        # These endpoints should require super_admin role
        endpoints = [
            "/api/v1/admin/dashboard",
            "/api/v1/admin/faculty",
            "/api/v1/admin/departments",
            "/api/v1/admin/designations",
            "/api/v1/admin/ip-records",
            "/api/v1/admin/duplicates",
            "/api/v1/admin/conflicts",
            "/api/v1/admin/associations",
            "/api/v1/admin/verifications",
        ]
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code in [401, 403]  # Unauthenticated or forbidden


class TestVerificationWorkflow:
    """Test verification workflow endpoints."""

    def test_verification_endpoints_require_auth(self):
        endpoints = [
            "/api/v1/verification/sources",
            "/api/v1/verification/verify",
        ]
        for endpoint in endpoints:
            response = client.get(endpoint) if "verify" not in endpoint else client.post(endpoint, json={})
            assert response.status_code in [400, 401, 405]


class TestNotificationsAuditWorkflow:
    """Test notifications and audit workflow endpoints."""

    def test_notifications_endpoints_require_auth(self):
        endpoints = [
            "/api/v1/notifications/",
            "/api/v1/notifications/unread-count",
            "/api/v1/audit/logs",
            "/api/v1/audit/security-events",
        ]
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 401


class TestAssociationsWorkflow:
    """Test associations workflow endpoints."""

    def test_associations_endpoints_require_auth(self):
        endpoints = [
            "/api/v1/associations/",
            "/api/v1/associations/pending",
        ]
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 401


class TestDuplicatesWorkflow:
    """Test duplicates workflow endpoints."""

    def test_duplicates_endpoints_require_auth(self):
        endpoints = [
            "/api/v1/duplicates/",
        ]
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 401


class TestConflictsWorkflow:
    """Test conflicts workflow endpoints."""

    def test_conflicts_endpoints_require_auth(self):
        endpoints = [
            "/api/v1/conflicts/",
        ]
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 401


class TestIPRecordsWorkflow:
    """Test IP records workflow endpoints."""

    def test_ip_records_endpoints_require_auth(self):
        endpoints = [
            "/api/v1/ip-records/",
        ]
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 401


class TestUploadsWorkflow:
    """Test uploads workflow endpoints."""

    def test_uploads_endpoint_minimal(self):
        # Uploads router is minimal
        pass
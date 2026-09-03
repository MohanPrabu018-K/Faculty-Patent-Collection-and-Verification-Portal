import sys
sys.path.insert(0, r'E:\Faculty profile portal\backend')

# Test all major imports
print("=== Testing Imports ===")

from app.main import app
print("✓ app.main imported")

from app.core.config import app_settings, rate_limit_settings, get_settings
print("✓ app.core.config imported")

from app.core.security import hash_password, verify_password, generate_jwt_token, decode_jwt_token
print("✓ app.core.security imported")

from app.core.exceptions import PortalError, AuthenticationError, AuthorizationError, NotFoundError
print("✓ app.core.exceptions imported")

from app.core.logging import log_audit, log_security_event, get_logger
print("✓ app.core.logging imported")

from app.api.deps import get_current_user, get_session_data, require_role, require_super_admin, require_faculty
print("✓ app.api.deps imported")

from app.api.auth import router as auth_router
print("✓ app.api.auth imported")

from app.api.faculty import router as faculty_router
print("✓ app.api.faculty imported")

from app.api.admin import router as admin_router
print("✓ app.api.admin imported")

from app.api.uploads import router as upload_router
print("✓ app.api.uploads imported")

from app.api.ip_records import router as ip_records_router
print("✓ app.api.ip_records imported")

from app.api.associations import router as associations_router
print("✓ app.api.associations imported")

from app.api.duplicates import router as duplicates_router
print("✓ app.api.duplicates imported")

from app.api.conflicts import router as conflicts_router
print("✓ app.api.conflicts imported")

from app.api.verification import router as verification_router
print("✓ app.api.verification imported")

from app.api.search import router as search_router
print("✓ app.api.search imported")

from app.api.analytics import router as analytics_router
print("✓ app.api.analytics imported")

from app.api.exports import router as exports_router
print("✓ app.api.exports imported")

from app.api.notifications import router as notifications_router
print("✓ app.api.notifications imported")

from app.api.audit import router as audit_router
print("✓ app.api.audit imported")

from app.services.extraction import extraction_service, StructuredExtractionService, EvidenceTracker
print("✓ app.services.extraction imported")

from app.models.base import Base, User, Department, Designation, IpRecord, IpContributor
print("✓ app.models.base imported")

from app.workers.orchestrator_task import run_document_pipeline
print("✓ app.workers.orchestrator_task imported")

from app.services.ocr_pipeline import process_document, decode_qr_payloads, perform_ocr
print("✓ app.services.ocr_pipeline imported")

from alembic.config import Config
from alembic import command
print("✓ alembic imported")

print("\n=== All imports successful! ===")
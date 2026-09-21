import uuid
from contextlib import asynccontextmanager

from app.api.admin import router as admin_router
from app.api.associations import router as associations_router
from app.api.auth import router as auth_router
from app.api.excel_import import router as excel_import_router
from app.api.hod import router as hod_router
from app.api.conflicts import router as conflicts_router
from app.api.duplicates import router as duplicates_router
from app.api.faculty import router as faculty_router
from app.api.ip_records import router as ip_records_router
from app.api.notifications_audit import (
    audit_router,
    notifications_router,
)
from app.api.search_analytics_exports import (
    analytics_router,
    exports_router,
    router as search_router,
)
from app.api.uploads import router as upload_router
from app.api.verification import router as verification_router
from app.api.deps import get_current_user
from app.core.config import app_settings
from app.core.exceptions import (
    PortalError,
    portal_error_handler,
)
from app.core.performance import setup_performance_optimization
from app.core.security import validate_csrf_token
from app.core.security_middleware import setup_security_middleware
from app.services.scheduler import lifespan_scheduler

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


def create_app() -> FastAPI:
    app = FastAPI(
        title="Faculty Patent Collection Portal",
        version="0.1.0",
        description=(
            "Production-grade, free-first institutional web portal "
            "for patents and design registrations"
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan_scheduler,
    )

    # ---------------------------------------------------------
    # CORS
    # ---------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=(
            app_settings.cors_origins
            if hasattr(app_settings, "cors_origins")
            else ["http://localhost:5173"]
        ),
        allow_credentials=True,
        allow_methods=[
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "OPTIONS",
        ],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # ---------------------------------------------------------
    # Security / Performance Middleware
    # ---------------------------------------------------------
    setup_security_middleware(
        app,
        debug=app_settings.debug,
    )

    setup_performance_optimization(app)

    # ---------------------------------------------------------
    # Request Middleware
    # ---------------------------------------------------------
    @app.middleware("http")
    async def request_middleware(
        request: Request,
        call_next,
    ):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # CSRF protection for all state-changing requests,
        # except authentication endpoints.
        if request.method in (
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        ):
            if not request.url.path.startswith(
                "/api/v1/auth/"
            ):
                csrf_token = request.headers.get(
                    "X-CSRF-Token",
                    "",
                )

                session_token = request.cookies.get(
                    "csrf_token",
                    "",
                )

                if not validate_csrf_token(
                    csrf_token,
                    session_token,
                ):
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": "CSRF_TOKEN_INVALID",
                            "message": (
                                "Invalid or missing CSRF token"
                            ),
                        },
                    )

        # IMPORTANT:
        # Continue the request after middleware validation.
        response = await call_next(request)

        # Attach request ID to every response.
        response.headers["X-Request-ID"] = request_id

        # Basic security headers.
        response.headers[
            "X-Content-Type-Options"
        ] = "nosniff"

        response.headers[
            "X-Frame-Options"
        ] = "DENY"

        return response

    # ---------------------------------------------------------
    # Portal Error Handler
    # ---------------------------------------------------------
    @app.exception_handler(PortalError)
    async def portal_exception_handler(
        request: Request,
        exc: PortalError,
    ):
        return portal_error_handler(exc)

    # ---------------------------------------------------------
    # Global Exception Handler
    # ---------------------------------------------------------
    @app.exception_handler(Exception)
    async def global_exception_handler(
        request: Request,
        exc: Exception,
    ):
        import traceback

        print(
            "\n========== UNHANDLED EXCEPTION =========="
        )
        print(
            "PATH:",
            request.url.path,
        )
        print(
            "METHOD:",
            request.method,
        )
        print(
            "TYPE:",
            type(exc).__name__,
        )
        print(
            "ERROR:",
            repr(exc),
        )

        traceback.print_exc()

        print(
            "=========================================\n"
        )

        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            },
        )

    # ---------------------------------------------------------
    # Health / Readiness / Metrics
    # ---------------------------------------------------------
    @app.get(
        "/healthz",
        include_in_schema=False,
    )
    async def health_check():
        return {
            "status": "ok"
        }

    @app.get(
        "/readyz",
        include_in_schema=False,
    )
    async def readiness_check():
        return {
            "status": "ready"
        }

    @app.get(
        "/metrics",
        include_in_schema=False,
    )
    async def metrics():
        return {
            "status": "ok",
            "service": app_settings.app_name,
            "version": "0.1.0",
        }

    # ---------------------------------------------------------
    # API Routers
    # ---------------------------------------------------------
    app.include_router(
        auth_router,
        tags=["auth"],
    )

    app.include_router(
        faculty_router,
        tags=["faculty"],
    )

    app.include_router(
        admin_router,
        tags=["admin"],
    )

    app.include_router(
        hod_router,
        tags=["hod"],
    )

    app.include_router(
        excel_import_router,
        tags=["excel-import"],
    )

    app.include_router(
        upload_router,
        tags=["uploads"],
    )

    app.include_router(
        ip_records_router,
        tags=["ip-records"],
    )

    app.include_router(
        associations_router,
        tags=["associations"],
    )

    app.include_router(
        duplicates_router,
        tags=["duplicates"],
    )

    app.include_router(
        conflicts_router,
        tags=["conflicts"],
    )

    app.include_router(
        verification_router,
        tags=["verification"],
    )

    app.include_router(
        search_router,
        tags=["search"],
    )

    app.include_router(
        analytics_router,
        tags=["analytics"],
    )

    app.include_router(
        exports_router,
        tags=["exports"],
    )

    app.include_router(
        notifications_router,
        tags=["notifications"],
    )

    app.include_router(
        audit_router,
        tags=["audit"],
    )

    return app


# -------------------------------------------------------------
# Application Instance
# -------------------------------------------------------------
app = create_app()


# -------------------------------------------------------------
# Root Endpoint
# -------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "name": app_settings.app_name,
        "version": "0.1.0",
        "status": "operational",
    }
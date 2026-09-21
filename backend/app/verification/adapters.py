from __future__ import annotations

import asyncio
import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import re
import unicodedata

import structlog
from app.core.config import verification_settings
from app.core.logging import log_audit

try:
    from rapidfuzz import fuzz as _rf_fuzz
except Exception:  # pragma: no cover
    _rf_fuzz = None

logger = structlog.get_logger()


# --- Data Classes ---

@dataclass
class VerificationSource:
    """Represents an external verification source."""
    name: str
    display_name: str
    url: str
    supported_countries: list[str]
    supported_ip_types: list[str]
    rate_limit_rps: float = 1.0
    requires_api_key: bool = False


@dataclass
class VerificationRequest:
    """Request payload for verification."""
    ip_type: str
    identifier: str
    title: str | None = None
    applicant: str | None = None
    inventor: str | None = None
    filing_date: str | None = None
    country: str | None = None
    additional_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class FieldComparison:
    """Comparison between certificate and official field values."""
    field_name: str
    certificate_value: str | None
    official_value: str | None
    status: str  # MATCH, MISMATCH, MISSING_OFFICIAL, MISSING_CERTIFICATE, UNAVAILABLE, NEEDS_REVIEW
    confidence: float = 0.0


@dataclass
class VerificationResult:
    """Result of a verification attempt."""
    success: bool
    status: str  # VERIFIED, MISMATCH, NOT_FOUND, ERROR, VERIFICATION_REQUIRED
    source: str
    confidence: float
    matched_data: dict[str, Any] = field(default_factory=dict)
    raw_response: dict[str, Any] | None = None
    error: str | None = None
    verification_time_ms: float = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    field_comparisons: list[FieldComparison] = field(default_factory=list)


@dataclass
class CacheEntry:
    """Cached verification result."""
    result: VerificationResult
    cached_at: datetime
    expires_at: datetime


# --- Base Adapter ---

class VerificationAdapter(ABC):
    """Abstract base class for verification adapters."""

    def __init__(self, source: VerificationSource):
        self.source = source
        self.logger = logger.bind(adapter=source.name)

    @abstractmethod
    async def verify(self, request: VerificationRequest) -> VerificationResult:
        """Perform verification against this source."""
        pass

    @abstractmethod
    def get_source_name(self) -> str:
        """Return the source name."""
        pass

    def _create_result(
        self,
        success: bool,
        status: str,
        confidence: float,
        matched_data: dict[str, Any] = None,
        raw_response: dict[str, Any] = None,
        error: str = None,
        verification_time_ms: float = 0,
        field_comparisons: list[FieldComparison] = None,
    ) -> VerificationResult:
        return VerificationResult(
            success=success,
            status=status,
            source=self.get_source_name(),
            confidence=confidence,
            matched_data=matched_data or {},
            raw_response=raw_response,
            error=error,
            verification_time_ms=verification_time_ms,
            field_comparisons=field_comparisons or [],
        )

    def _compare_fields(
        self,
        request: VerificationRequest,
        official_data: dict[str, Any],
    ) -> list[FieldComparison]:
        """Compare certificate/extracted fields with official source data."""
        comparisons = []

        field_configs = [
            ("patent_number", "patent_number", 0.15),
            ("design_number", "design_number", 0.15),
            ("application_number", "application_number", 0.1),
            ("publication_number", "publication_number", 0.1),
            ("title", "title", 0.2),
            ("applicant", "applicant", 0.15),
            ("inventors", "inventors", 0.15),
            ("filing_date", "filing_date", 0.1),
        ]

        for req_field, off_field, weight in field_configs:
            # inventors is stored as `inventor` (singular) on VerificationRequest
            if req_field == "inventors":
                cert_value = getattr(request, "inventor", None)
                # Also support inventors list via additional_data for tests
                if not cert_value and isinstance(getattr(request, "additional_data", None), dict):
                    cert_value = request.additional_data.get("inventors")
                # Normalize single inventor to list for comparison
                if isinstance(cert_value, str):
                    cert_value = [cert_value]
                off_value = official_data.get(off_field)
                # Ensure off_value is list
                if isinstance(off_value, str):
                    off_value = [off_value]
            elif req_field in ("design_number", "patent_number", "application_number", "publication_number"):
                cert_value = getattr(request, req_field, None)
                # Fallback to identifier for primary identifier fields
                if not cert_value and getattr(request, "identifier", None):
                    if req_field == "design_number" and request.ip_type == "DESIGN_REGISTRATION":
                        cert_value = request.identifier
                    elif req_field == "patent_number" and request.ip_type == "PATENT":
                        cert_value = request.identifier
                    elif req_field == "application_number" and request.identifier:
                        # application_number may be same as patent for some flows
                        cert_value = request.identifier if not getattr(request, "design_number", None) and not getattr(request, "patent_number", None) else None
                off_value = official_data.get(off_field)
            else:
                cert_value = getattr(request, req_field, None)
                off_value = official_data.get(off_field)

            comparison = self._compare_single_field(
                req_field, cert_value, off_value, weight
            )
            comparisons.append(comparison)

        return comparisons

    def _compare_single_field(
        self,
        field_name: str,
        cert_value: Any,
        off_value: Any,
        weight: float,
    ) -> FieldComparison:
        """Compare a single field between certificate and official data."""
        # Field-aware normalization
        cert_norm = self._normalize_for_comparison(cert_value, field_name) if cert_value not in (None, "", []) else None
        off_norm = self._normalize_for_comparison(off_value, field_name) if off_value not in (None, "", []) else None

        if cert_norm is None and off_norm is None:
            status = "UNAVAILABLE"
            confidence = 0.0
        elif cert_norm is None:
            status = "MISSING_CERTIFICATE"
            confidence = 0.0
        elif off_norm is None:
            status = "MISSING_OFFICIAL"
            confidence = 0.0
        elif self._values_match(cert_norm, off_norm, field_name, cert_value, off_value):
            status = "MATCH"
            confidence = weight
        else:
            status = "MISMATCH"
            confidence = 0.0

        return FieldComparison(
            field_name=field_name,
            certificate_value=str(cert_value) if cert_value not in (None, "") else None,
            official_value=str(off_value) if off_value not in (None, "") else None,
            status=status,
            confidence=confidence,
        )

    def _normalize_for_comparison(self, value: Any, field_name: str | None = None) -> str | None:
        """Robust normalization: Unicode NFKC, casefold, whitespace, punctuation."""
        if value is None:
            return None
        if isinstance(value, list):
            normalized = [self._normalize_for_comparison(v, field_name) for v in value]
            # Filter None and empty
            filtered = [n for n in normalized if n]
            if not filtered:
                return None
            return "|".join(sorted(filtered))
        # String path
        s = str(value)
        # Unicode NFKC
        try:
            s = unicodedata.normalize("NFKC", s)
        except Exception:
            pass
        s = s.strip()
        if not s:
            return None
        # For identifiers: upper, keep alphanum + - / , strip other punctuation
        if field_name in ("patent_number", "design_number", "application_number", "publication_number", "filing_date"):
            s = s.upper()
            # Keep A-Z 0-9 - / for identifiers, and - for dates will be normalized via date logic elsewhere
            s = re.sub(r"[^A-Z0-9\-/]", "", s)
            return s.lower()  # keep lower for uniform cert/off comparison (both upper->lower)
        # For inventors/title/applicant: casefold, whitespace, punctuation
        s = s.casefold()
        # Replace punctuation with space, keep alphanum and space
        s = re.sub(r"[\"'.,;:!?()\[\]{}]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _values_match(self, cert_norm: str | None, off_norm: str | None, field_name: str, cert_raw: Any = None, off_raw: Any = None) -> bool:
        """Field-aware matching: identifiers exact, titles/applicants fuzzy with explicit threshold."""
        if not cert_norm or not off_norm:
            return False
        if cert_norm == off_norm:
            return True

        # Inventors: pipe-separated exact set logic (no substring, no fuzzy for names -> prevents Ashwin vs Ashwini)
        if field_name == "inventors" and "|" in cert_norm:
            cert_parts = set(cert_norm.split("|"))
            off_parts = set(off_norm.split("|"))
            # Require exact set equality or cert subset of official (all cert inventors present)
            return cert_parts.issubset(off_parts)

        # Identifiers and dates: exact only (prevents substring false positives)
        if field_name in ("patent_number", "design_number", "application_number", "publication_number", "filing_date"):
            return False

        # Title / applicant: controlled fuzzy via rapidfuzz, threshold 90 token_set
        if field_name in ("title", "applicant"):
            if _rf_fuzz is not None:
                try:
                    # token_set_ratio handles word order and extra words robustly
                    score = _rf_fuzz.token_set_ratio(cert_norm, off_norm)
                    if score >= 90:
                        return True
                    # Fallback ratio for short strings
                    if _rf_fuzz.ratio(cert_norm, off_norm) >= 92:
                        return True
                    return False
                except Exception:
                    return False
            # Without rapidfuzz, fall back to exact only (conservative)
            return False

        # Default: exact only (conservative)
        return False


# --- Cache Layer ---

class VerificationCache:
    """Thread-safe cache for verification results."""

    def __init__(self, ttl_seconds: int = 86400):
        self._cache: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self.ttl_seconds = ttl_seconds
        self.logger = logger.bind(component="verification_cache")

    def _make_key(self, request: VerificationRequest) -> str:
        """Generate cache key from request."""
        key_data = {
            "ip_type": request.ip_type,
            "identifier": request.identifier,
            "title": request.title,
            "applicant": request.applicant,
            "country": request.country,
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()

    async def get(self, request: VerificationRequest) -> VerificationResult | None:
        """Get cached result if valid."""
        key = self._make_key(request)
        async with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if datetime.now(UTC) < entry.expires_at:
                    self.logger.debug("cache_hit", source=self.source.name if hasattr(self, 'source') else "unknown", key=key)
                    return entry.result
                else:
                    del self._cache[key]
        return None

    async def set(self, request: VerificationRequest, result: VerificationResult):
        """Cache a result."""
        key = self._make_key(request)
        async with self._lock:
            now = datetime.now(UTC)
            self._cache[key] = CacheEntry(
                result=result,
                cached_at=now,
                expires_at=now + timedelta(seconds=self.ttl_seconds),
            )

    async def clear_expired(self):
        """Remove expired entries."""
        now = datetime.now(UTC)
        async with self._lock:
            expired = [k for k, v in self._cache.items() if now >= v.expires_at]
            for k in expired:
                del self._cache[k]


# --- Adapter Implementations ---

class ManualVerificationAdapter(VerificationAdapter):
    """Manual/fallback adapter - always returns VERIFICATION_REQUIRED."""

    def __init__(self):
        source = VerificationSource(
            name="manual",
            display_name="Manual Verification",
            url="",
            supported_countries=["ALL"],
            supported_ip_types=["PATENT", "DESIGN_REGISTRATION", "UNKNOWN_OTHER"],
            rate_limit_rps=100.0,
        )
        super().__init__(source)

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        """Always returns VERIFICATION_REQUIRED - human must verify manually."""
        self.logger.info("manual_verification_required", identifier=request.identifier)
        return self._create_result(
            success=False,
            status="VERIFICATION_REQUIRED",
            confidence=0.0,
            error="Manual verification required - no automated source available",
            field_comparisons=[],
        )

    def get_source_name(self) -> str:
        return "manual"


class FixtureVerificationAdapter(VerificationAdapter):
    """Deterministic fixture provider for automated testing — NOT a real official source.

    Maps identifier → canned `VerificationResult` (VERIFIED/MISMATCH/NOT_FOUND/etc.)
    without network. Used only in tests to prove field mapping, comparison, caching,
    retry safety and audit preservation. Never registered as default in production.
    """

    def __init__(self, fixtures: dict[str, dict[str, Any]] | None = None):
        source = VerificationSource(
            name="fixture",
            display_name="Fixture Verification (Test Only)",
            url="fixture://test",
            supported_countries=["IN", "ALL"],
            supported_ip_types=["PATENT", "DESIGN_REGISTRATION", "UNKNOWN_OTHER"],
            rate_limit_rps=100.0,
        )
        super().__init__(source)
        # identifier -> {status, matched_data, error, raw_response, field_comparisons_override}
        self.fixtures: dict[str, dict[str, Any]] = fixtures or {}
        self.call_count: dict[str, int] = {}

    def set_fixture(self, identifier: str, payload: dict[str, Any]):
        self.fixtures[identifier] = payload

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        ident = request.identifier or ""
        self.call_count[ident] = self.call_count.get(ident, 0) + 1

        # Simulate timeout / malformed / HTTP error via special fixture keys
        if ident == "__TIMEOUT__":
            raise TimeoutError("Simulated timeout for testing")
        if ident == "__HTTP_ERROR__":
            # Simulate HTTP error path as VERIFICATION_REQUIRED via India adapter logic
            return self._create_result(
                success=False,
                status="VERIFICATION_REQUIRED",
                confidence=0.0,
                error="Simulated HTTP 500",
                field_comparisons=[],
            )
        if ident == "__MALFORMED__":
            # Simulate malformed official response: return NOT_FOUND with raw_response that is not dict
            return self._create_result(
                success=False,
                status="VERIFICATION_REQUIRED",
                confidence=0.0,
                error="Malformed official response",
                raw_response=None,  # type: ignore
                field_comparisons=[],
            )

        fixture = self.fixtures.get(ident)
        if fixture is None:
            # Default not found
            return self._create_result(
                success=False,
                status="NOT_FOUND",
                confidence=0.85,
                error=f"Fixture not found for {ident}",
                field_comparisons=[],
            )

        status = fixture.get("status", "VERIFICATION_REQUIRED")
        # Build matched_data from fixture or from request for field comparison testing
        matched = fixture.get("matched_data")
        if matched is None and status in ("VERIFIED", "MISMATCH"):
            # Echo request fields as matched for VERIFIED case, slightly perturbed for MISMATCH
            matched = {
                "patent_number": request.identifier if request.ip_type == "PATENT" else None,
                "design_number": request.identifier if request.ip_type == "DESIGN_REGISTRATION" else None,
                "application_number": fixture.get("application_number"),
                "title": request.title,
                "applicant": request.applicant,
                "inventors": [request.inventor] if request.inventor else [],
                "filing_date": request.filing_date,
            }
            matched = {k: v for k, v in matched.items() if v not in (None, "", [])}
            if status == "MISMATCH" and "title" in matched:
                matched["title"] = matched["title"] + " MISMATCH_SUFFIX"

        # Use real comparison logic for field_comparisons unless overridden
        field_comparisons = fixture.get("field_comparisons")
        if field_comparisons is None and matched is not None:
            field_comparisons = self._compare_fields(request, matched)
        elif field_comparisons is None:
            field_comparisons = []

        # Determine success per adapter contract
        success = status in ("VERIFIED", "MISMATCH", "NOT_FOUND") and status != "VERIFICATION_REQUIRED"
        # For VERIFIED/MISMATCH we return success=True to allow caching
        if status in ("VERIFIED", "MISMATCH"):
            success = True
        elif status == "NOT_FOUND":
            success = False
        else:
            success = False

        return self._create_result(
            success=success,
            status=status,
            confidence=fixture.get("confidence", 0.9 if status == "VERIFIED" else 0.7 if status == "MISMATCH" else 0.85 if status == "NOT_FOUND" else 0.0),
            matched_data=matched or {},
            raw_response=fixture.get("raw_response", {"fixture": True, "identifier": ident}),
            error=fixture.get("error"),
            field_comparisons=field_comparisons,
        )

    def get_source_name(self) -> str:
        return "fixture"


class IndiaPatentOfficeAdapter(VerificationAdapter):
    """Look up an Indian patent / design registration by its number.

    The Indian Patent Office (IPO) does not publish an official free REST API.
    This adapter calls a configurable JSON endpoint
    (``verification_settings.ipindia_search_url``) that is expected to return a
    single record for a given number -- either the InPASS public-search backend
    or a thin self-hosted proxy in front of it.

    Expected response shape (all fields optional, parsed defensively)::

        {
          "found": true,
          "record": {
            "patent_number": "...",
            "application_number": "...",
            "design_number": "...",
            "title": "...",
            "applicant": "...",
            "inventors": ["..."],
            "filing_date": "YYYY-MM-DD",
            "grant_date": "YYYY-MM-DD",
            "registration_date": "YYYY-MM-DD",
            "status": "..."
          }
        }

    When the URL is not configured, the adapter is unreachable, or the response
    cannot be parsed, it returns ``VERIFICATION_REQUIRED`` so the pipeline
    degrades gracefully to manual verification (no mandatory key, per the
    project's free-first constraint).
    """

    def __init__(self, search_url: str = "", timeout_seconds: int = 15, enabled: bool = True):
        source = VerificationSource(
            name="ip_india",
            display_name="Indian Patent Office (IPO / InPASS)",
            url=search_url or "https://iprsearch.ipindia.gov.in/PublicSearch/",
            supported_countries=["IN"],
            supported_ip_types=["PATENT", "DESIGN_REGISTRATION"],
            rate_limit_rps=0.5,
            requires_api_key=False,
        )
        super().__init__(source)
        self.search_url = search_url
        self.timeout_seconds = timeout_seconds
        self.enabled = enabled

    def get_source_name(self) -> str:
        return "ip_india"

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        start_time = time.time()

        if not self.enabled or not self.search_url:
            return self._create_result(
                success=False,
                status="VERIFICATION_REQUIRED",
                confidence=0.0,
                error="Indian Patent Office lookup is not configured; manual verification required",
                field_comparisons=[],
            )

        try:
            import httpx
        except Exception as exc:  # pragma: no cover - dependency guard
            return self._create_result(
                success=False,
                status="VERIFICATION_REQUIRED",
                confidence=0.0,
                error=f"HTTP client unavailable: {exc}",
                field_comparisons=[],
            )

        params = {
            "number": request.identifier,
            "type": "design" if request.ip_type == "DESIGN_REGISTRATION" else "patent",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(self.search_url, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException:
            self.logger.warning("ip_india_lookup_timeout", identifier=request.identifier)
            return self._create_result(
                success=False,
                status="VERIFICATION_REQUIRED",
                confidence=0.0,
                error=f"Indian Patent Office lookup timed out after {self.timeout_seconds}s",
                field_comparisons=[],
                verification_time_ms=(time.time() - start_time) * 1000,
            )
        except httpx.HTTPStatusError as exc:
            self.logger.warning("ip_india_lookup_http_error", identifier=request.identifier, status=exc.response.status_code)
            return self._create_result(
                success=False,
                status="VERIFICATION_REQUIRED",
                confidence=0.0,
                error=f"Indian Patent Office returned HTTP {exc.response.status_code}",
                field_comparisons=[],
                verification_time_ms=(time.time() - start_time) * 1000,
            )
        except Exception as exc:
            self.logger.warning("ip_india_lookup_failed", identifier=request.identifier, error=str(exc))
            return self._create_result(
                success=False,
                status="VERIFICATION_REQUIRED",
                confidence=0.0,
                error=f"Indian Patent Office lookup failed: {exc}",
                field_comparisons=[],
                verification_time_ms=(time.time() - start_time) * 1000,
            )

        record = payload.get("record") or payload.get("data") or (payload if payload.get("title") else None)
        found = payload.get("found")
        if found is None:
            found = record is not None
        if not found or not record:
            return self._create_result(
                success=False,
                status="NOT_FOUND",
                confidence=0.85,
                error=f"No Indian {params['type']} record found for {request.identifier}",
                raw_response=payload if isinstance(payload, dict) else None,
                field_comparisons=[],
                verification_time_ms=(time.time() - start_time) * 1000,
            )

        matched = {
            "patent_number": record.get("patent_number") or record.get("patentNumber"),
            "application_number": record.get("application_number") or record.get("applicationNumber"),
            "design_number": record.get("design_number") or record.get("designNumber"),
            "title": record.get("title"),
            "applicant": record.get("applicant") or record.get("applicantName"),
            "inventors": record.get("inventors") or record.get("inventorNames") or [],
            "filing_date": record.get("filing_date") or record.get("filingDate"),
            "grant_date": record.get("grant_date") or record.get("grantDate"),
            "registration_date": record.get("registration_date") or record.get("registrationDate"),
            "status": record.get("status") or record.get("legalStatus"),
        }
        matched = {k: v for k, v in matched.items() if v not in (None, "", [])}

        # Perform field-level comparison
        field_comparisons = self._compare_fields(request, matched)

        # Determine overall status — VERIFIED safety: critical identifier must be positively matched
        has_mismatch = any(fc.status == "MISMATCH" for fc in field_comparisons)
        # Critical identifier check
        design_fc = next((fc for fc in field_comparisons if fc.field_name == "design_number"), None)
        patent_fc = next((fc for fc in field_comparisons if fc.field_name == "patent_number"), None)
        app_fc = next((fc for fc in field_comparisons if fc.field_name == "application_number"), None)
        if request.ip_type == "DESIGN_REGISTRATION":
            critical_ok = design_fc is not None and design_fc.status == "MATCH"
        elif request.ip_type == "PATENT":
            critical_ok = (patent_fc is not None and patent_fc.status == "MATCH") or (
                app_fc is not None and app_fc.status == "MATCH"
            )
        else:
            critical_ok = any(fc.status == "MATCH" for fc in field_comparisons if fc.field_name in ("patent_number", "design_number", "application_number"))

        if has_mismatch:
            status = "MISMATCH"
            confidence = 0.7
        elif not critical_ok:
            # Missing critical identifier must not become VERIFIED
            status = "VERIFICATION_REQUIRED"
            confidence = 0.0
        else:
            all_available_match = all(fc.status in ("MATCH", "MISSING_OFFICIAL", "UNAVAILABLE") for fc in field_comparisons)
            if all_available_match:
                status = "VERIFIED"
                confidence = 0.9
            else:
                # No mismatch but some MISSING_CERTIFICATE -> not VERIFIED
                has_missing_cert = any(fc.status == "MISSING_CERTIFICATE" for fc in field_comparisons)
                if has_missing_cert:
                    status = "VERIFICATION_REQUIRED"
                    confidence = 0.0
                else:
                    status = "VERIFIED"
                    confidence = 0.8

        return self._create_result(
            success=True,
            status=status,
            confidence=confidence,
            matched_data=matched,
            raw_response=payload if isinstance(payload, dict) else None,
            verification_time_ms=(time.time() - start_time) * 1000,
            field_comparisons=field_comparisons,
        )


# --- Registry & Orchestrator ---

class VerificationAdapterRegistry:
    """Registry for managing verification adapters."""

    def __init__(self):
        self._adapters: dict[str, VerificationAdapter] = {}
        self._default_adapter: VerificationAdapter | None = None
        self.cache = VerificationCache()

    def register(self, adapter: VerificationAdapter):
        """Register an adapter."""
        self._adapters[adapter.get_source_name()] = adapter
        logger.info("adapter_registered", source=adapter.get_source_name())

    def set_default(self, adapter: VerificationAdapter):
        """Set the default/fallback adapter."""
        self._default_adapter = adapter
        logger.info("default_adapter_set", source=adapter.get_source_name())

    def get_adapter(self, source_name: str) -> VerificationAdapter | None:
        """Get adapter by name."""
        return self._adapters.get(source_name)

    def get_adapters_for_request(self, request: VerificationRequest) -> list[VerificationAdapter]:
        """Get all adapters that can handle this request."""
        matching = []
        for adapter in self._adapters.values():
            if (request.ip_type in adapter.source.supported_ip_types and
                (not adapter.source.supported_countries or "ALL" in adapter.source.supported_countries or
                 request.country in adapter.source.supported_countries)):
                matching.append(adapter)
        return matching

    async def verify_with_cache(self, request: VerificationRequest, source_name: str | None = None) -> VerificationResult:
        """Verify with caching."""
        # Check cache first
        cached = await self.cache.get(request)
        if cached:
            cached.matched_data["from_cache"] = True
            return cached

        # Try specific adapter or all matching adapters
        if source_name:
            adapter = self.get_adapter(source_name)
            if not adapter:
                return VerificationResult(
                    success=False,
                    status="ERROR",
                    source=source_name,
                    confidence=0.0,
                    error=f"Adapter {source_name} not found",
                )
            adapters = [adapter]
        else:
            adapters = self.get_adapters_for_request(request)

        if not adapters:
            # Use default/fallback adapter
            if self._default_adapter:
                adapters = [self._default_adapter]
            else:
                return VerificationResult(
                    success=False,
                    status="ERROR",
                    source="none",
                    confidence=0.0,
                    error="No suitable verification adapter found",
                )

        # Try each adapter in order, skip VERIFICATION_REQUIRED results
        last_error_result = None
        for adapter in adapters:
            try:
                result = await adapter.verify(request)
                # Cache successful results
                if result.success:
                    await self.cache.set(request, result)
                    return result
                # If verification required, store as fallback but continue to next adapter
                if result.status == "VERIFICATION_REQUIRED":
                    last_error_result = result
                    continue
                # For other failures (NOT_FOUND, MISMATCH, ERROR), return immediately
                return result
            except Exception as e:
                logger.warning("adapter_failed", adapter=adapter.get_source_name(), error=str(e))
                continue

        # If all adapters returned VERIFICATION_REQUIRED, return the last one
        if last_error_result:
            return last_error_result

        # If all failed, return error
        return VerificationResult(
            success=False,
            status="ERROR",
            source="multiple",
            confidence=0.0,
            error="All verification adapters failed",
        )


# --- Global Registry ---

_verification_registry: VerificationAdapterRegistry | None = None


def get_verification_registry() -> VerificationAdapterRegistry:
    """Get or create the global verification registry."""
    global _verification_registry
    if _verification_registry is None:
        _verification_registry = VerificationAdapterRegistry()
        # Register default adapters
        _verification_registry.register(ManualVerificationAdapter())
        # Real free government source: Indian Patent Office (IPO / InPASS).
        # Disabled unless IPINDIA_SEARCH_URL is configured; degrades to manual.
        _verification_registry.register(
            IndiaPatentOfficeAdapter(
                search_url=verification_settings.ipindia_search_url,
                timeout_seconds=verification_settings.ipindia_timeout_seconds,
                enabled=verification_settings.ipindia_enabled,
            )
        )
        _verification_registry.set_default(ManualVerificationAdapter())
    return _verification_registry


async def verify_patent_or_design(
    ip_type: str,
    identifier: str,
    title: str | None = None,
    applicant: str | None = None,
    inventor: str | None = None,
    filing_date: str | None = None,
    country: str | None = None,
    source: str | None = None,
) -> VerificationResult:
    """High-level verification function for external use."""
    registry = get_verification_registry()

    request = VerificationRequest(
        ip_type=ip_type,
        identifier=identifier,
        title=title,
        applicant=applicant,
        inventor=inventor,
        filing_date=filing_date,
        country=country or verification_settings.default_country,
    )

    return await registry.verify_with_cache(request, source)


# --- Verification Service ---

class VerificationService:
    """High-level verification service integrating with database."""

    def __init__(self):
        self.registry = get_verification_registry()
        self.logger = logger.bind(service="verification")

    async def initiate_verification(
        self,
        ip_record_id: str,
        ip_type: str,
        identifier: str,
        title: str | None = None,
        applicant: str | None = None,
        inventor: str | None = None,
        filing_date: str | None = None,
        country: str | None = None,
        requested_by: str | None = None,
    ) -> dict[str, Any]:
        """Initiate verification for an IP record."""
        # In production, this would also persist a VerificationAttempt row before
        # running the (already async) lookup below.

        request = VerificationRequest(
            ip_type=ip_type,
            identifier=identifier,
            title=title,
            applicant=applicant,
            inventor=inventor,
            filing_date=filing_date,
            country=country or verification_settings.default_country,
        )
        
        # Try verification
        result = await self.registry.verify_with_cache(request)
        
        # Log audit
        log_audit(
            actor=requested_by or "system",
            action="VERIFICATION_INITIATED",
            target_type="ip_record",
            target_id=ip_record_id,
            status="initiated",
            before={"verification_status": "UNVERIFIED"},
            after={"verification_status": "VERIFICATION_INITIATED"},
            extra={
                "identifier": identifier,
                "ip_type": ip_type,
                "source": result.source,
            },
        )
        
        return {
            "verification_id": f"ver-{ip_record_id}-{int(time.time())}",
            "status": result.status,
            "source": result.source,
            "confidence": result.confidence,
            "matched_data": result.matched_data,
            "message": "Verification completed" if result.success else f"Verification {result.status}: {result.error}",
        }

    async def get_verification_sources(self, country: str | None = None, ip_type: str | None = None) -> list[dict[str, Any]]:
        """Get available verification sources."""
        registry = get_verification_registry()
        sources = []
        
        for adapter in registry._adapters.values():
            if (not ip_type or ip_type in adapter.source.supported_ip_types) and \
               (not country or not adapter.source.supported_countries or "ALL" in adapter.source.supported_countries or country in adapter.source.supported_countries):
                sources.append({
                    "name": adapter.get_source_name(),
                    "display_name": adapter.source.display_name,
                    "url": adapter.source.url,
                    "supported_countries": adapter.source.supported_countries,
                    "supported_ip_types": adapter.source.supported_ip_types,
                    "requires_api_key": adapter.source.requires_api_key,
                    "rate_limit_rps": adapter.source.rate_limit_rps,
                })
        
        return sources


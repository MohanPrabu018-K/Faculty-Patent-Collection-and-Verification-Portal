from __future__ import annotations

import asyncio
import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from app.core.config import verification_settings
from app.core.logging import log_audit

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
class VerificationResult:
    """Result of a verification attempt."""
    success: bool
    status: str  # VERIFIED, MISMATCH, NOT_FOUND, ERROR
    source: str
    confidence: float
    matched_data: dict[str, Any] = field(default_factory=dict)
    raw_response: dict[str, Any] | None = None
    error: str | None = None
    verification_time_ms: float = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


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
        )


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
        )

    def get_source_name(self) -> str:
        return "manual"


def _fuzzy_contains(a: str, b: str) -> bool:
    """Loose substring/equality match, case-insensitive."""
    a_clean = (a or "").lower().strip()
    b_clean = (b or "").lower().strip()
    if not a_clean or not b_clean:
        return False
    return a_clean in b_clean or b_clean in a_clean or a_clean == b_clean

def _field_match_confidence(request: VerificationRequest, data: dict[str, Any]) -> float:
    """Score how well the extracted fields agree with the source record (0..1)."""
    score = 0.0
    max_score = 0.0
    if request.title and data.get("title"):
        max_score += 0.4
        if _fuzzy_contains(request.title, data["title"]):
            score += 0.4
    if request.applicant and data.get("applicant"):
        max_score += 0.3
        if _fuzzy_contains(request.applicant, data["applicant"]):
            score += 0.3
    inventors = data.get("inventors") or []
    if request.inventor and inventors:
        max_score += 0.2
        if any(_fuzzy_contains(request.inventor, inv) for inv in inventors):
            score += 0.2
    if request.filing_date and data.get("filing_date"):
        max_score += 0.1
        if str(request.filing_date)[:10] == str(data["filing_date"])[:10]:
            score += 0.1
    return score / max_score if max_score > 0 else 0.5


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
            )

        try:
            import httpx
        except Exception as exc:  # pragma: no cover - dependency guard
            return self._create_result(
                success=False,
                status="VERIFICATION_REQUIRED",
                confidence=0.0,
                error=f"HTTP client unavailable: {exc}",
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
        except Exception as exc:
            self.logger.warning("ip_india_lookup_failed", identifier=request.identifier, error=str(exc))
            return self._create_result(
                success=False,
                status="VERIFICATION_REQUIRED",
                confidence=0.0,
                error=f"Indian Patent Office lookup failed: {exc}",
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

        field_conf = _field_match_confidence(request, matched)
        confidence = min(0.9 + field_conf * 0.1, 1.0)

        return self._create_result(
            success=True,
            status="VERIFIED",
            confidence=confidence,
            matched_data=matched,
            raw_response=payload if isinstance(payload, dict) else None,
            verification_time_ms=(time.time() - start_time) * 1000,
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


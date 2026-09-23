from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


# ============================================================
# GENERAL TEXT HELPERS
# ============================================================

def _clean_text(value: str | None) -> str:
    """Normalize OCR text while preserving line boundaries."""
    if not value:
        return ""

    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u00a0", " ")
    value = re.sub(r"[ \t]+", " ", value)

    return value.strip()


def _clean_inline_text(value: str | None) -> str:
    """Normalize a single-line OCR field."""
    if not value:
        return ""

    value = value.replace("\r\n", " ")
    value = value.replace("\r", " ")
    value = value.replace("\n", " ")
    value = value.replace("\u00a0", " ")

    value = re.sub(r"\s+", " ", value)

    return value.strip(" \t\r\n:;,-")


def _clean_ocr_fragment(value: str | None) -> str:
    """Clean a short OCR fragment."""
    if not value:
        return ""

    value = value.replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


# Terminator for single-line OCR fields: a blank line or end of text. Real OCR
# output frequently emits whitespace-only "blank" lines (e.g. "\n \n"), so a
# bare "\n{2,}" misses the terminator and drops the field entirely.
FIELD_BLANK_LINE = r"(?:\n\s*\n|$)"


# ============================================================
# DATE NORMALIZATION
# ============================================================

def normalize_date(raw: str) -> date | None:
    """Normalize a date string.

    Indian Patent Office documents use DD/MM/YYYY
    for slash-separated dates.
    """

    if not raw:
        return None

    raw = _clean_inline_text(raw)

    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%Y %m %d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    # Conservative OCR cleanup.
    cleaned = re.sub(
        r"[^0-9A-Za-z/\-, ]+",
        "",
        raw,
    ).strip()

    if cleaned != raw:
        for fmt in formats:
            try:
                return datetime.strptime(
                    cleaned,
                    fmt,
                ).date()
            except ValueError:
                continue

    logger.warning(
        "date_normalization_failed",
        raw=raw,
    )

    return None


def normalize_year(raw: str) -> int | None:
    """Extract a valid year."""
    if not raw:
        return None

    matches = re.findall(
        r"(\d{4})",
        raw,
    )

    if not matches:
        return None

    try:
        year = int(matches[0])

        if 1900 <= year <= 2100:
            return year

    except ValueError:
        pass

    return None


# ============================================================
# IDENTIFIER NORMALIZATION
# ============================================================

def normalize_patent_number(raw: str) -> str | None:
    """Normalize patent number."""
    if not raw:
        return None

    normalized = raw.strip().upper()

    normalized = re.sub(
        r"[^A-Z0-9\-]",
        "",
        normalized,
    )

    if len(normalized) >= 4:
        return normalized

    return None


def normalize_design_number(raw: str) -> str | None:
    """Normalize design registration number."""
    if not raw:
        return None

    normalized = raw.strip().upper()

    normalized = re.sub(
        r"[^A-Z0-9\-]",
        "",
        normalized,
    )

    if len(normalized) >= 3:
        return normalized

    return None


def normalize_application_number(raw: str) -> str | None:
    """Normalize patent application number."""
    if not raw:
        return None

    normalized = raw.strip().upper()

    normalized = re.sub(
        r"[^A-Z0-9/\-]",
        "",
        normalized,
    )

    if len(normalized) >= 3:
        return normalized

    return None


# ============================================================
# CONTRIBUTOR NORMALIZATION
# ============================================================

def normalize_contributor_name(raw: str) -> str:
    """Normalize contributor name."""
    if not raw:
        return "UNKNOWN"

    name = _clean_inline_text(raw)

    name = re.sub(
        r"[.,;:]+$",
        "",
        name,
    ).strip()

    return name or "UNKNOWN"


def normalize_designation(raw: str) -> str | None:
    """Normalize faculty designation."""
    if not raw:
        return None

    raw = _clean_inline_text(raw)

    designation_map = {
        "assoc. prof.": "Associate Professor",
        "assoc prof.": "Associate Professor",
        "assoc prof": "Associate Professor",
        "associate prof.": "Associate Professor",
        "associate prof": "Associate Professor",
        "associate": "Associate Professor",

        "assistant prof.": "Assistant Professor",
        "assistant prof": "Assistant Professor",
        "asst. prof.": "Assistant Professor",
        "asst prof": "Assistant Professor",
        "assistant": "Assistant Professor",

        "prof.": "Professor",
        "prof": "Professor",
        "professor": "Professor",

        "associate professor": "Associate Professor",
        "assistant professor": "Assistant Professor",

        "lecturer": "Lecturer",
        "senior lecturer": "Senior Lecturer",
        "head": "Head",
    }

    key = raw.lower()

    return designation_map.get(
        key,
        raw,
    )


def normalize_department(raw: str) -> str | None:
    """Normalize department names."""
    if not raw:
        return None

    raw = _clean_inline_text(raw)

    department_map = {
        "computer science":
            "Computer Science",

        "computer science and engineering":
            "Computer Science and Engineering",

        "computer science & engineering":
            "Computer Science & Engineering",

        "cs":
            "Computer Science",

        "cse":
            "Computer Science and Engineering",

        "information science":
            "Information Science",

        "information science and engineering":
            "Information Science and Engineering",

        "information science & engineering":
            "Information Science & Engineering",

        "electrical engineering":
            "Electrical Engineering",

        "mechanical engineering":
            "Mechanical Engineering",

        "artificial intelligence and data science":
            "Artificial Intelligence and Data Science",

        "artificial intelligence & data science":
            "Artificial Intelligence & Data Science",

        "data science":
            "Data Science",
    }

    key = raw.lower()

    return department_map.get(
        key,
        raw,
    )


# ============================================================
# EVIDENCE TRACKING
# ============================================================

class EvidenceTracker:
    """Tracks extraction evidence."""

    def __init__(self):
        self.evidence: dict[
            str,
            list[dict[str, Any]]
        ] = {}

    def add(
        self,
        field: str,
        value: Any,
        source: str,
        confidence: float,
        qr_data: str | None = None,
    ):
        """Add evidence."""

        if field not in self.evidence:
            self.evidence[field] = []

        self.evidence[field].append(
            {
                "value": value,
                "source": source,
                "confidence": confidence,
                "qr_data": qr_data,
            }
        )

    def get(
        self,
        field: str,
    ) -> list[dict[str, Any]] | None:
        return self.evidence.get(field)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe evidence structure."""

        return {
            field: [
                {
                    "value": item["value"],
                    "source": item["source"],
                    "confidence": item["confidence"],
                }
                for item in entries
            ]
            for field, entries in self.evidence.items()
        }


# ============================================================
# MAIN EXTRACTION SERVICE
# ============================================================

class StructuredExtractionService:
    """Deterministic structured extraction service.

    No LLM.
    No external AI API.
    No paid service dependency.
    """

    def __init__(self):
        self.evidence_tracker = EvidenceTracker()

    # ========================================================
    # PUBLIC API
    # ========================================================

    def extract_from_text(
        self,
        text: str,
        ip_type: str,
        qr_data: str | None = None,
    ) -> dict[str, Any]:
        """Extract structured fields from OCR text."""

        self.evidence_tracker = EvidenceTracker()

        text = _clean_text(text)

        result: dict[str, Any] = {
            "ip_type": ip_type,
            "normalized_fields": {},
            "confidence": 0.0,
            "evidence": {},
            "status": "partial",
            "requires_review": False,
            "conflicts": [],
        }

        if not text:
            result["confidence"] = 0.1
            result["requires_review"] = True
            result["status"] = "awaiting_review"

            return result

        if ip_type == "PATENT":
            self._extract_patent_fields(
                text,
                qr_data,
            )

        elif ip_type == "DESIGN_REGISTRATION":
            self._extract_design_fields(
                text,
                qr_data,
            )

        else:
            self._extract_generic_fields(
                text,
            )

        result["normalized_fields"] = (
            self.evidence_tracker.to_dict()
        )

        result["evidence"] = (
            result["normalized_fields"]
        )

        result["confidence"] = (
            self._calculate_confidence()
        )

        result["requires_review"] = (
            self._check_review_required(
                ip_type,
                result["confidence"],
            )
        )

        result["status"] = (
            "complete"
            if not result["requires_review"]
            else "awaiting_review"
        )

        return result

    # ========================================================
    # PATENT EXTRACTION
    # ========================================================

    def _extract_patent_fields(
        self,
        text: str,
        qr_data: str | None,
    ):
        """Extract patent fields."""

        if qr_data:
            patent_number = (
                normalize_patent_number(
                    qr_data
                )
            )

            if patent_number:
                self.evidence_tracker.add(
                    "patent_number",
                    patent_number,
                    "qr_code",
                    0.9,
                    qr_data,
                )

        if (
            "patent_number"
            not in self.evidence_tracker.evidence
        ):
            patterns = [
                r"patent\s+no\.?\s*[:\-]?\s*"
                r"([A-Z0-9][A-Z0-9/\-]*)",

                r"patent\s+number\s*[:\-]?\s*"
                r"([A-Z0-9][A-Z0-9/\-]*)",

                r"no\.?\s*patent\s*[:\-]?\s*"
                r"([A-Z0-9][A-Z0-9/\-]*)",
            ]

            for pattern in patterns:
                match = re.search(
                    pattern,
                    text,
                    re.IGNORECASE,
                )

                if not match:
                    continue

                patent_number = (
                    normalize_patent_number(
                        match.group(1)
                    )
                )

                if patent_number:
                    self.evidence_tracker.add(
                        "patent_number",
                        patent_number,
                        "ocr_text",
                        0.6,
                        qr_data,
                    )

                    break

        # ----------------------------------------------------
        # Application number (patent application publications / journals).
        #
        # WIPO ST.16 numbered field, e.g.:
        #   (21) Application No.202441103691 A
        # Generic form, e.g.:
        #   Application No: 202441103691
        # ----------------------------------------------------

        if (
            "application_number"
            not in self.evidence_tracker.evidence
        ):
            app_patterns = [
                r"\(21\)\s*application\s*no\.?"
                r"\s*([0-9][0-9A-Z/\-]*)",

                r"application\s*(?:number|no\.?)"
                r"\s*[:\-\s]\s*"
                r"([A-Z0-9][A-Z0-9/\-]*)",
            ]

            for pattern in app_patterns:
                match = re.search(
                    pattern,
                    text,
                    re.IGNORECASE,
                )

                if not match:
                    continue

                application_number = (
                    normalize_application_number(
                        match.group(1)
                    )
                )

                if application_number:
                    self.evidence_tracker.add(
                        "application_number",
                        application_number,
                        "ocr_text",
                        0.75,
                        qr_data,
                    )
                    break

        title_match = re.search(
            r"title(?:\s+of\s+the\s+invention)?"
            r"\s*[:\-]\s*(.+?)" + FIELD_BLANK_LINE,
            text,
            re.IGNORECASE,
        )

        if title_match:
            title = _clean_inline_text(
                title_match.group(1)
            )

            if title:
                self.evidence_tracker.add(
                    "title",
                    title[:300],
                    "ocr_text",
                    0.6,
                    qr_data,
                )

        filing_patterns = [
            r"filing\s+date\s*[:\-]\s*([^\n]+)",
            r"application\s+date\s*[:\-]\s*([^\n]+)",
            r"date\s+of\s+filing(?:\s+of\s+application)?"
            r"\s*[:\-]\s*([^\n]+)",
        ]

        for pattern in filing_patterns:
            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if not match:
                continue

            raw = _clean_inline_text(
                match.group(1)
            )

            normalized = normalize_date(raw)

            if normalized:
                self.evidence_tracker.add(
                    "filing_date",
                    normalized,
                    "ocr_text",
                    0.6,
                    qr_data,
                )
                break

            year = normalize_year(raw)

            if year:
                self.evidence_tracker.add(
                    "filing_date",
                    year,
                    "ocr_text",
                    0.3,
                    qr_data,
                )
                break

        publication_match = re.search(
            r"publication\s+date\s*[:\-]\s*([^\n]+)",
            text,
            re.IGNORECASE,
        )

        if publication_match:
            normalized = normalize_date(
                _clean_inline_text(
                    publication_match.group(1)
                )
            )

            if normalized:
                self.evidence_tracker.add(
                    "published_date",
                    normalized,
                    "ocr_text",
                    0.6,
                    qr_data,
                )

        # Bug 9: grant-date phrasings vary across certificate/journal forms.
        # The separator after the label is optional (e.g. "Granted on
        # 15 March 2024", "Date of Grant 22/10/2024"), and Indian forms add a
        # qualifier ("Date of Grant of Patent: ..."). Separator-less variants
        # capture a strict date-shaped token (never rest-of-line) so stray
        # text cannot produce a false date; a bare 4-digit year is still
        # accepted at low confidence via the dedicated year pattern.
        _DATE_TOKEN = (
            r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
            r"|\d{4}[/-]\d{1,2}[/-]\d{1,2}"
            r"|\d{1,2}\s+[A-Za-z]+\s*,?\s*\d{4}"
            r"|[A-Za-z]+\s+\d{1,2}\s*,?\s*\d{4})"
        )
        grant_patterns = [
            rf"grant\s+date\s*[:\-]?\s*{_DATE_TOKEN}",
            rf"date\s+of\s+grant(?:\s+of\s+[A-Za-z]+)?\s*[:\-]?\s*{_DATE_TOKEN}",
            rf"granted\s+on\s*[:\-]?\s*{_DATE_TOKEN}",
            rf"date\s+granted\s*[:\-]?\s*{_DATE_TOKEN}",
            rf"granted\s*[:\-]\s*{_DATE_TOKEN}",
        ]

        for pattern in grant_patterns:
            grant_match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if grant_match:
                raw = _clean_inline_text(
                    grant_match.group(1)
                )

                normalized = normalize_date(raw)

                if normalized:
                    self.evidence_tracker.add(
                        "grant_date",
                        normalized,
                        "ocr_text",
                        0.6,
                        qr_data,
                    )
                    break

                year = normalize_year(raw)

                if year:
                    self.evidence_tracker.add(
                        "grant_date",
                        year,
                        "ocr_text",
                        0.3,
                        qr_data,
                    )
                    break

        grant_year_match = re.search(
            r"(?:grant\s+date|date\s+of\s+grant|granted\s+on|date\s+granted|granted)\s*[:\-]\s*(\d{4})\b",
            text,
            re.IGNORECASE,
        )
        if grant_year_match and not self.evidence_tracker.get("grant_date"):
            year = normalize_year(grant_year_match.group(1))
            if year:
                self.evidence_tracker.add(
                    "grant_date",
                    year,
                    "ocr_text",
                    0.3,
                    qr_data,
                )

        # ----------------------------------------------------
        # Inventors.
        #
        # Journal form uses the WIPO ST.16 (72) numbered-inventor list, e.g.:
        #   (72)Name of Inventor :
        #      1)Dr. N. DEVAKIRUBAI
        #      2)N. PUSHPA
        # Plain form ("Inventor(s): ...") is kept as fallback.
        # ----------------------------------------------------

        inventors = self._extract_journal_inventors(
            text
        )

        if not inventors:
            inventor_match = re.search(
                r"inventors?\s*[:\-]\s*"
                r"(.+?)" + FIELD_BLANK_LINE,
                text,
                re.IGNORECASE,
            )

            if inventor_match:
                raw = inventor_match.group(1)

                for item in re.split(
                    r",|;|\band\b",
                    raw,
                    flags=re.IGNORECASE,
                ):
                    name = normalize_contributor_name(
                        item
                    )

                    if name != "UNKNOWN":
                        inventors.append(name)

        if inventors:
            self.evidence_tracker.add(
                "inventors",
                inventors,
                "ocr_text",
                0.5,
                qr_data,
            )

            # Mirror inventors as canonical contributors. Downstream stages
            # (faculty identity resolution, association recommendation) consume
            # the canonical `contributors` contract — without this, patent
            # inventors are invisible to identity matching and every patent
            # contributor degrades to EXTERNAL, exactly like design
            # contributors already do via _extract_design_contributors.
            self.evidence_tracker.add(
                "contributors",
                [{"name": name} for name in inventors],
                "ocr_text",
                0.5,
                qr_data,
            )

        # ----------------------------------------------------
        # Applicant.
        #
        # Journal form, e.g.:
        #   (71)Name of Applicant :
        #      1)R P SARATHY INSTITUTE OF TECHNOLOGY
        # Plain form ("Applicant: ...") is kept as fallback.
        # ----------------------------------------------------

        applicant_match = re.search(
            r"(?:\(71\)\s*)?name\s+of\s+applicant"
            r"\s*:?\s*(?:\d+[.)]\s*)?([^\n]+)",
            text,
            re.IGNORECASE,
        )

        if not applicant_match:
            applicant_match = re.search(
                r"(?:applicant|patentee)"
                r"\s*[:\-]\s*(.+?)" + FIELD_BLANK_LINE,
                text,
                re.IGNORECASE,
            )

        if applicant_match:
            applicant = _clean_inline_text(
                applicant_match.group(1)
            )

            if applicant:
                self.evidence_tracker.add(
                    "applicant",
                    applicant[:300],
                    "ocr_text",
                    0.5,
                    qr_data,
                )

    def _extract_journal_inventors(
        self,
        text: str,
    ) -> list[str]:
        """Extract numbered inventor lists from patent journals.

        Matches the WIPO ST.16 ``(72) Name of Inventor`` section found in
        patent office journals, where each inventor is a numbered entry
        (``1)Name ... 2)Name ...``) possibly followed by address lines.
        Only the first (name) line of each entry is kept; the section ends
        at the next numbered ``(NN)`` section marker. Returns [] when the
        section is absent so plain ``Inventor(s):`` parsing can apply.
        """

        start_match = re.search(
            r"\(72\)\s*name\s+of\s+inventors?\s*:?",
            text,
            re.IGNORECASE,
        )

        if not start_match:
            return []

        rest = text[start_match.end():]

        end_match = re.search(
            r"\(\d{2}\)|\babstract\s*:",
            rest,
            re.IGNORECASE,
        )

        region = (
            rest[: end_match.start()]
            if end_match
            else rest
        )

        inventors: list[str] = []

        for chunk in re.split(
            r"(?m)^\s*\d+[.)]\s*",
            region,
        ):
            for line in chunk.splitlines():
                name = normalize_contributor_name(line)

                if name == "UNKNOWN":
                    continue

                lowered = name.lower()

                if lowered.startswith("address"):
                    continue

                if "name of applicant" in lowered:
                    continue

                inventors.append(name)
                break

        unique: list[str] = []
        seen: set[str] = set()

        for name in inventors:
            key = name.strip().lower()

            if key in seen:
                continue

            seen.add(key)
            unique.append(name)

        return unique

    # ========================================================
    # DESIGN EXTRACTION
    # ========================================================

    def _extract_design_fields(
        self,
        text: str,
        qr_data: str | None,
    ):
        """Extract Indian Design Registration fields."""

        text = _clean_text(text)

        document_type = (
            self._detect_design_document_type(
                text
            )
        )

        # ----------------------------------------------------
        # Design number
        # ----------------------------------------------------

        design_number = (
            self._extract_design_number(
                text,
                qr_data,
            )
        )

        if design_number:
            qr_number = (
                normalize_design_number(qr_data)
                if qr_data
                else None
            )

            if qr_number == design_number:
                source = "qr_code"
                confidence = 0.95
            else:
                source = "ocr_text"
                confidence = 0.85

            self.evidence_tracker.add(
                "design_number",
                design_number,
                source,
                confidence,
                qr_data,
            )

        # ----------------------------------------------------
        # Isolate current design record
        # ----------------------------------------------------

        record_text = (
            self._extract_design_record(
                text,
                design_number,
            )
        )

        # ----------------------------------------------------
        # Serial number
        # ----------------------------------------------------

        serial_match = re.search(
            r"serial\s*(?:no\.?|number)?"
            r"\s*[:\-]?\s*"
            r"([0-9A-Z][0-9A-Z/\-]*)",
            text,
            re.IGNORECASE,
        )

        if serial_match:
            serial = _clean_inline_text(
                serial_match.group(1)
            )

            if serial:
                self.evidence_tracker.add(
                    "serial_number",
                    serial,
                    "ocr_text",
                    0.85,
                    qr_data,
                )

        # ----------------------------------------------------
        # Class
        # ----------------------------------------------------

        class_match = re.search(
            r"\bclass\s*[:\-]?\s*"
            r"([0-9]{1,2}\s*-\s*[0-9]{1,2})\b",
            record_text,
            re.IGNORECASE,
        )

        if class_match:
            design_class = re.sub(
                r"\s+",
                "",
                class_match.group(1),
            )

            self.evidence_tracker.add(
                "class",
                design_class,
                "ocr_text",
                0.9,
                qr_data,
            )

        # ----------------------------------------------------
        # Title
        # ----------------------------------------------------

        title = self._extract_design_title(
            record_text
        )

        if title:
            self.evidence_tracker.add(
                "title",
                title[:300],
                "ocr_text",
                0.9,
                qr_data,
            )

        # ----------------------------------------------------
        # Registration date
        #
        # Journal:
        # Date of Registration : 22/10/2024
        #
        # Certificate:
        # Design No. : 435272-001
        # Date       : 22/10/2024
        # ----------------------------------------------------

        if document_type == "CERTIFICATE":
            registration_date = (
                self._extract_certificate_registration_date(
                    text
                )
            )
        else:
            registration_date = (
                self._extract_registration_date(
                    record_text
                )
            )

        if registration_date:
            self.evidence_tracker.add(
                "registration_date",
                registration_date,
                "ocr_text",
                0.9,
                qr_data,
            )

        # ----------------------------------------------------
        # Certificate date
        #
        # ONLY certificate documents.
        # ----------------------------------------------------

        if document_type == "CERTIFICATE":
            certificate_date = (
                self._extract_certificate_date(
                    text,
                    registration_date,
                )
            )

            if certificate_date:
                self.evidence_tracker.add(
                    "certificate_date",
                    certificate_date,
                    "ocr_text",
                    0.9,
                    qr_data,
                )

        # ----------------------------------------------------
        # Priority
        # ----------------------------------------------------

        priority_match = re.search(
            r"\bpriority\b\s*[:\-]?\s*([^\n]+)",
            record_text,
            re.IGNORECASE,
        )

        if priority_match:
            priority = _clean_inline_text(
                priority_match.group(1)
            )

            if priority.upper() not in {
                "",
                "NA",
                "N/A",
                "NIL",
                "NONE",
            }:
                self.evidence_tracker.add(
                    "priority",
                    priority,
                    "ocr_text",
                    0.5,
                    qr_data,
                )

        # ----------------------------------------------------
        # Contributors
        # ----------------------------------------------------

        contributors = (
            self._extract_design_contributors(
                record_text,
                document_text=text,
                document_type=document_type,
            )
        )

        if contributors:
            self.evidence_tracker.add(
                "contributors",
                contributors,
                "ocr_text",
                0.9,
                qr_data,
            )

            inventor_names = [
                item["name"]
                for item in contributors
                if item.get("name")
            ]

            if inventor_names:
                self.evidence_tracker.add(
                    "inventors",
                    inventor_names,
                    "ocr_text",
                    0.9,
                    qr_data,
                )

        # ----------------------------------------------------
        # Applicant
        #
        # Applicant is certificate-specific and must come from an explicit
        # proprietor statement ("in the name of ..."). Joint proprietors
        # are stored as one clean human-readable string. When the document
        # does not name an applicant, nothing is stored: contributor names
        # must never be silently converted into an applicant.
        # ----------------------------------------------------

        if document_type == "CERTIFICATE":
            applicant_names = (
                self._extract_certificate_applicants(
                    text
                )
            )

            if applicant_names:
                self.evidence_tracker.add(
                    "applicant",
                    ", ".join(applicant_names),
                    "ocr_text",
                    0.85,
                    qr_data,
                )

    # ========================================================
    # DESIGN DOCUMENT TYPE
    # ========================================================

    def _detect_design_document_type(
        self,
        text: str,
    ) -> str:
        """Detect journal vs design certificate."""

        lower = text.lower()

        certificate_score = 0
        journal_score = 0

        certificate_markers = [
            "original",
            "certified that",
            "in the name of",
            "serial no",
            "design no.",
            "design no",
            "registered",
            "certificate",
        ]

        journal_markers = [
            "the patent office journal",
            "patent office journal",
            "priority",
            "date of registration",
        ]

        for marker in certificate_markers:
            if marker in lower:
                certificate_score += 1

        for marker in journal_markers:
            if marker in lower:
                journal_score += 1

        if re.search(
            r"\bin\s+the\s+name\s+of\b",
            text,
            re.IGNORECASE,
        ):
            certificate_score += 3

        if re.search(
            r"\bcertified\s+that\b",
            text,
            re.IGNORECASE,
        ):
            certificate_score += 3

        if (
            "patent office journal" in lower
            or "the patent office journal" in lower
        ):
            journal_score += 5

        if journal_score > certificate_score:
            return "JOURNAL"

        if certificate_score > 0:
            return "CERTIFICATE"

        return "UNKNOWN"

    # ========================================================
    # DESIGN NUMBER
    # ========================================================

    def _extract_design_number(
        self,
        text: str,
        qr_data: str | None,
    ) -> str | None:
        """Extract Indian design registration number."""

        if qr_data:
            qr_number = normalize_design_number(
                qr_data
            )

            if (
                qr_number
                and re.search(
                    r"\d{3,}-\d{3,}",
                    qr_number,
                )
            ):
                return qr_number

        patterns = [
            r"design\s*(?:number|no\.?)"
            r"\s*[:\-]?\s*"
            r"([0-9A-Z][0-9A-Z\-/]*)",

            r"fMtkbu\s+la[-]?\s*/?"
            r"\s*design\s+no\.?"
            r"\s*[:\-]?\s*"
            r"([0-9A-Z][0-9A-Z\-/]*)",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if not match:
                continue

            number = normalize_design_number(
                match.group(1)
            )

            if number:
                return number

        candidates = re.findall(
            r"\b\d{5,7}-\d{3}\b",
            text,
        )

        if candidates:
            return normalize_design_number(
                candidates[0]
            )

        return None

    # ========================================================
    # DESIGN RECORD ISOLATION
    # ========================================================

    def _extract_design_record(
        self,
        text: str,
        design_number: str | None,
    ) -> str:
        """Isolate one design record from journal."""

        if not design_number:
            return text

        matches = list(
            re.finditer(
                re.escape(design_number),
                text,
                re.IGNORECASE,
            )
        )

        if not matches:
            return text

        first = matches[0]

        start = first.start()

        remaining = text[
            first.end():
        ]

        next_design = re.search(
            r"\b\d{5,7}-\d{3}\b",
            remaining,
        )

        if next_design:
            end = (
                first.end()
                + next_design.start()
            )
        else:
            end = len(text)

        record = text[
            start:end
        ]

        if len(record) > 15000:
            record = record[:15000]

        return _clean_text(record)

    # ========================================================
    # DESIGN TITLE
    # ========================================================

    def _extract_design_title(
        self,
        record_text: str,
    ) -> str | None:
        """Extract design title."""

        patterns = [
            r"\btitle\s*[:\-]\s*"
            r"(.+?)"
            r"(?=\n\s*(?:priority|design\s+number|"
            r"date\s+of\s+registration|serial|class)\b|$)",

            r"\btitle\s+"
            r"(.+?)"
            r"(?=\n\s*(?:priority|design\s+number|"
            r"date\s+of\s+registration|serial|class)\b|$)",

            # Certificate wording:
            # application of such design to TITLE in the name
            r"application\s+of\s+such\s+design\s+to\s+"
            r"(.+?)"
            r"\s+in\s+the\s+name\s+of\b",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                record_text,
                re.IGNORECASE | re.DOTALL,
            )

            if not match:
                continue

            title = _clean_inline_text(
                match.group(1)
            )

            if title:
                return title

        return None

    # ========================================================
    # JOURNAL REGISTRATION DATE
    # ========================================================

    def _extract_registration_date(
        self,
        record_text: str,
    ) -> date | None:
        """Extract journal registration date."""

        patterns = [
            r"date\s+of\s+registration"
            r"\s*[:\-]?\s*"
            r"([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})",

            r"registration\s+date"
            r"\s*[:\-]?\s*"
            r"([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})",

            r"date\s+of\s+registration"
            r"\s*[:\-]?\s*"
            r"([0-9]{1,2}-[0-9]{1,2}-[0-9]{2,4})",

            r"registration\s+date"
            r"\s*[:\-]?\s*"
            r"([0-9]{1,2}-[0-9]{1,2}-[0-9]{2,4})",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                record_text,
                re.IGNORECASE,
            )

            if not match:
                continue

            normalized = normalize_date(
                match.group(1)
            )

            if normalized:
                return normalized

        return None

    # ========================================================
    # CERTIFICATE REGISTRATION DATE
    # ========================================================

    def _extract_certificate_registration_date(
        self,
        document_text: str,
    ) -> date | None:
        """Extract registration date from certificate.

        Typical certificate structure:

        Design No. : 435272-001
        Date       : 22/10/2024

        This date is the design registration date.
        """

        # ----------------------------------------------------
        # Primary deterministic pattern.
        # ----------------------------------------------------

        pattern = (
            r"design\s*(?:number|no\.?)"
            r"\s*[:\-]?\s*"
            r"[0-9A-Z][0-9A-Z\-/]*"
            r".{0,150}?"
            r"\bdate\b"
            r"\s*[:\-]\s*"
            r"([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})"
        )

        match = re.search(
            pattern,
            document_text,
            re.IGNORECASE | re.DOTALL,
        )

        if match:
            normalized = normalize_date(
                match.group(1)
            )

            if normalized:
                return normalized

        # ----------------------------------------------------
        # Hyphen date fallback.
        # ----------------------------------------------------

        pattern_hyphen = (
            r"design\s*(?:number|no\.?)"
            r"\s*[:\-]?\s*"
            r"[0-9A-Z][0-9A-Z\-/]*"
            r".{0,150}?"
            r"\bdate\b"
            r"\s*[:\-]\s*"
            r"([0-9]{1,2}-[0-9]{1,2}-[0-9]{2,4})"
        )

        match = re.search(
            pattern_hyphen,
            document_text,
            re.IGNORECASE | re.DOTALL,
        )

        if match:
            normalized = normalize_date(
                match.group(1)
            )

            if normalized:
                return normalized

        return None

    # ========================================================
    # CERTIFICATE DATE
    # ========================================================

    def _extract_certificate_date(
        self,
        document_text: str,
        registration_date: date | None,
    ) -> date | None:
        """Extract certificate issue date.

        The certificate issue date is normally the final
        date printed on the certificate.

        Registration date is explicitly excluded.
        """

        # ----------------------------------------------------
        # Explicit certificate date labels.
        # ----------------------------------------------------

        explicit_patterns = [
            r"(?:certificate\s+date|"
            r"date\s+of\s+certificate)"
            r"\s*[:\-]\s*"
            r"([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})",

            r"(?:certificate\s+date|"
            r"date\s+of\s+certificate)"
            r"\s*[:\-]\s*"
            r"([0-9]{1,2}-[0-9]{1,2}-[0-9]{2,4})",
        ]

        for pattern in explicit_patterns:
            for match in re.finditer(
                pattern,
                document_text,
                re.IGNORECASE,
            ):
                normalized = normalize_date(
                    match.group(1)
                )

                if not normalized:
                    continue

                if (
                    registration_date is None
                    or normalized != registration_date
                ):
                    return normalized

        # ----------------------------------------------------
        # Collect all dates.
        # ----------------------------------------------------

        date_matches = list(
            re.finditer(
                r"\b"
                r"(?:"
                r"[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}"
                r"|"
                r"[0-9]{1,2}-[0-9]{1,2}/[0-9]{2,4}"
                r"|"
                r"[0-9]{1,2}-[0-9]{1,2}-[0-9]{2,4}"
                r")"
                r"\b",
                document_text,
            )
        )

        # ----------------------------------------------------
        # Last date excluding registration date.
        # ----------------------------------------------------

        for match in reversed(date_matches):
            normalized = normalize_date(
                match.group(0)
            )

            if not normalized:
                continue

            if (
                registration_date is not None
                and normalized == registration_date
            ):
                continue

            return normalized

        return None

    # ========================================================
    # CONTRIBUTOR REGION
    # ========================================================

    def _extract_contributor_region(
        self,
        record_text: str,
        document_type: str,
    ) -> str:
        """Extract contributor region."""

        if document_type == "CERTIFICATE":
            match = re.search(
                r"\bin\s+the\s+name\s+of\b",
                record_text,
                re.IGNORECASE,
            )

            if match:
                return record_text[
                    match.end():
                ]

            return record_text

        # ----------------------------------------------------
        # Journal:
        #
        # Class
        # 1.Dr...
        # 2.Dr...
        # Date of Registration
        # ----------------------------------------------------

        class_match = re.search(
            r"\bclass\s*[:\-]?\s*"
            r"[0-9]{1,2}\s*-\s*[0-9]{1,2}\b",
            record_text,
            re.IGNORECASE,
        )

        start = (
            class_match.end()
            if class_match
            else 0
        )

        end = len(record_text)

        end_matches = []

        for pattern in [
            r"\bdate\s+of\s+registration\b",
            r"\bregistration\s+date\b",
        ]:
            match = re.search(
                pattern,
                record_text[start:],
                re.IGNORECASE,
            )

            if match:
                end_matches.append(
                    start + match.start()
                )

        if end_matches:
            end = min(end_matches)

        return _clean_text(
            record_text[start:end]
        )

    # ========================================================
    # CERTIFICATE PROSE STOPPER
    # ========================================================

    def _stop_at_certificate_prose(
        self,
        block: str,
    ) -> str:
        """Stop before certificate legal boilerplate."""

        if not block:
            return ""

        block = block.replace(
            "\r\n",
            "\n",
        ).replace(
            "\r",
            "\n",
        )

        block = block.replace(
            "\u00a0",
            " ",
        )

        block = re.sub(
            r"[ \t]+",
            " ",
            block,
        )

        english_patterns = [
            r"\bCertified\s+that\b",
            r"\bCertified\b",
            r"\bthe\s+design\s+of\s+which\b",
            r"\bIn\s+pursuance\s+of\b",
            r"\bDesigns\s+Act\b",
            r"\bDesigns\s+Rules\b",
            r"\bDate\s+of\s+Registration\b",
            r"\bregistration\s+as\s+of\b",
        ]

        hindi_patterns = [
            r"\bfMtkbu\s+vf/kfu;e\b",
            r"\bfMtkbu\s+fu;e\b",
            r"\bvf/kfu;e\]\s*2000\b",
            r"\bfu;e\]\s*2001\b",
            r"\bds\s+v/;/khu\b",
            r"\bçko/kkuksa\s+ds\s+vuqlj.k\s+esaA\b",
        ]

        positions: list[int] = []

        for pattern in (
            english_patterns
            + hindi_patterns
        ):
            match = re.search(
                pattern,
                block,
                re.IGNORECASE,
            )

            if match:
                positions.append(
                    match.start()
                )

        if positions:
            block = block[
                :min(positions)
            ]

        block = re.sub(
            r"\s*,?\s*et\s+al\.?\s*$",
            "",
            block,
            flags=re.IGNORECASE,
        )

        block = re.sub(
            r"\s+",
            " ",
            block,
        )

        block = block.strip(
            " \t\r\n:;,-"
        )

        block = re.sub(
            r"\.(?=\s*$)",
            "",
            block,
        ).strip()

        return block

    # ========================================================
    # CONTRIBUTOR BLOCK
    # ========================================================

    def _clean_contributor_block(
        self,
        block: str,
    ) -> str:
        """Clean contributor block."""

        if not block:
            return ""

        block = self._stop_at_certificate_prose(
            block
        )

        block = _clean_inline_text(
            block
        )

        block = re.sub(
            r"\.(?=\s*$)",
            "",
            block,
        ).strip()

        return block

    # ========================================================
    # CONTRIBUTOR PARSER
    # ========================================================

    def _parse_contributor_block(
        self,
        block: str,
        number: int,
    ) -> dict[str, Any] | None:
        """Parse one contributor."""

        if not block:
            return None

        block = self._clean_contributor_block(
            block
        )

        if not block:
            return None

        block = re.sub(
            rf"^\s*{number}\s*\.\s*",
            "",
            block,
        ).strip()

        if not block:
            return None

        # ----------------------------------------------------
        # Designation boundary.
        #
        # IMPORTANT:
        # "Associate" / "Assistant" must NOT become part
        # of the contributor name.
        # ----------------------------------------------------

        designation_boundary = re.search(
            r"\s+"
            r"(?:"
            r"Associate\s+Professor"
            r"|Assistant\s+Professor"
            r"|Professor\s*&\s*Head"
            r"|Professor"
            r"|Senior\s+Lecturer"
            r"|Lecturer"
            r"|Head"
            r")"
            r"(?:\s|,|$)",
            block,
            re.IGNORECASE,
        )

        if not designation_boundary:
            # Fallback: try matching Associate/Assistant as standalone words
            designation_boundary = re.search(
                r"\s+"
                r"(?:"
                r"\bAssociate\b"
                r"|\bAssistant\b"
                r")"
                r"(?:\s|,|$)",
                block,
                re.IGNORECASE,
            )

        if designation_boundary:
            name_part = block[
                :designation_boundary.start()
            ].strip()

            remainder = block[
                designation_boundary.end():
            ].strip()

            designation_raw = (
                designation_boundary.group(0).strip()
            )

            designation_raw = re.sub(
                r"^[,\s]+",
                "",
                designation_raw,
            )

            if re.search(
                r"Professor\s*&\s*Head",
                designation_raw,
                re.IGNORECASE,
            ):
                designation_raw = (
                    "Professor & Head"
                )

            elif re.search(
                r"Associate\s+Professor",
                designation_raw,
                re.IGNORECASE,
            ):
                designation_raw = (
                    "Associate Professor"
                )

            elif re.search(
                r"Assistant\s+Professor",
                designation_raw,
                re.IGNORECASE,
            ):
                designation_raw = (
                    "Assistant Professor"
                )

            elif re.search(
                r"\bProfessor\b",
                designation_raw,
                re.IGNORECASE,
            ):
                designation_raw = "Professor"

            elif re.search(
                r"\bAssociate\b",
                designation_raw,
                re.IGNORECASE,
            ):
                designation_raw = (
                    "Associate Professor"
                )

            elif re.search(
                r"\bAssistant\b",
                designation_raw,
                re.IGNORECASE,
            ):
                designation_raw = (
                    "Assistant Professor"
                )

        else:
            # No designation found - try to extract name by finding department/institution boundary
            name_part = block
            remainder = ""
            designation_raw = ""

            # Search for department pattern to split name from department
            dept_match = re.search(
                r"\s+(?:Department\s+of|Dept\.?\s+of)\s+",
                block,
                re.IGNORECASE,
            )
            if dept_match:
                name_part = block[:dept_match.start()].strip()
                remainder = block[dept_match.start():].strip()
            else:
                # Try institution pattern
                inst_match = re.search(
                    r"\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*[A-Za-z]",
                    block
                )
                if inst_match:
                    # This is a heuristic - look for ", City" pattern
                    pass

        if not name_part:
            return None

        # If no designation found, still try to extract department/institution from full block
        search_text = remainder if remainder else block

        name = normalize_contributor_name(
            name_part
        )

        if name == "UNKNOWN":
            return None

        contributor: dict[str, Any] = {
            "number": number,
            "name": name,
        }

        # ----------------------------------------------------
        # Designation
        # ----------------------------------------------------

        if designation_raw:
            designation = normalize_designation(
                designation_raw
            )

            if designation:
                contributor[
                    "designation"
                ] = designation

        # ----------------------------------------------------
        # Department
        #
        # IMPORTANT FIX:
        #
        # Department of Information Science and Engineering
        # -> Information Science and Engineering
        #
        # Department of CSE, FET, MRIIRS
        # -> CSE
        # -> Computer Science and Engineering
        # ----------------------------------------------------

        department_match = re.search(
            r"(?:Department\s+of|Dept\.?\s+of)\s+"
            r"(?P<department>[^,\n]+)",
            search_text,
            re.IGNORECASE,
        )

        department = None

        if department_match:
            department = _clean_inline_text(
                department_match.group(
                    "department"
                )
            )

        if department:
            contributor[
                "department"
            ] = normalize_department(
                department
            )

        # ----------------------------------------------------
        # Institution + location + state + PIN
        # ----------------------------------------------------

        institution_match = re.search(
            r"(?:Department\s+of|Dept\.?\s+of)"
            r"\s+.+?,\s*"
            r"(?P<institution>.+?)"
            r",\s*"
            r"(?P<location>[A-Za-z .'-]+)"
            r",\s*"
            r"(?P<state>"
            r"Karnataka|Tamil Nadu|Haryana|Kerala|"
            r"Maharashtra|Delhi|Andhra Pradesh|"
            r"Telangana|Rajasthan|Gujarat|"
            r"West Bengal|Uttar Pradesh|"
            r"Madhya Pradesh"
            r")"
            r"(?:,\s*(?:Pin|PIN)\s*:?\s*"
            r"(?P<pin>\d{6}))?",
            search_text,
            re.IGNORECASE,
        )

        if institution_match:
            institution = _clean_inline_text(
                institution_match.group(
                    "institution"
                )
            )

            if institution:
                contributor[
                    "institution"
                ] = institution

            location = _clean_inline_text(
                institution_match.group(
                    "location"
                )
            )

            if location:
                contributor[
                    "location"
                ] = location

            state = _clean_inline_text(
                institution_match.group(
                    "state"
                )
            )

            if state:
                contributor[
                    "state"
                ] = state

            pin = institution_match.group(
                "pin"
            )

            if pin:
                contributor[
                    "pin_code"
                ] = pin

        # ----------------------------------------------------
        # PIN fallback
        # ----------------------------------------------------

        if "pin_code" not in contributor:
            pin_match = re.search(
                r"\b(?:Pin|PIN)\s*:\s*"
                r"(\d{6})\b",
                search_text,
                re.IGNORECASE,
            )

            if pin_match:
                contributor[
                    "pin_code"
                ] = pin_match.group(1)

        # ----------------------------------------------------
        # State fallback
        # ----------------------------------------------------

        if "state" not in contributor:
            state_match = re.search(
                r"\b("
                r"Karnataka|Tamil Nadu|Haryana|Kerala|"
                r"Maharashtra|Delhi|Andhra Pradesh|"
                r"Telangana|Rajasthan|Gujarat|"
                r"West Bengal|Uttar Pradesh|"
                r"Madhya Pradesh"
                r")\b",
                search_text,
                re.IGNORECASE,
            )

            if state_match:
                contributor[
                    "state"
                ] = state_match.group(1)

        return contributor

    # ========================================================
    # DESIGN CONTRIBUTORS
    # ========================================================

    def _extract_design_contributors(
        self,
        record_text: str,
        document_text: str | None = None,
        document_type: str = "UNKNOWN",
    ) -> list[dict[str, Any]]:
        """Extract numbered contributors."""

        region = self._extract_contributor_region(
            record_text,
            document_type,
        )

        if not region:
            return []

        matches = list(
            re.finditer(
                r"(?<![\d-])"
                r"(?P<number>"
                r"10|[1-9]"
                r")"
                r"\s*\.\s*"
                r"(?="
                r"(?:Dr\.?|Prof\.?|Mr\.?|Mrs\.?|Ms\.?)"
                r"\s+"
                r")",
                region,
                re.IGNORECASE,
            )
        )

        if not matches:
            return []

        contributors: list[
            dict[str, Any]
        ] = []

        for index, match in enumerate(matches):
            number = int(
                match.group("number")
            )

            start = match.end()

            if index + 1 < len(matches):
                end = matches[
                    index + 1
                ].start()
            else:
                end = len(region)

            block = region[
                start:end
            ]

            block = self._stop_at_certificate_prose(
                block
            )

            contributor = (
                self._parse_contributor_block(
                    block,
                    number,
                )
            )

            if contributor:
                contributors.append(
                    contributor
                )

        # ----------------------------------------------------
        # Deduplicate contributors by name.
        # ----------------------------------------------------

        unique: list[
            dict[str, Any]
        ] = []

        seen: set[str] = set()

        for contributor in contributors:
            key = contributor[
                "name"
            ].strip().lower()

            if key in seen:
                continue

            seen.add(key)
            unique.append(
                contributor
            )

        return unique

    # ========================================================
    # CERTIFICATE APPLICANTS
    # ========================================================

    def _extract_certificate_applicants(
        self,
        text: str,
    ) -> list[str]:
        """Extract all certificate applicant names."""

        match = re.search(
            r"\bin\s+the\s+name\s+of\b"
            r"(?P<names>.+?)"
            r"(?="
            r"\bfMtkbu\s+vf/kfu;e\b"
            r"|"
            r"\bCertified\b"
            r"|"
            r"\bIn\s+pursuance\b"
            r"|"
            r"\n\s*\n"
            r"|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )

        if not match:
            return []

        region = match.group(
            "names"
        )

        region = self._stop_at_certificate_prose(
            region
        )

        matches = list(
            re.finditer(
                r"(?<![\d-])"
                r"(?P<number>"
                r"10|[1-9]"
                r")"
                r"\s*\.\s*",
                region,
            )
        )

        names: list[str] = []

        if matches:
            for index, item in enumerate(matches):
                start = item.end()

                if index + 1 < len(matches):
                    end = matches[
                        index + 1
                    ].start()
                else:
                    end = len(region)

                raw_name = region[
                    start:end
                ]

                raw_name = (
                    self._stop_at_certificate_prose(
                        raw_name
                    )
                )

                raw_name = _clean_inline_text(
                    raw_name
                )

                # Remove designation/legal continuation.
                raw_name = re.split(
                    r"\b(?:Professor|"
                    r"Associate Professor|"
                    r"Assistant Professor|"
                    r"Department)\b",
                    raw_name,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0]

                name = normalize_contributor_name(
                    raw_name
                )

                if name != "UNKNOWN":
                    names.append(name)

            return names

        # ----------------------------------------------------
        # Fallback
        # ----------------------------------------------------

        chunks = re.split(
            r"(?=(?:Dr\.?|Prof\.?)\s+)",
            region,
            flags=re.IGNORECASE,
        )

        for chunk in chunks:
            name = normalize_contributor_name(
                chunk
            )

            if (
                name != "UNKNOWN"
                and len(name) < 150
            ):
                names.append(name)

        return names

    # ========================================================
    # GENERIC EXTRACTION
    # ========================================================

    def _extract_generic_fields(
        self,
        text: str,
    ):
        """Extract generic identifier candidates."""

        identifiers = re.findall(
            r"\b[A-Z0-9]{4,}"
            r"(?:[-/][A-Z0-9]{2,})*\b",
            text,
        )

        if not identifiers:
            return

        unique = list(
            dict.fromkeys(
                identifiers
            )
        )

        self.evidence_tracker.add(
            "identifier_candidates",
            unique[:10],
            "ocr_text",
            0.3,
        )

    # ========================================================
    # CONFIDENCE
    # ========================================================

    def _calculate_confidence(
        self,
    ) -> float:
        """Calculate weighted extraction confidence."""

        evidence = (
            self.evidence_tracker.evidence
        )

        if not evidence:
            return 0.1

        total_weight = 0.0
        weighted_sum = 0.0

        for entries in evidence.values():
            for entry in entries:
                confidence = float(
                    entry.get(
                        "confidence",
                        0.0,
                    )
                )

                source = str(
                    entry.get(
                        "source",
                        "",
                    )
                ).lower()

                if "qr" in source:
                    weight = 3.0
                elif "ocr" in source:
                    weight = 2.0
                else:
                    weight = 1.0

                total_weight += weight
                weighted_sum += (
                    confidence * weight
                )

        if total_weight == 0:
            return 0.1

        return round(
            min(
                weighted_sum / total_weight,
                1.0,
            ),
            2,
        )

    # ========================================================
    # REVIEW DECISION
    # ========================================================

    def _check_review_required(
        self,
        ip_type: str,
        confidence: float,
    ) -> bool:
        """Determine whether human review is required."""

        if confidence < 0.5:
            return True

        if (
            ip_type == "PATENT"
            and confidence < 0.7
        ):
            return True

        if (
            ip_type == "DESIGN_REGISTRATION"
            and confidence < 0.6
        ):
            return True

        evidence = (
            self.evidence_tracker.evidence
        )

        has_core_id = (
            "patent_number" in evidence
            or "design_number" in evidence
        )

        if (
            has_core_id
            and confidence >= 0.5
        ):
            return False

        return True


# ============================================================
# DEFAULT SERVICE INSTANCE
# ============================================================

extraction_service = (
    StructuredExtractionService()
)
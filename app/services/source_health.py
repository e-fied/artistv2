"""Source-health classification and recovery transitions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.models.artist import ArtistSource
from app.models.scan import ScanSourceResult


@dataclass(frozen=True)
class SourceHealthAssessment:
    """One classified source outcome."""

    status: str  # healthy | empty | warning | error
    code: str
    message: Optional[str] = None
    transient: bool = False

    @property
    def is_problem(self) -> bool:
        return self.status in {"warning", "error"}


@dataclass(frozen=True)
class SourceHealthTransition:
    """State change produced by applying one assessment."""

    recovered: bool
    previous_failures: int


def assess_event_content(
    markdown: str,
    extracted_count: int,
    *,
    extraction_failed: bool = False,
    extraction_mode: Optional[str] = None,
) -> SourceHealthAssessment:
    """Classify fetched event content into an actionable health state."""
    if extracted_count > 0:
        code = "structured_events" if extraction_mode == "structured" else "events_extracted"
        return SourceHealthAssessment(status="healthy", code=code)

    text = (markdown or "").strip()
    lower_text = text.casefold()
    if any(
        phrase in lower_text
        for phrase in (
            "no upcoming events",
            "no upcoming dates",
            "no tour dates",
            "no shows",
            "nothing scheduled",
            "check back soon",
        )
    ):
        return SourceHealthAssessment(
            status="empty",
            code="no_upcoming_events",
            message="The source was reached successfully and currently reports no upcoming dates.",
        )

    if extraction_failed:
        return SourceHealthAssessment(
            status="error",
            code="extraction_failed",
            message="The page was fetched, but event extraction failed.",
        )

    if any(
        phrase in lower_text
        for phrase in (
            "access denied",
            "captcha",
            "cf-chl",
            "cloudflare",
            "enable cookies",
            "forbidden",
            "unusual traffic",
            "verify you are human",
        )
    ):
        return SourceHealthAssessment(
            status="warning",
            code="bot_protection",
            message="The fetched content looks like bot protection or an access-denied page.",
            transient=True,
        )

    date_hits = re.findall(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
        lower_text,
    )
    event_word_hits = sum(
        1 for word in ("tour", "tickets", "venue", "show", "event", "dates")
        if word in lower_text
    )
    if len(text) < 500:
        return SourceHealthAssessment(
            status="warning",
            code="very_little_content",
            message="Crawler returned very little page text. The page may be blank, blocked, or rendering dates after load.",
            transient=True,
        )
    if event_word_hits >= 2 and not date_hits:
        return SourceHealthAssessment(
            status="warning",
            code="dynamic_listing_missing",
            message="Tour-related text was found but no date-like content appeared. A JavaScript widget or unsupported event feed may be missing.",
            transient=True,
        )
    if not date_hits:
        return SourceHealthAssessment(
            status="warning",
            code="no_date_content",
            message="Readable content was fetched, but no date-like text was found.",
            transient=True,
        )
    return SourceHealthAssessment(
        status="warning",
        code="zero_events_extracted",
        message="Date-like content was found, but no events could be extracted for this artist.",
        transient=True,
    )


def fetch_error_assessment(message: str) -> SourceHealthAssessment:
    return SourceHealthAssessment(
        status="error",
        code="fetch_failed",
        message=(message or "Source fetch failed")[:500],
    )


def ticketmaster_assessment(event_count: int) -> SourceHealthAssessment:
    if event_count > 0:
        return SourceHealthAssessment(status="healthy", code="ticketmaster_events")
    return SourceHealthAssessment(
        status="empty",
        code="ticketmaster_no_upcoming",
        message="Ticketmaster was reached successfully and returned no upcoming candidates.",
    )


def cached_assessment() -> SourceHealthAssessment:
    return SourceHealthAssessment(status="healthy", code="unchanged_cache")


def apply_source_health(
    source: ArtistSource,
    result: ScanSourceResult,
    assessment: SourceHealthAssessment,
    *,
    checked_at: Optional[datetime] = None,
) -> SourceHealthTransition:
    """Apply a classified outcome consistently to source and scan-result rows."""
    checked_at = checked_at or datetime.utcnow()
    previous_failures = source.consecutive_failures or 0
    recovered = previous_failures > 0 and not assessment.is_problem

    result.health_status = "recovered" if recovered else assessment.status
    result.health_code = assessment.code
    result.fetch_error = assessment.message if assessment.is_problem else None

    source.last_checked_at = checked_at
    source.health_status = assessment.status
    source.last_health_code = assessment.code
    if assessment.is_problem:
        source.consecutive_failures = previous_failures + 1
        source.last_error = assessment.message
    else:
        source.consecutive_failures = 0
        source.last_error = None
        source.last_success_at = checked_at
        if recovered:
            source.last_recovered_at = checked_at

    return SourceHealthTransition(
        recovered=recovered,
        previous_failures=previous_failures,
    )

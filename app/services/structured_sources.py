"""Canonical event seam for structured page and widget adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from app.schemas.gemini import ConfidenceLevel, ExtractedEvent, ExtractionResult


STRUCTURED_EVENT_PREFIX = "TOURTRACKER_EVENT_JSON "


@dataclass(frozen=True)
class StructuredExtraction:
    """Structured events plus the adapters that supplied them."""

    result: ExtractionResult
    providers: tuple[str, ...]


def event_marker(provider: str, event: dict) -> str:
    """Serialize one adapter event into the crawler's lossless internal format."""
    payload = {"provider": provider, **event}
    return STRUCTURED_EVENT_PREFIX + json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def extract_structured_events(
    markdown: str,
    artist_name: str,
) -> Optional[StructuredExtraction]:
    """Return canonical adapter events without calling an LLM."""
    events: list[ExtractedEvent] = []
    providers: set[str] = set()
    seen: set[tuple[str, str, str, str, str]] = set()

    for raw_line in (markdown or "").splitlines():
        line = raw_line.strip()
        if not line.startswith(STRUCTURED_EVENT_PREFIX):
            continue
        try:
            payload = json.loads(line[len(STRUCTURED_EVENT_PREFIX):])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue

        provider = str(payload.get("provider") or "structured").strip()
        event_date = str(payload.get("date") or "TBD").strip()
        venue = str(payload.get("venue") or "").strip()
        city = str(payload.get("city") or "").strip()
        if not venue or not city:
            continue

        source_event_id = str(payload.get("source_event_id") or "").strip() or None
        ticket_url = str(payload.get("ticket_url") or "").strip() or None
        key = (
            provider,
            source_event_id or ticket_url or "",
            event_date,
            venue.casefold(),
            city.casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        providers.add(provider)

        evidence = str(payload.get("evidence_text") or "").strip()
        if not evidence:
            evidence = f"{provider}: {event_date} | {venue} | {city}"[:240]
        events.append(
            ExtractedEvent(
                artist_name=artist_name,
                event_name=str(payload.get("event_name") or artist_name).strip(),
                date=event_date,
                time=str(payload.get("time") or "").strip() or None,
                venue=venue,
                city=city,
                region=str(payload.get("region") or "").strip() or None,
                country=str(payload.get("country") or "").strip() or None,
                ticket_url=ticket_url,
                evidence_text=evidence[:500],
                confidence=ConfidenceLevel.HIGH,
                source_provider=provider,
                source_event_id=source_event_id,
            )
        )

    if not events:
        return None
    return StructuredExtraction(
        result=ExtractionResult(
            events=events,
            page_notes="Parsed directly from structured event adapters; Gemini bypassed.",
        ),
        providers=tuple(sorted(providers)),
    )

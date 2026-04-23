"""LLM event extraction service using Gemini."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from google import genai
from google.genai import types

from app.config import AppSettings
from app.schemas.gemini import ConfidenceLevel, ExtractedEvent, ExtractionResult

logger = logging.getLogger(__name__)


class ExtractorService:
    """Service for extracting structured event data from text using Gemini."""

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.client = None
        if settings.gemini_api_key:
            try:
                self.client = genai.Client(api_key=settings.gemini_api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Gemini: {e}")
        self.last_debug: dict = {}

    def extract_events(self, markdown: str, artist_name: str) -> Optional[ExtractionResult]:
        """Parse markdown to extract upcoming events for the given artist."""
        if not self.client:
            logger.error("Gemini API key not configured")
            fallback = self._fallback_extract_events(markdown, artist_name)
            if fallback:
                self.last_debug = {
                    "model": None,
                    "temperature": None,
                    "response_mime_type": "application/json",
                    "input_markdown_chars": len(markdown),
                    "fallback_used": "structured_markdown_parser",
                    "parsed_response": fallback.model_dump(),
                }
            return fallback

        model = "gemini-2.5-flash"
        prompt = f"""
You are an expert event data extractor.
Review the following text from an artist's tour website and extract all UPCOMING events.

Target Artist: {artist_name}

Rules:
1. Only extract events that have not already passed (if a year is missing, assume the next upcoming instance of that date).
2. If the date is 'TBD' or just an announcement, leave date as TBD and confidence as LOW.
3. Be precise with the venue and city.
4. If it's a festival, put the festival name in the event_name field, otherwise use the tour name or artist name.
5. Provide a short, verbatim evidence_text excerpt from the text that proves the event exists.
6. Assess confidence: HIGH if date/city/venue are clear, MEDIUM if missing details, LOW if just rumors/TBD.

Website Content:
----------------
{markdown}
"""
        self.last_debug = {
            "model": model,
            "temperature": 0.1,
            "response_mime_type": "application/json",
            "prompt": prompt,
            "input_markdown_chars": len(markdown),
        }
        try:
            response = self.client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ExtractionResult,
                    temperature=0.1,
                ),
            )
            self.last_debug["raw_response_text"] = getattr(response, "text", None)
            
            # The structured output is available in response.parsed
            if hasattr(response, 'parsed') and response.parsed:
                self.last_debug["parsed_response"] = response.parsed.model_dump()
                if response.parsed.events:
                    return response.parsed

                fallback = self._fallback_extract_events(markdown, artist_name)
                if fallback:
                    self.last_debug["fallback_used"] = "structured_markdown_parser"
                    self.last_debug["parsed_response"] = fallback.model_dump()
                    logger.info(
                        "Gemini returned zero events; using structured markdown fallback for %s",
                        artist_name,
                    )
                    return fallback
                return response.parsed
            else:
                self.last_debug["parsed_response"] = None
                fallback = self._fallback_extract_events(markdown, artist_name)
                if fallback:
                    self.last_debug["fallback_used"] = "structured_markdown_parser"
                    self.last_debug["parsed_response"] = fallback.model_dump()
                    logger.info(
                        "Gemini returned no parsed output; using structured markdown fallback for %s",
                        artist_name,
                    )
                    return fallback
                logger.error("Gemini returned success but no parsed structured output.")
                return None
                
        except Exception as e:
            self.last_debug["error"] = str(e)
            fallback = self._fallback_extract_events(markdown, artist_name)
            if fallback:
                self.last_debug["fallback_used"] = "structured_markdown_parser"
                self.last_debug["parsed_response"] = fallback.model_dump()
                logger.info(
                    "Gemini extraction failed; using structured markdown fallback for %s",
                    artist_name,
                )
                return fallback
            logger.error(f"Gemini extraction failed: {e}")
            return None

    def _fallback_extract_events(self, markdown: str, artist_name: str) -> Optional[ExtractionResult]:
        """Extract obvious structured events without the LLM as a safety net."""
        events: list[ExtractedEvent] = []
        events.extend(self._extract_markdown_table_events(markdown, artist_name))
        events.extend(self._extract_punchup_api_events(markdown, artist_name))

        deduped: list[ExtractedEvent] = []
        seen: set[tuple[str, str | None, str, str, str]] = set()
        for event in events:
            key = (event.date, event.time, event.venue.lower(), event.city.lower(), event.ticket_url or "")
            if key in seen:
                continue
            seen.add(key)
            deduped.append(event)

        if not deduped:
            return None

        return ExtractionResult(events=deduped, page_notes="Recovered via structured markdown fallback.")

    def _extract_markdown_table_events(self, markdown: str, artist_name: str) -> list[ExtractedEvent]:
        events: list[ExtractedEvent] = []

        for raw_line in markdown.splitlines():
            line = raw_line.strip()
            if not line.startswith("|"):
                continue

            raw_cells = [cell.strip() for cell in line.strip("|").split("|")]
            cells = [self._strip_markdown_links(cell) for cell in raw_cells]
            if len(cells) < 4:
                continue
            if cells[0].startswith("---"):
                continue

            event_date = self._parse_human_date(cells[0])
            if not event_date:
                continue

            location_text, location_time = self._extract_trailing_time(cells[1])
            venue_text, venue_time = self._extract_trailing_time(cells[2])
            city, region = self._split_city_region(location_text)
            ticket_url = self._extract_url(raw_cells[3]) or self._extract_url(raw_line)

            if not city or not venue_text:
                continue

            evidence_text = " | ".join(part for part in [cells[0], cells[1], cells[2]] if part)[:240]
            events.append(
                ExtractedEvent(
                    artist_name=artist_name,
                    event_name=artist_name,
                    date=event_date,
                    time=location_time or venue_time,
                    venue=venue_text,
                    city=city,
                    region=region,
                    country=None,
                    ticket_url=ticket_url,
                    evidence_text=evidence_text,
                    confidence=ConfidenceLevel.HIGH,
                )
            )

        return events

    def _extract_punchup_api_events(self, markdown: str, artist_name: str) -> list[ExtractedEvent]:
        events: list[ExtractedEvent] = []

        for raw_line in markdown.splitlines():
            line = raw_line.strip()
            if not line.startswith("- 20"):
                continue
            if " | Tickets: " not in line:
                continue

            body = line[2:]
            event_page = None
            if " | Event page: " in body:
                body, event_page = body.split(" | Event page: ", 1)
                event_page = event_page.strip()

            body, ticket_url = body.split(" | Tickets: ", 1)
            segments = [segment.strip() for segment in body.split(" | ") if segment.strip()]
            if len(segments) < 4:
                continue

            starts_at = segments[0]
            try:
                dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
            except ValueError:
                continue

            venue_index, location_index = self._find_location_window(segments[1:])
            if venue_index is None or location_index is None:
                continue

            offset_segments = segments[1:]
            title = " | ".join(offset_segments[:venue_index]).strip() or artist_name
            venue = offset_segments[venue_index].strip()
            location = offset_segments[location_index].strip()
            city, region = self._split_city_region(location)

            if not city or not venue:
                continue

            evidence_text = line[2:240]
            events.append(
                ExtractedEvent(
                    artist_name=artist_name,
                    event_name=title,
                    date=dt.date().isoformat(),
                    time=dt.strftime("%H:%M"),
                    venue=venue,
                    city=city,
                    region=region,
                    country=None,
                    ticket_url=ticket_url.strip() or event_page,
                    evidence_text=evidence_text,
                    confidence=ConfidenceLevel.HIGH,
                )
            )

        return events

    def _find_location_window(self, segments: list[str]) -> tuple[Optional[int], Optional[int]]:
        for idx in range(len(segments) - 1, 0, -1):
            if self._looks_like_location(segments[idx]):
                return idx - 1, idx
        if len(segments) >= 3:
            return 1, 2
        return None, None

    def _looks_like_location(self, value: str) -> bool:
        return bool(re.search(r",\s*[A-Z][A-Za-z]{1,3}\.?\s*$", value))

    def _strip_markdown_links(self, value: str) -> str:
        return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value).strip()

    def _extract_url(self, value: str) -> Optional[str]:
        match = re.search(r"\((https?://[^)]+)\)", value)
        return match.group(1) if match else None

    def _extract_trailing_time(self, value: str) -> tuple[str, Optional[str]]:
        match = re.search(r"\((\d{1,2}:\d{2}\s*[AaPp][Mm])\)\s*$", value)
        if not match:
            return value.strip(), None

        cleaned = value[:match.start()].strip()
        time_text = match.group(1).replace(" ", "").upper()
        parsed_time = datetime.strptime(time_text, "%I:%M%p").strftime("%H:%M")
        return cleaned, parsed_time

    def _split_city_region(self, value: str) -> tuple[str, Optional[str]]:
        if "," not in value:
            return value.strip(), None
        city, region = value.rsplit(",", 1)
        return city.strip(), region.strip() or None

    def _parse_human_date(self, value: str) -> Optional[str]:
        cleaned = self._strip_markdown_links(value).replace("  ", " ").strip()
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(cleaned, fmt).date().isoformat()
            except ValueError:
                continue
        return None

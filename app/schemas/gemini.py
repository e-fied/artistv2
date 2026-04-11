"""Pydantic schemas for Gemini structured output."""

from __future__ import annotations

from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, Field


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExtractedEvent(BaseModel):
    """A single event extracted from website content by Gemini."""

    artist_name: str = Field(description="The artist or comedian name as shown on the page")
    event_name: str = Field(description="Full event or show name")
    date: str = Field(description="Event date in YYYY-MM-DD format, or 'TBD' if unclear")
    time: Optional[str] = Field(
        default=None, description="Event time in HH:MM 24h format if available"
    )
    venue: str = Field(description="Venue name")
    city: str = Field(description="City name")
    region: Optional[str] = Field(
        default=None, description="Province, state, or region"
    )
    country: Optional[str] = Field(
        default=None, description="Country name or code"
    )
    ticket_url: Optional[str] = Field(
        default=None, description="Direct ticket purchase URL if found"
    )
    evidence_text: str = Field(
        description="Exact text snippet from the page showing this event"
    )
    confidence: ConfidenceLevel = Field(
        description="How confident this is a real confirmed event with a specific date"
    )


class ExtractionResult(BaseModel):
    """Complete result from Gemini extraction of a page."""

    events: List[ExtractedEvent] = Field(default_factory=list)
    page_notes: Optional[str] = Field(
        default=None,
        description="General tour announcements like 'coming soon' without specific dates",
    )

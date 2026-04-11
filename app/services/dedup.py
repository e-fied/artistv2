"""Event deduplication service.

Generates a dedup key for each event and handles upsert logic.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, time, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.event import Event

logger = logging.getLogger(__name__)


def make_dedup_key(
    artist_id: int,
    event_name: str,
    venue: str,
    city: str,
    event_date: Optional[date],
) -> str:
    """Generate a deterministic dedup key for an event.
    
    Format: sha256(artist_id|normalized_name|normalized_venue|normalized_city|date)
    """
    parts = [
        str(artist_id),
        event_name.strip().lower(),
        venue.strip().lower(),
        city.strip().lower(),
        event_date.isoformat() if event_date else "nodate",
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def upsert_event(
    db: Session,
    artist_id: int,
    event_name: str,
    venue: str,
    city: str,
    region: Optional[str],
    country: Optional[str],
    event_date: Optional[date],
    event_time: Optional[time],
    ticket_url: Optional[str],
    source_url: Optional[str],
    source_type: str,
    ticketmaster_event_id: Optional[str],
    status: str,
    confidence_score: float,
    match_reason: Optional[str],
    evidence_text: Optional[str],
    matched_location_profile_id: Optional[int],
) -> tuple:  # (Event, bool_is_new)
    """Insert a new event or update an existing one.
    
    Returns (event, is_new) tuple.
    
    Rules:
    - If dedup key exists: update fields but never downgrade status
    - If new: insert with given status
    """
    dedup_key = make_dedup_key(artist_id, event_name, venue, city, event_date)

    existing = db.query(Event).filter(Event.dedup_key == dedup_key).first()

    if existing:
        # Update mutable fields
        if ticket_url and not existing.ticket_url:
            existing.ticket_url = ticket_url
        if evidence_text and not existing.evidence_text:
            existing.evidence_text = evidence_text
        if ticketmaster_event_id and not existing.ticketmaster_event_id:
            existing.ticketmaster_event_id = ticketmaster_event_id

        # Never downgrade status: confirmed → stays confirmed
        status_priority = {"rejected": 0, "expired": 1, "possible": 2, "confirmed": 3}
        if status_priority.get(status, 0) > status_priority.get(existing.status, 0):
            existing.status = status
            existing.confidence_score = confidence_score

        existing.updated_at = datetime.utcnow()
        db.flush()
        return (existing, False)

    # New event
    event = Event(
        artist_id=artist_id,
        event_name=event_name,
        venue=venue,
        city=city,
        region=region,
        country=country,
        event_date=event_date,
        event_time=event_time,
        ticket_url=ticket_url,
        source_url=source_url,
        source_type=source_type,
        ticketmaster_event_id=ticketmaster_event_id,
        status=status,
        confidence_score=confidence_score,
        match_reason=match_reason,
        evidence_text=evidence_text,
        matched_location_profile_id=matched_location_profile_id,
        dedup_key=dedup_key,
    )
    db.add(event)
    db.flush()
    return (event, True)

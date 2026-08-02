"""Event identity, persistence, lifecycle, and notification-state policy."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.artist import Artist
from app.models.event import Event
from app.services.location_matcher import match_event_to_locations


@dataclass(frozen=True)
class EventProcessingResult:
    """Observable result of processing one discovered performance."""

    outcome: str
    event: Optional[Event] = None
    is_new: bool = False
    should_notify: bool = False


@dataclass(frozen=True)
class EventHistoryNormalization:
    """Counts from idempotent event-history maintenance."""

    expired: int = 0
    duplicates_removed: int = 0


def process_discovered_event(
    db: Session,
    artist: Artist,
    event_data: dict,
    profiles: list,
    source_type: str,
    *,
    as_of: Optional[date] = None,
) -> EventProcessingResult:
    """Match and record one discovery, returning its user-visible outcome."""
    as_of = as_of or date.today()
    event_date = _parse_date(event_data.get("date"))
    event_time = _parse_time(event_data.get("time"))

    if event_date and event_date < as_of:
        return EventProcessingResult(outcome="past")

    city = str(event_data.get("city") or "").strip()
    venue = str(event_data.get("venue") or "").strip()
    match = match_event_to_locations(
        event_city=city,
        event_region=event_data.get("region") or "",
        event_country=event_data.get("country") or "",
        event_lat=event_data.get("venue_lat"),
        event_lon=event_data.get("venue_lon"),
        event_venue=venue,
        profiles=profiles,
    )
    if not match or not match.matched:
        return EventProcessingResult(outcome="no_match")

    confirmed = source_type == "ticketmaster" and match.confidence >= 0.8
    confirmed = confirmed or match.confidence >= 0.9
    status = "confirmed" if confirmed else "possible"

    event, is_new = _upsert_event(
        db=db,
        artist_id=artist.id,
        event_name=str(event_data.get("event_name") or "").strip(),
        venue=venue,
        city=city,
        region=event_data.get("region") or None,
        country=event_data.get("country") or None,
        event_date=event_date,
        event_time=event_time,
        ticket_url=event_data.get("ticket_url") or None,
        source_url=event_data.get("source_url") or None,
        source_type=source_type,
        ticketmaster_event_id=event_data.get("ticketmaster_event_id") or None,
        source_provider=event_data.get("source_provider") or None,
        source_event_id=event_data.get("source_event_id") or None,
        status=status,
        confidence_score=match.confidence,
        match_reason=match.reason,
        evidence_text=event_data.get("evidence_text") or None,
        matched_location_profile_id=match.profile.id if match.profile else None,
    )

    should_notify = bool(
        event.status == "confirmed"
        and event.notification_status == "pending"
        and not event.is_attending
    )
    if is_new and event.status == "confirmed":
        outcome = "confirmed"
    elif is_new and event.status == "possible":
        outcome = "possible"
    else:
        outcome = "existing"

    return EventProcessingResult(
        outcome=outcome,
        event=event,
        is_new=is_new,
        should_notify=should_notify,
    )


def apply_event_action(db: Session, event_id: int, action: str) -> int:
    """Apply one user action to every row representing the same performance."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return 0

    matches = _same_performance_rows(db, event)
    for matching in matches:
        if action == "going":
            matching.is_attending = True
            matching.notified = True
            matching.notification_status = "attending"
        elif action == "not_going":
            matching.is_attending = False
            matching.notified = True
            matching.notification_status = "sent"
        elif action == "confirm":
            matching.status = "confirmed"
        elif action == "confirm_silent":
            matching.status = "confirmed"
            matching.notified = True
            matching.notification_status = "sent"
        elif action == "reject":
            matching.status = "rejected"
            matching.notification_status = "dismissed"
        else:
            raise ValueError(f"Unsupported event action: {action}")

    db.commit()
    return len(matches)


def record_notification_result(event: Event, *, sent: bool) -> None:
    """Record a notification attempt without hiding failed sends from retries."""
    if sent:
        event.notified = True
        event.notification_status = "sent"


def normalize_event_history(
    db: Session,
    *,
    as_of: Optional[date] = None,
) -> EventHistoryNormalization:
    """Expire past rows and merge exact legacy duplicates safely."""
    as_of = as_of or date.today()
    expirable = (
        db.query(Event)
        .filter(
            Event.event_date.is_not(None),
            Event.event_date < as_of,
            Event.status.in_(("confirmed", "possible")),
        )
        .all()
    )
    for event in expirable:
        event.status = "expired"
        if event.notification_status == "pending":
            event.notification_status = "dismissed"

    groups: dict[str, list[Event]] = {}
    for event in db.query(Event).order_by(Event.first_seen_at, Event.id).all():
        groups.setdefault(_performance_key_for_event(event), []).append(event)

    duplicates_removed = 0
    survivors: list[Event] = []
    for rows in groups.values():
        survivor = _choose_survivor(rows)
        survivors.append(survivor)
        if len(rows) == 1:
            continue

        _merge_rows(survivor, rows)
        for duplicate in rows:
            if duplicate.id != survivor.id:
                db.delete(duplicate)
                duplicates_removed += 1

    db.flush()
    for survivor in survivors:
        survivor.dedup_key = _performance_key_for_event(survivor)
    db.commit()
    return EventHistoryNormalization(
        expired=len(expirable),
        duplicates_removed=duplicates_removed,
    )


def _upsert_event(
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
    source_provider: Optional[str],
    source_event_id: Optional[str],
    status: str,
    confidence_score: float,
    match_reason: Optional[str],
    evidence_text: Optional[str],
    matched_location_profile_id: Optional[int],
) -> tuple[Event, bool]:
    dedup_key = _make_performance_key(
        artist_id=artist_id,
        event_name=event_name,
        venue=venue,
        city=city,
        event_date=event_date,
        event_time=event_time,
    )
    existing = _find_existing_event(
        db=db,
        artist_id=artist_id,
        dedup_key=dedup_key,
        venue=venue,
        city=city,
        event_date=event_date,
        event_time=event_time,
        ticket_url=ticket_url,
        ticketmaster_event_id=ticketmaster_event_id,
        source_provider=source_provider,
        source_event_id=source_event_id,
    )
    if existing:
        _update_existing_event(
            existing,
            event_name=event_name,
            region=region,
            country=country,
            event_time=event_time,
            ticket_url=ticket_url,
            source_url=source_url,
            ticketmaster_event_id=ticketmaster_event_id,
            source_provider=source_provider,
            source_event_id=source_event_id,
            status=status,
            confidence_score=confidence_score,
            match_reason=match_reason,
            evidence_text=evidence_text,
            matched_location_profile_id=matched_location_profile_id,
        )
        db.flush()
        return existing, False

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
        source_provider=source_provider,
        source_event_id=source_event_id,
        status=status,
        confidence_score=confidence_score,
        match_reason=match_reason,
        evidence_text=evidence_text,
        matched_location_profile_id=matched_location_profile_id,
        dedup_key=dedup_key,
        notification_status="pending",
    )
    db.add(event)
    db.flush()
    return event, True


def _find_existing_event(
    db: Session,
    artist_id: int,
    dedup_key: str,
    venue: str,
    city: str,
    event_date: Optional[date],
    event_time: Optional[time],
    ticket_url: Optional[str],
    ticketmaster_event_id: Optional[str],
    source_provider: Optional[str],
    source_event_id: Optional[str],
) -> Optional[Event]:
    if source_provider and source_event_id:
        event = (
            db.query(Event)
            .filter(
                Event.artist_id == artist_id,
                Event.source_provider == source_provider,
                Event.source_event_id == source_event_id,
            )
            .first()
        )
        if event:
            return event

    if ticketmaster_event_id:
        event = (
            db.query(Event)
            .filter(
                Event.artist_id == artist_id,
                Event.ticketmaster_event_id == ticketmaster_event_id,
            )
            .first()
        )
        if event:
            return event

    event = db.query(Event).filter(Event.dedup_key == dedup_key).first()
    if event:
        return event

    candidates = db.query(Event).filter(Event.artist_id == artist_id)
    if event_date:
        candidates = candidates.filter(Event.event_date == event_date)
    candidate_rows = candidates.order_by(Event.first_seen_at, Event.id).all()

    normalized_url = _normalize_url(ticket_url)
    if normalized_url:
        for candidate in candidate_rows:
            if _normalize_url(candidate.ticket_url) == normalized_url:
                return candidate

    if event_date:
        same_place = [
            candidate
            for candidate in candidate_rows
            if _normalize_text(candidate.venue) == _normalize_text(venue)
            and _normalize_text(candidate.city) == _normalize_text(city)
        ]
        exact_time = [candidate for candidate in same_place if candidate.event_time == event_time]
        if exact_time:
            return exact_time[0]
        if event_time:
            missing_time = [candidate for candidate in same_place if candidate.event_time is None]
            if len(missing_time) == 1:
                return missing_time[0]
        elif len(same_place) == 1:
            return same_place[0]

    return None


def _update_existing_event(event: Event, **values) -> None:
    for field in (
        "region",
        "country",
        "event_time",
        "ticket_url",
        "source_url",
        "ticketmaster_event_id",
        "source_provider",
        "source_event_id",
        "match_reason",
        "evidence_text",
        "matched_location_profile_id",
    ):
        value = values.get(field)
        if value and not getattr(event, field):
            setattr(event, field, value)

    # A user rejection is terminal. Confirmed events are never downgraded.
    incoming_status = values["status"]
    if event.status not in {"rejected", "expired"}:
        priority = {"possible": 1, "confirmed": 2}
        if priority.get(incoming_status, 0) > priority.get(event.status, 0):
            event.status = incoming_status
            event.confidence_score = values["confidence_score"]

    if values.get("event_name") and not event.event_name:
        event.event_name = values["event_name"]
    event.updated_at = datetime.utcnow()


def _same_performance_rows(db: Session, event: Event) -> list[Event]:
    rows = (
        db.query(Event)
        .filter(
            Event.artist_id == event.artist_id,
            Event.event_date == event.event_date,
            func.lower(func.trim(Event.venue)) == event.venue.strip().lower(),
            func.lower(func.trim(Event.city)) == event.city.strip().lower(),
        )
        .all()
    )
    if event.event_time:
        compatible = [
            row for row in rows if row.event_time in {None, event.event_time}
        ]
        return compatible or [event]
    return rows or [event]


def _choose_survivor(rows: list[Event]) -> Event:
    return sorted(
        rows,
        key=lambda event: (
            not event.is_attending,
            not event.notified,
            event.status != "confirmed",
            event.first_seen_at or datetime.max,
            event.id,
        ),
    )[0]


def _merge_rows(survivor: Event, rows: list[Event]) -> None:
    survivor.is_attending = any(row.is_attending for row in rows)
    survivor.notified = any(row.notified for row in rows) or survivor.is_attending
    if survivor.is_attending:
        survivor.notification_status = "attending"
    elif any(row.status == "rejected" for row in rows):
        survivor.status = "rejected"
        survivor.notification_status = "dismissed"
    elif survivor.notified or any(row.notification_status == "sent" for row in rows):
        survivor.notification_status = "sent"

    status_priority = {"expired": 0, "possible": 1, "confirmed": 2}
    if survivor.status != "rejected":
        best_status = max(rows, key=lambda row: status_priority.get(row.status, 0))
        survivor.status = best_status.status
        survivor.confidence_score = best_status.confidence_score

    for field in (
        "ticket_url",
        "source_url",
        "ticketmaster_event_id",
        "source_provider",
        "source_event_id",
        "evidence_text",
        "region",
        "country",
        "event_time",
        "match_reason",
        "matched_location_profile_id",
    ):
        if not getattr(survivor, field):
            value = next((getattr(row, field) for row in rows if getattr(row, field)), None)
            if value:
                setattr(survivor, field, value)


def _performance_key_for_event(event: Event) -> str:
    return _make_performance_key(
        artist_id=event.artist_id,
        event_name=event.event_name,
        venue=event.venue,
        city=event.city,
        event_date=event.event_date,
        event_time=event.event_time,
    )


def _make_performance_key(
    artist_id: int,
    event_name: str,
    venue: str,
    city: str,
    event_date: Optional[date],
    event_time: Optional[time],
) -> str:
    parts = [
        str(artist_id),
        event_date.isoformat() if event_date else "nodate",
        _normalize_text(venue),
        _normalize_text(city),
        event_time.isoformat() if event_time else "notime",
    ]
    if not event_date:
        parts.append(_normalize_text(event_name))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def _normalize_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold())


def _normalize_url(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        split = urlsplit(value.strip())
        query = urlencode(
            [
                (key, item)
                for key, item in parse_qsl(split.query, keep_blank_values=True)
                if not key.casefold().startswith("utm_")
            ]
        )
        return urlunsplit(
            (
                split.scheme.casefold(),
                split.netloc.casefold(),
                split.path.rstrip("/"),
                query,
                "",
            )
        )
    except ValueError:
        return value.strip()


def _parse_date(value) -> Optional[date]:
    if not value or value == "TBD":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_time(value) -> Optional[time]:
    if not value:
        return None
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        return None

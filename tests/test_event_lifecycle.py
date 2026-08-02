from __future__ import annotations

from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models.artist import Artist
from app.models.event import Event
from app.models.location import LocationProfile
from app.services.event_lifecycle import (
    apply_event_action,
    normalize_event_history,
    process_discovered_event,
    record_notification_result,
)


def _context():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    artist = Artist(name="Adam Ray", artist_type="comedy")
    profile = LocationProfile(
        name="Vancouver / Lower Mainland",
        latitude=49.2827,
        longitude=-123.1207,
        radius_km=60,
        country_code="CA",
        region_code="BC",
        is_default=True,
    )
    db.add_all([artist, profile])
    db.commit()
    return db, artist, profile


def _discovery(**overrides):
    event = {
        "event_name": 'Adam Ray - "Who Is Me" Tour',
        "venue": "Stanley Park",
        "city": "Vancouver",
        "region": "BC",
        "country": "Canada",
        "date": "2026-08-29",
        "time": "19:00:00",
        "ticket_url": "https://tickets.example/show-1?utm_source=tour",
        "source_url": "https://adamraycomedy.com/tour",
    }
    event.update(overrides)
    return event


def test_michael_blaustein_past_show_is_not_persisted():
    db, artist, profile = _context()
    artist.name = "Michael Blaustein"

    result = process_discovered_event(
        db,
        artist,
        _discovery(
            event_name="Michael Blaustein: The Taste Me Tour",
            venue="Massey Theatre",
            date="2026-05-08",
        ),
        [profile],
        "official_website",
        as_of=date(2026, 8, 2),
    )

    assert result.outcome == "past"
    assert result.event is None
    assert db.query(Event).count() == 0


def test_title_and_tracking_url_changes_reuse_same_performance():
    db, artist, profile = _context()
    first = process_discovered_event(
        db,
        artist,
        _discovery(),
        [profile],
        "official_website",
        as_of=date(2026, 8, 2),
    )
    second = process_discovered_event(
        db,
        artist,
        _discovery(
            event_name="Who Is Me Tour",
            ticket_url="https://tickets.example/show-1?utm_campaign=summer",
        ),
        [profile],
        "official_website",
        as_of=date(2026, 8, 2),
    )

    assert first.outcome == "confirmed"
    assert first.is_new is True
    assert first.should_notify is True
    assert second.outcome == "existing"
    assert second.is_new is False
    assert second.event.id == first.event.id
    assert db.query(Event).count() == 1


def test_two_showtimes_at_same_venue_remain_separate_performances():
    db, artist, profile = _context()
    early = process_discovered_event(
        db,
        artist,
        _discovery(time="19:00:00", ticket_url="https://tickets.example/early"),
        [profile],
        "official_website",
        as_of=date(2026, 8, 2),
    )
    late = process_discovered_event(
        db,
        artist,
        _discovery(time="21:30:00", ticket_url="https://tickets.example/late"),
        [profile],
        "official_website",
        as_of=date(2026, 8, 2),
    )

    assert early.is_new is True
    assert late.is_new is True
    assert db.query(Event).count() == 2


def test_going_suppresses_only_that_performance_and_survives_rediscovery():
    db, artist, profile = _context()
    first = process_discovered_event(
        db,
        artist,
        _discovery(),
        [profile],
        "official_website",
        as_of=date(2026, 8, 2),
    )
    apply_event_action(db, first.event.id, "going")

    rediscovered = process_discovered_event(
        db,
        artist,
        _discovery(event_name="Who Is Me Tour"),
        [profile],
        "official_website",
        as_of=date(2026, 8, 2),
    )
    later_show = process_discovered_event(
        db,
        artist,
        _discovery(date="2026-10-10", ticket_url="https://tickets.example/future"),
        [profile],
        "official_website",
        as_of=date(2026, 8, 2),
    )

    assert rediscovered.event.notification_status == "attending"
    assert rediscovered.should_notify is False
    assert later_show.should_notify is True


def test_failed_notification_remains_pending_for_retry():
    db, artist, profile = _context()
    result = process_discovered_event(
        db,
        artist,
        _discovery(),
        [profile],
        "official_website",
        as_of=date(2026, 8, 2),
    )
    record_notification_result(result.event, sent=False)
    db.commit()

    retry = process_discovered_event(
        db,
        artist,
        _discovery(),
        [profile],
        "official_website",
        as_of=date(2026, 8, 2),
    )

    assert retry.is_new is False
    assert retry.outcome == "existing"
    assert retry.should_notify is True


def test_rejected_performance_is_not_resurrected_by_rediscovery():
    db, artist, profile = _context()
    result = process_discovered_event(
        db,
        artist,
        _discovery(),
        [profile],
        "official_website",
        as_of=date(2026, 8, 2),
    )
    apply_event_action(db, result.event.id, "reject")

    rediscovered = process_discovered_event(
        db,
        artist,
        _discovery(),
        [profile],
        "ticketmaster",
        as_of=date(2026, 8, 2),
    )

    assert rediscovered.event.status == "rejected"
    assert rediscovered.should_notify is False


def test_normalization_expires_past_rows_and_merges_legacy_duplicates():
    db, artist, _profile = _context()
    shared = {
        "artist_id": artist.id,
        "venue": "Stanley Park",
        "city": "Vancouver",
        "region": "BC",
        "country": "Canada",
        "event_date": date(2026, 5, 8),
        "event_time": time(19, 0),
        "source_type": "official_website",
        "status": "confirmed",
        "confidence_score": 1.0,
        "notification_status": "sent",
    }
    db.add_all(
        [
            Event(event_name="Old title", dedup_key="legacy-a", **shared),
            Event(
                event_name="Changed title",
                dedup_key="legacy-b",
                is_attending=True,
                **shared,
            ),
        ]
    )
    db.commit()

    normalized = normalize_event_history(db, as_of=date(2026, 8, 2))

    assert normalized.expired == 2
    assert normalized.duplicates_removed == 1
    remaining = db.query(Event).one()
    assert remaining.status == "expired"
    assert remaining.is_attending is True
    assert remaining.notification_status == "attending"

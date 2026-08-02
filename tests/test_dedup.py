import pytest
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Artist
from app.services.dedup import make_dedup_key, upsert_event

def test_make_dedup_key_consistency():
    artist_id = 1
    event_name = "Dave Chappelle Live"
    venue = "Rogers Arena"
    city = "Vancouver"
    event_date = datetime.date(2026, 10, 15)

    key1 = make_dedup_key(artist_id, event_name, venue, city, event_date)
    key2 = make_dedup_key(artist_id, " Dave Chappelle Live ", " rogers arena ", "Vancouver", event_date)
    
    assert key1 == key2, "Dedup key should be case and whitespace insensitive"
    assert len(key1) == 32, "Dedup key should be a 32-char hex string"

def test_make_dedup_key_no_date():
    key1 = make_dedup_key(1, "Test", "Venue", "City", None)
    key2 = make_dedup_key(1, "Test", "Venue", "City", None)
    assert key1 == key2, "Keys matching without dates should be consistent"


def test_upsert_reuses_same_performance_when_extracted_title_changes():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        artist = Artist(name="Adam Ray", artist_type="comedy")
        db.add(artist)
        db.flush()

        shared = {
            "db": db,
            "artist_id": artist.id,
            "venue": "Stanley Park",
            "city": "Vancouver",
            "region": "BC",
            "country": "Canada",
            "event_date": datetime.date(2026, 8, 29),
            "event_time": None,
            "ticket_url": "https://link.seated.com/show-1",
            "source_url": "https://adamraycomedy.com/tour",
            "source_type": "official_website",
            "ticketmaster_event_id": None,
            "status": "confirmed",
            "confidence_score": 1.0,
            "match_reason": "exact_city",
            "evidence_text": None,
            "matched_location_profile_id": None,
        }
        first, first_is_new = upsert_event(event_name="Who Is Me Tour", **shared)
        second, second_is_new = upsert_event(
            event_name='Adam Ray - "Who Is Me" Tour',
            **shared,
        )

        assert first_is_new is True
        assert second_is_new is False
        assert second.id == first.id

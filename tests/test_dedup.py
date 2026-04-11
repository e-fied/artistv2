import pytest
import datetime
from app.services.dedup import make_dedup_key

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

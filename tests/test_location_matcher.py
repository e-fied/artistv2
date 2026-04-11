import pytest
from app.models.location import LocationProfile, LocationAlias
from app.services.location_matcher import match_event_to_locations, haversine_km

def test_haversine_km():
    # Vancouver vs Seattle
    dist = haversine_km(49.2827, -123.1207, 47.6062, -122.3321)
    # Approx 193 km
    assert 190 < dist < 200

def test_match_exact_city():
    profile = LocationProfile(id=1, name="Vancouver", radius_km=100)
    match = match_event_to_locations(
        event_city="Vancouver",
        event_region=None,
        event_country=None,
        event_lat=None,
        event_lon=None,
        profiles=[profile]
    )
    assert match is not None
    assert match.matched is True
    assert match.confidence == 1.0
    assert match.reason == "exact_city"

def test_match_alias_city():
    profile = LocationProfile(id=1, name="Vancouver", radius_km=100)
    profile.aliases = [LocationAlias(alias_city="Burnaby")]
    
    match = match_event_to_locations(
        event_city="Burnaby",
        event_region=None,
        event_country=None,
        event_lat=None,
        event_lon=None,
        profiles=[profile]
    )
    assert match is not None
    assert match.matched is True
    assert match.confidence == 0.95
    assert match.reason == "alias:Burnaby"

def test_match_radius():
    profile = LocationProfile(id=1, name="Vancouver", latitude=49.2827, longitude=-123.1207, radius_km=50)
    # Event in Richmond (close enough)
    match = match_event_to_locations(
        event_city="Richmond",
        event_region=None,
        event_country=None,
        event_lat=49.1666,
        event_lon=-123.1336,
        profiles=[profile]
    )
    assert match is not None
    assert match.matched is True
    assert "radius_km" in match.reason

def test_no_match():
    profile = LocationProfile(id=1, name="Vancouver", latitude=49.2827, longitude=-123.1207, radius_km=50)
    # Event in Toronto
    match = match_event_to_locations(
        event_city="Toronto",
        event_region=None,
        event_country=None,
        event_lat=43.651070,
        event_lon=-79.347015,
        profiles=[profile]
    )
    assert match is None

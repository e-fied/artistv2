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
        event_venue=None,
        profiles=[profile]
    )
    assert match is not None
    assert match.matched is True
    assert match.confidence == 1.0
    assert match.reason == "exact_city"

def test_match_alias_city():
    profile = LocationProfile(id=1, name="Vancouver", radius_km=100, region_code="BC", country_code="CA")
    profile.aliases = [LocationAlias(alias_city="Burnaby")]
    
    match = match_event_to_locations(
        event_city="Burnaby",
        event_region="BC",
        event_country="CA",
        event_lat=None,
        event_lon=None,
        event_venue=None,
        profiles=[profile]
    )
    assert match is not None
    assert match.matched is True
    assert match.confidence == 0.95
    assert match.reason == "alias:Burnaby"

def test_alias_city_does_not_cross_region_or_country():
    profile = LocationProfile(id=1, name="Vancouver", radius_km=100, region_code="BC", country_code="CA")
    profile.aliases = [LocationAlias(alias_city="Richmond")]

    match = match_event_to_locations(
        event_city="Richmond",
        event_region="VA",
        event_country="US",
        event_lat=None,
        event_lon=None,
        event_venue="Dominion Energy Center",
        profiles=[profile],
    )

    assert match is None

def test_match_radius():
    profile = LocationProfile(id=1, name="Vancouver", latitude=49.2827, longitude=-123.1207, radius_km=50)
    # Event in Richmond (close enough)
    match = match_event_to_locations(
        event_city="Richmond",
        event_region=None,
        event_country=None,
        event_lat=49.1666,
        event_lon=-123.1336,
        event_venue=None,
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
        event_venue=None,
        profiles=[profile]
    )
    assert match is None

def test_match_alias_city_partial_name():
    profile = LocationProfile(id=1, name="Toronto", radius_km=50)
    profile.aliases = [LocationAlias(alias_city="Rama")]

    match = match_event_to_locations(
        event_city="Rama First Nation",
        event_region="ON",
        event_country="CA",
        event_lat=None,
        event_lon=None,
        event_venue=None,
        profiles=[profile]
    )
    assert match is not None
    assert match.matched is True
    assert match.reason == "alias:Rama"

def test_match_alias_from_venue_name():
    profile = LocationProfile(id=1, name="Toronto", radius_km=50, region_code="ON", country_code="CA")
    profile.aliases = [LocationAlias(alias_city="Rama")]

    match = match_event_to_locations(
        event_city="Orillia",
        event_region="ON",
        event_country="CA",
        event_lat=None,
        event_lon=None,
        event_venue="Casino Rama Resort",
        profiles=[profile]
    )
    assert match is not None
    assert match.matched is True
    assert match.reason == "venue_alias:Rama"

def test_venue_alias_does_not_cross_region():
    profile = LocationProfile(id=1, name="Vancouver", radius_km=50, region_code="BC", country_code="CA")
    profile.aliases = [LocationAlias(alias_city="Delta")]

    match = match_event_to_locations(
        event_city="Fredericton",
        event_region="NB",
        event_country="CA",
        event_lat=None,
        event_lon=None,
        event_venue="Delta Ballroom",
        profiles=[profile]
    )
    assert match is None

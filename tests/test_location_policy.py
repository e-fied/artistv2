from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.artist import Artist, ArtistLocation
from app.models.location import LocationProfile
from app.services.location_policy import (
    get_artist_location_policy,
    normalize_location_policy,
    replace_artist_travel_cities,
    set_global_home_area,
)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _profile(name: str, *, default: bool = False) -> LocationProfile:
    return LocationProfile(
        name=name,
        latitude=49.0,
        longitude=-123.0,
        radius_km=50,
        country_code="CA",
        is_default=default,
    )


def test_global_home_is_included_with_artist_travel_city():
    db = _session()
    artist = Artist(name="Test Artist", artist_type="comedy")
    vancouver = _profile("Vancouver / Lower Mainland", default=True)
    denver = _profile("Denver")
    db.add_all([artist, vancouver, denver])
    db.flush()
    db.add(
        ArtistLocation(
            artist_id=artist.id,
            location_profile_id=denver.id,
            is_travel_city=True,
        )
    )
    db.commit()

    policy = get_artist_location_policy(db, artist.id)

    assert [profile.name for profile in policy.home_profiles] == [
        "Vancouver / Lower Mainland"
    ]
    assert [profile.name for profile in policy.travel_profiles] == ["Denver"]
    assert [profile.name for profile in policy.profiles] == [
        "Vancouver / Lower Mainland",
        "Denver",
    ]


def test_replace_travel_cities_ignores_home_and_invalid_profiles():
    db = _session()
    artist = Artist(name="Test Artist", artist_type="comedy")
    vancouver = _profile("Vancouver / Lower Mainland", default=True)
    denver = _profile("Denver")
    db.add_all([artist, vancouver, denver])
    db.flush()

    replace_artist_travel_cities(
        db,
        artist.id,
        [vancouver.id, denver.id, 999_999],
    )
    db.commit()

    assignments = db.query(ArtistLocation).all()
    assert len(assignments) == 1
    assert assignments[0].location_profile_id == denver.id
    assert assignments[0].is_travel_city is True


def test_normalization_preserves_legacy_non_default_location_as_travel():
    db = _session()
    artist = Artist(name="Test Artist", artist_type="comedy")
    vancouver = _profile("Vancouver / Lower Mainland", default=True)
    denver = _profile("Denver")
    db.add_all([artist, vancouver, denver])
    db.flush()
    db.add_all(
        [
            ArtistLocation(
                artist_id=artist.id,
                location_profile_id=vancouver.id,
                is_travel_city=False,
            ),
            ArtistLocation(
                artist_id=artist.id,
                location_profile_id=denver.id,
                is_travel_city=False,
            ),
        ]
    )
    db.commit()

    normalize_location_policy(db)

    assignments = db.query(ArtistLocation).all()
    assert len(assignments) == 1
    assert assignments[0].location_profile_id == denver.id
    assert assignments[0].is_travel_city is True


def test_setting_home_area_replaces_previous_default():
    db = _session()
    vancouver = _profile("Vancouver / Lower Mainland", default=True)
    seattle = _profile("Seattle")
    db.add_all([vancouver, seattle])
    db.flush()

    set_global_home_area(db, seattle)
    db.commit()

    defaults = (
        db.query(LocationProfile)
        .filter(LocationProfile.is_default.is_(True))
        .all()
    )
    assert [profile.name for profile in defaults] == ["Seattle"]

"""Global home-area and per-artist travel-city policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.artist import ArtistLocation
from app.models.location import LocationProfile


@dataclass(frozen=True)
class ArtistLocationPolicy:
    """Resolved locations that should be considered for one artist."""

    home_profiles: tuple[LocationProfile, ...]
    travel_profiles: tuple[LocationProfile, ...]

    @property
    def profiles(self) -> list[LocationProfile]:
        return [*self.home_profiles, *self.travel_profiles]

    @property
    def travel_profile_ids(self) -> set[int]:
        return {profile.id for profile in self.travel_profiles}


def get_artist_location_policy(db: Session, artist_id: int) -> ArtistLocationPolicy:
    """Resolve the global home area plus this artist's travel-city additions."""
    home_profiles = tuple(
        db.query(LocationProfile)
        .filter(LocationProfile.is_default.is_(True))
        .order_by(LocationProfile.name)
        .all()
    )
    home_ids = {profile.id for profile in home_profiles}

    linked_profiles = (
        db.query(LocationProfile)
        .join(ArtistLocation, ArtistLocation.location_profile_id == LocationProfile.id)
        .filter(ArtistLocation.artist_id == artist_id)
        .order_by(LocationProfile.name)
        .all()
    )
    travel_profiles = tuple(
        profile for profile in linked_profiles if profile.id not in home_ids
    )
    return ArtistLocationPolicy(
        home_profiles=home_profiles,
        travel_profiles=travel_profiles,
    )


def replace_artist_travel_cities(
    db: Session,
    artist_id: int,
    location_profile_ids: Iterable[int],
) -> None:
    """Replace one artist's travel cities, ignoring home and invalid profiles."""
    requested_ids = {int(profile_id) for profile_id in location_profile_ids}
    allowed_ids = {
        profile_id
        for (profile_id,) in (
            db.query(LocationProfile.id)
            .filter(
                LocationProfile.id.in_(requested_ids),
                LocationProfile.is_default.is_(False),
            )
            .all()
        )
    }

    db.query(ArtistLocation).filter(ArtistLocation.artist_id == artist_id).delete()
    for profile_id in sorted(allowed_ids):
        db.add(
            ArtistLocation(
                artist_id=artist_id,
                location_profile_id=profile_id,
                is_travel_city=True,
            )
        )


def set_global_home_area(db: Session, profile: LocationProfile) -> None:
    """Make one location the only global home area."""
    db.query(LocationProfile).filter(LocationProfile.id != profile.id).update(
        {LocationProfile.is_default: False},
        synchronize_session="fetch",
    )
    profile.is_default = True


def normalize_location_policy(db: Session) -> None:
    """Convert legacy artist assignments to the global-home policy in place."""
    default_profiles = (
        db.query(LocationProfile)
        .filter(LocationProfile.is_default.is_(True))
        .order_by(LocationProfile.id)
        .all()
    )

    if len(default_profiles) > 1:
        preferred = next(
            (
                profile
                for profile in default_profiles
                if "vancouver" in profile.name.casefold()
            ),
            default_profiles[0],
        )
        set_global_home_area(db, preferred)
        default_profiles = [preferred]

    if not default_profiles:
        vancouver = (
            db.query(LocationProfile)
            .filter(LocationProfile.name.ilike("%vancouver%"))
            .order_by(LocationProfile.id)
            .first()
        )
        if vancouver:
            set_global_home_area(db, vancouver)
            default_profiles = [vancouver]

    home_ids = {profile.id for profile in default_profiles}
    if home_ids:
        db.query(ArtistLocation).filter(
            ArtistLocation.location_profile_id.in_(home_ids)
        ).delete(synchronize_session=False)

    db.query(ArtistLocation).update(
        {ArtistLocation.is_travel_city: True},
        synchronize_session=False,
    )
    db.commit()

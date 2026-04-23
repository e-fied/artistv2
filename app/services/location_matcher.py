"""Location matching service.

Determines whether an event is "near" a location profile using:
1. Exact city name match
2. Alias city name match
3. Haversine distance (lat/lon radius)
"""

from __future__ import annotations

import logging
import math
import re
from typing import Optional, List, Tuple

from sqlalchemy.orm import Session

from app.models.location import LocationAlias, LocationProfile

logger = logging.getLogger(__name__)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points on Earth (in km)."""
    R = 6371.0  # Earth's radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


class MatchResult:
    """Result of a location match attempt."""

    def __init__(
        self,
        matched: bool,
        reason: str = "",
        distance_km: Optional[float] = None,
        profile: Optional[LocationProfile] = None,
        confidence: float = 0.0,
    ):
        self.matched = matched
        self.reason = reason
        self.distance_km = distance_km
        self.profile = profile
        self.confidence = confidence

    def __repr__(self) -> str:
        return f"MatchResult(matched={self.matched}, reason={self.reason}, distance_km={self.distance_km})"


def match_event_to_locations(
    event_city: str,
    event_region: Optional[str],
    event_country: Optional[str],
    event_lat: Optional[float],
    event_lon: Optional[float],
    event_venue: Optional[str],
    profiles: List[LocationProfile],
) -> Optional[MatchResult]:
    """Try to match an event's location against a list of location profiles.
    
    Returns the best MatchResult if found, or None if no match.
    
    Priority:
    1. Exact city name match → confidence 1.0
    2. Alias match → confidence 0.95
    3. Geo-radius match → confidence based on distance
    """
    if not profiles:
        return None

    city_lower = event_city.strip().lower() if event_city else ""
    venue_lower = event_venue.strip().lower() if event_venue else ""

    best_match: Optional[MatchResult] = None

    for profile in profiles:
        # 1. Exact city name match
        profile_name_lower = profile.name.strip().lower()
        if city_lower and city_lower in profile_name_lower:
            return MatchResult(
                matched=True,
                reason="exact_city",
                distance_km=0,
                profile=profile,
                confidence=1.0,
            )

        # 2. Alias match
        for alias in profile.aliases:
            alias_lower = alias.alias_city.strip().lower()
            if city_lower and (
                city_lower == alias_lower
                or alias_lower in city_lower
                or city_lower in alias_lower
            ):
                return MatchResult(
                    matched=True,
                    reason=f"alias:{alias.alias_city}",
                    distance_km=None,
                    profile=profile,
                    confidence=0.95,
                )
            if venue_lower and alias_lower and re.search(rf"\b{re.escape(alias_lower)}\b", venue_lower):
                return MatchResult(
                    matched=True,
                    reason=f"venue_alias:{alias.alias_city}",
                    distance_km=None,
                    profile=profile,
                    confidence=0.9,
                )

        # 3. Geo-radius match (if we have event coordinates)
        if event_lat and event_lon and profile.latitude and profile.longitude:
            dist = haversine_km(
                profile.latitude, profile.longitude,
                event_lat, event_lon,
            )
            if dist <= profile.radius_km:
                confidence = max(0.7, 1.0 - (dist / profile.radius_km) * 0.3)
                match = MatchResult(
                    matched=True,
                    reason=f"radius_km:{dist:.0f}",
                    distance_km=dist,
                    profile=profile,
                    confidence=round(confidence, 2),
                )
                if best_match is None or confidence > best_match.confidence:
                    best_match = match

    return best_match


def get_profiles_for_artist(
    db: Session,
    artist_id: int,
) -> List[LocationProfile]:
    """Get all location profiles that apply to an artist.
    
    Includes:
    - Profiles directly linked to the artist (via ArtistLocation)
    - Default profiles (is_default=True) if the artist has no explicit assignments
    """
    from app.models.artist import ArtistLocation

    # Get explicitly linked profiles
    linked = (
        db.query(LocationProfile)
        .join(ArtistLocation, ArtistLocation.location_profile_id == LocationProfile.id)
        .filter(ArtistLocation.artist_id == artist_id)
        .all()
    )

    if linked:
        return linked

    # Fall back to default profiles
    defaults = (
        db.query(LocationProfile)
        .filter(LocationProfile.is_default == True)
        .all()
    )

    return defaults

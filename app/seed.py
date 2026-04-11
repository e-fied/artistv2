"""Seed data — pre-populate Vancouver / Lower Mainland location profile."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.location import LocationAlias, LocationProfile

logger = logging.getLogger(__name__)

VANCOUVER_ALIASES = [
    "Burnaby",
    "New Westminster",
    "Surrey",
    "Richmond",
    "North Vancouver",
    "West Vancouver",
    "Coquitlam",
    "Port Coquitlam",
    "Port Moody",
    "Delta",
    "Langley",
    "White Rock",
    "Maple Ridge",
    "Pitt Meadows",
    "Abbotsford",
    "Chilliwack",
    "Mission",
    "Squamish",
    "Whistler",
]


def seed_locations(db: Session) -> None:
    """Create default location profiles if they don't exist."""
    existing = db.query(LocationProfile).first()
    if existing:
        logger.info("Location profiles already exist — skipping seed")
        return

    # Vancouver / Lower Mainland
    vancouver = LocationProfile(
        name="Vancouver / Lower Mainland",
        latitude=49.2827,
        longitude=-123.1207,
        radius_km=60,
        country_code="CA",
        region_code="BC",
        is_default=True,
    )
    db.add(vancouver)
    db.flush()

    for city in VANCOUVER_ALIASES:
        db.add(LocationAlias(
            location_profile_id=vancouver.id,
            alias_city=city,
        ))

    db.commit()
    logger.info(
        f"Seeded Vancouver / Lower Mainland profile with {len(VANCOUVER_ALIASES)} aliases"
    )

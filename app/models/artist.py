"""Artist, ArtistSource, and ArtistLocation models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.location import LocationProfile
    from app.models.scan import ScanRun


class Artist(Base):
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    artist_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="music"
    )  # music | comedy

    # Ticketmaster identity (cached after user picks the correct match)
    ticketmaster_attraction_id: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    ticketmaster_attraction_name: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )

    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    sources: Mapped[List["ArtistSource"]] = relationship(
        back_populates="artist", cascade="all, delete-orphan"
    )
    locations: Mapped[List["ArtistLocation"]] = relationship(
        back_populates="artist", cascade="all, delete-orphan"
    )
    events: Mapped[List["Event"]] = relationship(
        "Event", back_populates="artist", cascade="all, delete-orphan"
    )
    scan_runs: Mapped[List["ScanRun"]] = relationship(
        "ScanRun", back_populates="artist", cascade="all, delete-orphan"
    )


class ArtistSource(Base):
    """A data source for an artist — Ticketmaster, official website, manual URL, etc."""

    __tablename__ = "artist_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artist_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # ticketmaster | official_website | manual_url | auto_found
    url: Mapped[Optional[str]] = mapped_column(
        String(1000), nullable=True
    )  # null for ticketmaster
    fetch_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="auto"
    )  # auto | crawl4ai | firecrawl | disabled
    preferred_crawler: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # learned: crawl4ai | firecrawl
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )  # SHA-256
    is_approved: Mapped[bool] = mapped_column(
        Boolean, default=True
    )  # false for auto-found until user approves
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # Relationships
    artist: Mapped["Artist"] = relationship(back_populates="sources")


class ArtistLocation(Base):
    """Links an artist to a location profile (home city or travel city)."""

    __tablename__ = "artist_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artist_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False
    )
    location_profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("location_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_travel_city: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # false = home, true = would travel for

    # Relationships
    artist: Mapped["Artist"] = relationship(back_populates="locations")
    location_profile: Mapped["LocationProfile"] = relationship()

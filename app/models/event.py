"""Event and EventReview models."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.artist import Artist


class Event(Base):
    """A discovered event — confirmed, possible, rejected, or expired."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artist_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False
    )
    event_name: Mapped[str] = mapped_column(String(500), nullable=False)
    venue: Mapped[str] = mapped_column(String(300), nullable=False)
    city: Mapped[str] = mapped_column(String(200), nullable=False)
    region: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    event_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    event_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    ticket_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # ticketmaster | website
    ticketmaster_event_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )

    # Status and confidence
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="possible"
    )  # confirmed | possible | rejected | expired
    confidence_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5
    )
    match_reason: Mapped[Optional[str]] = mapped_column(
        String(300), nullable=True
    )  # exact_city | alias | radius_km:31 | travel_city
    evidence_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    matched_location_profile_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("location_profiles.id", ondelete="SET NULL"), nullable=True
    )

    # Deduplication
    dedup_key: Mapped[str] = mapped_column(
        String(500), nullable=False, unique=True, index=True
    )

    # Notification tracking
    notified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    artist: Mapped["Artist"] = relationship(back_populates="events")
    reviews: Mapped[List["EventReview"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class EventReview(Base):
    """A user review action on a possible event."""

    __tablename__ = "event_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # confirm | reject | ignore_pattern | mark_source_bad
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # Relationships
    event: Mapped["Event"] = relationship(back_populates="reviews")

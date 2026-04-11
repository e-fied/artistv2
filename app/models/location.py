"""LocationProfile and LocationAlias models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LocationProfile(Base):
    """A tracked location — e.g. 'Vancouver / Lower Mainland'."""

    __tablename__ = "location_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    radius_km: Mapped[int] = mapped_column(Integer, default=50)
    country_code: Mapped[str] = mapped_column(
        String(5), nullable=False, default="CA"
    )
    region_code: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True
    )  # BC, WA, etc.
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # applies to all artists unless overridden
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # Relationships
    aliases: Mapped[List["LocationAlias"]] = relationship(
        back_populates="location_profile", cascade="all, delete-orphan"
    )


class LocationAlias(Base):
    """A city name that should be considered 'within' a location profile."""

    __tablename__ = "location_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("location_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    alias_city: Mapped[str] = mapped_column(String(200), nullable=False)

    # Relationships
    location_profile: Mapped["LocationProfile"] = relationship(
        back_populates="aliases"
    )

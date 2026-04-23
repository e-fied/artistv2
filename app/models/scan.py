"""ScanRun and ScanSourceResult models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.artist import Artist


class ScanRun(Base):
    """A record of a single scan execution (one artist or all)."""

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artist_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=True
    )  # null for "check all"
    trigger: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # scheduled | manual_single | manual_all
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running"
    )  # running | completed | failed
    events_found: Mapped[int] = mapped_column(Integer, default=0)
    new_confirmed: Mapped[int] = mapped_column(Integer, default=0)
    new_possible: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    artist: Mapped[Optional["Artist"]] = relationship(back_populates="scan_runs")
    source_results: Mapped[List["ScanSourceResult"]] = relationship(
        back_populates="scan_run", cascade="all, delete-orphan"
    )


class ScanSourceResult(Base):
    """Result of checking a single source during a scan run."""

    __tablename__ = "scan_source_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False
    )
    artist_source_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("artist_sources.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    fetch_mode_used: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # crawl4ai | firecrawl | ticketmaster
    fetch_success: Mapped[bool] = mapped_column(Boolean, default=False)
    fetch_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_changed: Mapped[bool] = mapped_column(Boolean, default=True)
    events_extracted: Mapped[int] = mapped_column(Integer, default=0)
    fetch_duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    llm_model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    llm_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    llm_cost_is_estimated: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # Relationships
    scan_run: Mapped["ScanRun"] = relationship(back_populates="source_results")

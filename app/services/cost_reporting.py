"""Gemini usage reporting and bounded scan-history retention."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.models.scan import ScanRun, ScanSourceResult


@dataclass(frozen=True)
class UsageTotals:
    source_checks: int
    llm_calls: int
    structured_bypasses: int
    cache_bypasses: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float

    @property
    def deterministic_bypasses(self) -> int:
        return self.structured_bypasses + self.cache_bypasses


@dataclass(frozen=True)
class ModelUsage:
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


@dataclass(frozen=True)
class DailyUsage:
    day: str
    calls: int
    estimated_cost_usd: float


@dataclass(frozen=True)
class CostReport:
    since: datetime
    window: UsageTotals
    all_time: UsageTotals
    models: tuple[ModelUsage, ...]
    daily: tuple[DailyUsage, ...]


def build_cost_report(
    db: Session,
    *,
    days: int = 30,
    as_of: datetime | None = None,
) -> CostReport:
    """Build one operational cost view from persisted source results."""
    as_of = as_of or datetime.utcnow()
    since = as_of - timedelta(days=max(days, 1))
    return CostReport(
        since=since,
        window=_usage_totals(db, since=since),
        all_time=_usage_totals(db),
        models=_model_usage(db, since),
        daily=_daily_usage(db, since),
    )


def prune_scan_history(
    db: Session,
    retention_days: int,
    *,
    as_of: datetime | None = None,
) -> int:
    """Delete completed scan runs outside the configured retention window."""
    if retention_days <= 0:
        return 0

    cutoff = (as_of or datetime.utcnow()) - timedelta(days=retention_days)
    expired = (
        db.query(ScanRun)
        .filter(
            ScanRun.status != "running",
            ScanRun.started_at < cutoff,
        )
        .all()
    )
    for scan in expired:
        db.delete(scan)
    if expired:
        db.commit()
    return len(expired)


def _usage_totals(db: Session, since: datetime | None = None) -> UsageTotals:
    query = db.query(
        func.count(ScanSourceResult.id),
        func.coalesce(func.sum(case((_is_llm_call(), 1), else_=0)), 0),
        func.coalesce(
            func.sum(case((ScanSourceResult.extraction_mode == "structured", 1), else_=0)),
            0,
        ),
        func.coalesce(
            func.sum(case((ScanSourceResult.extraction_mode == "cache", 1), else_=0)),
            0,
        ),
        func.coalesce(func.sum(ScanSourceResult.llm_input_tokens), 0),
        func.coalesce(func.sum(ScanSourceResult.llm_output_tokens), 0),
        func.coalesce(func.sum(ScanSourceResult.llm_estimated_cost_usd), 0.0),
    )
    if since:
        query = query.filter(ScanSourceResult.created_at >= since)
    row = query.one()
    return UsageTotals(
        source_checks=int(row[0] or 0),
        llm_calls=int(row[1] or 0),
        structured_bypasses=int(row[2] or 0),
        cache_bypasses=int(row[3] or 0),
        input_tokens=int(row[4] or 0),
        output_tokens=int(row[5] or 0),
        estimated_cost_usd=float(row[6] or 0.0),
    )


def _model_usage(db: Session, since: datetime) -> tuple[ModelUsage, ...]:
    rows = (
        db.query(
            ScanSourceResult.llm_model,
            func.count(ScanSourceResult.id),
            func.coalesce(func.sum(ScanSourceResult.llm_input_tokens), 0),
            func.coalesce(func.sum(ScanSourceResult.llm_output_tokens), 0),
            func.coalesce(func.sum(ScanSourceResult.llm_estimated_cost_usd), 0.0),
        )
        .filter(ScanSourceResult.created_at >= since, _is_llm_call())
        .group_by(ScanSourceResult.llm_model)
        .order_by(func.sum(ScanSourceResult.llm_estimated_cost_usd).desc())
        .all()
    )
    return tuple(
        ModelUsage(
            model=row[0] or "unrecorded model",
            calls=int(row[1] or 0),
            input_tokens=int(row[2] or 0),
            output_tokens=int(row[3] or 0),
            estimated_cost_usd=float(row[4] or 0.0),
        )
        for row in rows
    )


def _daily_usage(db: Session, since: datetime) -> tuple[DailyUsage, ...]:
    rows = (
        db.query(
            func.date(ScanSourceResult.created_at),
            func.coalesce(func.sum(case((_is_llm_call(), 1), else_=0)), 0),
            func.coalesce(func.sum(ScanSourceResult.llm_estimated_cost_usd), 0.0),
        )
        .filter(ScanSourceResult.created_at >= since)
        .group_by(func.date(ScanSourceResult.created_at))
        .order_by(func.date(ScanSourceResult.created_at).desc())
        .all()
    )
    return tuple(
        DailyUsage(day=str(row[0]), calls=int(row[1] or 0), estimated_cost_usd=float(row[2] or 0.0))
        for row in rows
    )


def _is_llm_call():
    return or_(
        ScanSourceResult.llm_model.is_not(None),
        ScanSourceResult.llm_input_tokens > 0,
        ScanSourceResult.llm_output_tokens > 0,
    )

"""Source management and health routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.artist import ArtistSource
from app.models.scan import ScanSourceResult
from app.services.debug_capture import has_scan_debug

router = APIRouter(prefix="/sources")


@router.get("/health")
def source_health_page(request: Request, db: Session = Depends(get_db)):
    """Show the health status of all tracked sources."""
    sources = (
        db.query(ArtistSource)
        .options(joinedload(ArtistSource.artist))
        .order_by(ArtistSource.consecutive_failures.desc(), ArtistSource.last_checked_at.desc())
        .all()
    )

    failing = [
        source for source in sources
        if source.health_status in {"warning", "error"} or source.consecutive_failures > 0
    ]
    empty = [
        source for source in sources
        if source.health_status == "empty" and source not in failing
    ]
    unknown = [
        source for source in sources
        if source.health_status == "unknown" and source not in failing and source not in empty
    ]
    healthy = [
        source for source in sources
        if source not in failing and source not in empty and source not in unknown
    ]
    latest_debug_scan_by_source = {}
    latest_result_by_source = {}
    for source in sources:
        result = (
            db.query(ScanSourceResult)
            .filter(ScanSourceResult.artist_source_id == source.id)
            .order_by(ScanSourceResult.created_at.desc())
            .first()
        )
        if result:
            latest_result_by_source[source.id] = result
        if result and has_scan_debug(result.scan_run_id):
            latest_debug_scan_by_source[source.id] = result.scan_run_id

    return request.app.state.templates.TemplateResponse(request=request, name="sources/health.html", context={
            "request": request,
            "failing_sources": failing,
            "healthy_sources": healthy,
            "empty_sources": empty,
            "unknown_sources": unknown,
            "latest_debug_scan_by_source": latest_debug_scan_by_source,
            "latest_result_by_source": latest_result_by_source,
        },
    )

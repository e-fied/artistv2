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

    failing = [s for s in sources if s.consecutive_failures > 0]
    healthy = [s for s in sources if s.consecutive_failures == 0]
    latest_debug_scan_by_source = {}
    for source in failing:
        result = (
            db.query(ScanSourceResult)
            .filter(ScanSourceResult.artist_source_id == source.id)
            .order_by(ScanSourceResult.created_at.desc())
            .first()
        )
        if result and has_scan_debug(result.scan_run_id):
            latest_debug_scan_by_source[source.id] = result.scan_run_id

    return request.app.state.templates.TemplateResponse(request=request, name="sources/health.html", context={
            "request": request,
            "failing_sources": failing,
            "healthy_sources": healthy,
            "latest_debug_scan_by_source": latest_debug_scan_by_source,
        },
    )

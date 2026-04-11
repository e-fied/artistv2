"""Source management and health routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.artist import ArtistSource

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

    return request.app.state.templates.TemplateResponse(request=request, name="sources/health.html", context={
            "request": request,
            "failing_sources": failing,
            "healthy_sources": healthy,
        },
    )

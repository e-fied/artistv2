"""Scan history routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.scan import ScanRun

router = APIRouter(prefix="/scans")


@router.get("/")
def scans_page(request: Request, db: Session = Depends(get_db)):
    """Show scan history."""
    scans = (
        db.query(ScanRun)
        .options(joinedload(ScanRun.artist), joinedload(ScanRun.source_results))
        .order_by(ScanRun.started_at.desc())
        .limit(100)
        .all()
    )

    return request.app.state.templates.TemplateResponse(
        "scans/index.html",
        {
            "request": request,
            "scans": scans,
        },
    )

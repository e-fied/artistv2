"""Scan history routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.scan import ScanRun
from app.services.debug_capture import has_scan_debug, read_scan_debug

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
    debug_scan_ids = {scan.id for scan in scans if has_scan_debug(scan.id)}
    has_running = any(scan.status == "running" for scan in scans)

    return request.app.state.templates.TemplateResponse(request=request, name="scans/index.html", context={
            "request": request,
            "scans": scans,
            "debug_scan_ids": debug_scan_ids,
            "has_running": has_running,
        },
    )


@router.get("/{scan_run_id}/debug")
def scan_debug_page(scan_run_id: int, request: Request, db: Session = Depends(get_db)):
    """Show captured debug artifact for a scan run."""
    scan = (
        db.query(ScanRun)
        .options(joinedload(ScanRun.artist), joinedload(ScanRun.source_results))
        .filter(ScanRun.id == scan_run_id)
        .first()
    )
    if not scan:
        return RedirectResponse(url="/scans", status_code=303)

    debug_data = read_scan_debug(scan_run_id)

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="scans/debug.html",
        context={
            "request": request,
            "scan": scan,
            "debug_data": debug_data,
        },
    )

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
def scans_page(
    request: Request,
    db: Session = Depends(get_db),
    status: str = "",
    trigger: str = "",
    page: int = 1,
):
    """Show a paginated operational history with diagnostics on demand."""
    allowed_statuses = {"running", "completed", "failed"}
    allowed_triggers = {"scheduled", "manual_single", "manual_all"}
    status = status if status in allowed_statuses else ""
    trigger = trigger if trigger in allowed_triggers else ""
    page = max(page, 1)
    per_page = 25

    query = db.query(ScanRun).options(
        joinedload(ScanRun.artist), joinedload(ScanRun.source_results)
    )
    if status:
        query = query.filter(ScanRun.status == status)
    if trigger:
        query = query.filter(ScanRun.trigger == trigger)

    total_scans = query.count()
    scans = (
        query.order_by(ScanRun.started_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    debug_scan_ids = {scan.id for scan in scans if has_scan_debug(scan.id)}
    has_running = (
        db.query(ScanRun.id).filter(ScanRun.status == "running").first() is not None
    )
    page_count = max(1, (total_scans + per_page - 1) // per_page)

    def page_url(target_page: int) -> str:
        params = [f"page={target_page}"]
        if status:
            params.append(f"status={status}")
        if trigger:
            params.append(f"trigger={trigger}")
        return f"/scans/?{'&'.join(params)}"

    return request.app.state.templates.TemplateResponse(request=request, name="scans/index.html", context={
            "request": request,
            "scans": scans,
            "debug_scan_ids": debug_scan_ids,
            "has_running": has_running,
            "filter_status": status,
            "filter_trigger": trigger,
            "total_scans": total_scans,
            "page": page,
            "page_count": page_count,
            "previous_url": page_url(page - 1) if page > 1 else None,
            "next_url": page_url(page + 1) if page < page_count else None,
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
        return RedirectResponse(url="/scans/", status_code=303)

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

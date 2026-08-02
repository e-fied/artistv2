"""Cost and resource reporting routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import load_settings
from app.database import get_db
from app.services.cost_reporting import build_cost_report

router = APIRouter(prefix="/costs")


@router.get("/")
def costs_page(request: Request, db: Session = Depends(get_db)):
    """Show actual recorded Gemini usage and deterministic bypasses."""
    settings = load_settings()
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="costs/index.html",
        context={
            "request": request,
            "report": build_cost_report(db),
            "settings": settings,
            "primary_extractor_model": (
                settings.gemini_extractor_models[0]
                if settings.gemini_extractor_models
                else "not configured"
            ),
        },
    )

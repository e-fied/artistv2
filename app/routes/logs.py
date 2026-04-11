"""Application logs viewer route."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.config import LOG_DIR
from app.database import get_db

router = APIRouter(prefix="/logs")

@router.get("/")
def logs_page(request: Request):
    """Render the log viewer page."""
    return request.app.state.templates.TemplateResponse(
        request=request, name="logs/index.html", context={"request": request}
    )

@router.get("/tail")
def tail_logs(lines: int = 100):
    """Return the last N lines of the application log."""
    log_file = LOG_DIR / "app.log"
    if not log_file.exists():
        return JSONResponse({"logs": "No log file found yet."})
    
    try:
        # Simple tail implementation
        with open(log_file, "r") as f:
            all_lines = f.readlines()
            tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return JSONResponse({"logs": "".join(tail)})
    except Exception as e:
        return JSONResponse({"logs": f"Error reading logs: {e}"})

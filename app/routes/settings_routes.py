"""Settings page routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import load_settings, save_settings, AppSettings
from app.database import get_db

router = APIRouter(prefix="/settings")


@router.get("/")
def settings_page(request: Request, db: Session = Depends(get_db)):
    """Render the settings page."""
    settings = load_settings()

    # Pre-compute secret field display data for the template
    secret_fields_data = []
    for field_name in ["ticketmaster_api_key", "gemini_api_key", "firecrawl_api_key", "telegram_bot_token", "telegram_chat_id"]:
        raw_value = getattr(settings, field_name, None) or ""
        secret_fields_data.append({
            "name": field_name,
            "label": field_name.replace("_", " ").title(),
            "has_value": bool(raw_value),
            "raw_value": raw_value,
            "redacted": settings.redacted(field_name) or "Not set",
        })

    return request.app.state.templates.TemplateResponse(
        "settings/index.html",
        {
            "request": request,
            "settings": settings,
            "secret_fields_data": secret_fields_data,
        },
    )


@router.post("/")
def update_settings(
    request: Request,
    scan_interval_hours: int = Form(6),
    timezone: str = Form("America/Vancouver"),
    notify_confirmed: bool = Form(False),
    notify_review_summary: bool = Form(False),
    daily_digest_enabled: bool = Form(False),
    daily_digest_time: str = Form("21:00"),
    crawl4ai_base_url: str = Form("http://crawl4ai:11235"),
):
    """Update non-secret settings."""
    settings = load_settings()

    settings.scan_interval_hours = scan_interval_hours
    settings.timezone = timezone
    settings.notify_confirmed = notify_confirmed
    settings.notify_review_summary = notify_review_summary
    settings.daily_digest_enabled = daily_digest_enabled
    settings.daily_digest_time = daily_digest_time
    settings.crawl4ai_base_url = crawl4ai_base_url

    save_settings(settings)
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/test-telegram")
def test_telegram(request: Request):
    """Send a test Telegram message."""
    settings = load_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return RedirectResponse(url="/settings?error=telegram_not_configured", status_code=303)

    import httpx

    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={
                "chat_id": settings.telegram_chat_id,
                "text": "✅ Test message from Tour Tracker v2",
                "parse_mode": "HTML",
            },
            timeout=15.0,
        )
        if response.status_code == 200 and response.json().get("ok"):
            return RedirectResponse(url="/settings?success=telegram_sent", status_code=303)
        else:
            return RedirectResponse(url="/settings?error=telegram_failed", status_code=303)
    except Exception:
        return RedirectResponse(url="/settings?error=telegram_failed", status_code=303)

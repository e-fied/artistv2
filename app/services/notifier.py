"""Telegram notification service."""

from __future__ import annotations

import logging
from html import escape
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def send_telegram(
    bot_token: str,
    chat_id: str,
    message: str,
    parse_mode: str = "HTML",
) -> bool:
    """Send a Telegram message. Returns True on success."""
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=15.0,
        )
        if response.status_code == 200 and response.json().get("ok"):
            logger.info("Telegram message sent successfully")
            return True
        else:
            logger.error(f"Telegram send failed: {response.status_code} — {response.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def format_event_notification(
    artist_name: str,
    event_name: str,
    venue: str,
    city: str,
    region: Optional[str],
    event_date: Optional[str],
    ticket_url: Optional[str],
    match_reason: Optional[str],
    source_type: str,
) -> str:
    """Format a confirmed event as an HTML Telegram message."""
    lines = [
        f"🎤 <b>{artist_name}</b>",
        "",
        f"📌 <b>{event_name}</b>",
        f"🏛 {venue}",
        f"📍 {city}{', ' + region if region else ''}",
    ]

    if event_date:
        lines.append(f"📅 {event_date}")

    if match_reason:
        lines.append(f"🔗 Match: {match_reason}")

    lines.append(f"📡 Source: {source_type}")

    if ticket_url:
        lines.append(f"")
        lines.append(f'🎟 <a href="{ticket_url}">Buy Tickets</a>')

    return "\n".join(lines)


def format_review_summary(
    possible_count: int,
    artist_summaries: list,
) -> str:
    """Format a summary of possible events needing review."""
    lines = [
        f"🔍 <b>Review Summary</b>",
        f"",
        f"{possible_count} possible event{'s' if possible_count != 1 else ''} need review:",
        "",
    ]

    for summary in artist_summaries[:10]:
        lines.append(
            f"• <b>{summary['artist']}</b>: {summary['count']} event{'s' if summary['count'] != 1 else ''}"
        )

    lines.append("")
    lines.append("Open the Review Inbox to confirm or reject.")

    return "\n".join(lines)


def format_source_health_alert(
    artist_name: str,
    source_type: str,
    source_url: Optional[str],
    problem: str,
    consecutive_failures: int,
) -> str:
    """Format a source health warning as an HTML Telegram message."""
    lines = [
        "⚠️ <b>Source Health Problem</b>",
        "",
        f"🎤 <b>{escape(artist_name)}</b>",
        f"📡 Source: {escape(source_type)}",
    ]

    if source_url:
        lines.append(f"🔗 {escape(source_url)}")

    lines.extend(
        [
            f"🔁 Notices: {consecutive_failures}",
            "",
            f"<pre>{escape(problem[:1500])}</pre>",
            "",
            "Open Source Health or the latest Scan Debug page to inspect the crawl output.",
        ]
    )

    return "\n".join(lines)

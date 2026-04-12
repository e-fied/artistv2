"""Scanner service — orchestrates the full scan workflow.

1. For each active artist:
   a. Query Ticketmaster (if attraction_id or keyword)
   b. Match events against location profiles
   c. Deduplicate and persist
   d. Notify on new confirmed events
2. Record ScanRun + ScanSourceResult history
"""

from __future__ import annotations

import logging
import time as time_module
from datetime import datetime, date, time
from typing import Optional, List

from sqlalchemy.orm import Session

from app.config import load_settings
from app.database import SessionLocal
from app.models.artist import Artist, ArtistSource
from app.models.event import Event
from app.models.scan import ScanRun, ScanSourceResult
from app.services.dedup import upsert_event
from app.services.location_matcher import (
    MatchResult,
    get_profiles_for_artist,
    match_event_to_locations,
)
from app.services.notifier import (
    format_event_notification,
    format_review_summary,
    send_telegram,
)
from app.services.ticketmaster import TicketmasterClient
from app.services.debug_capture import append_source_debug, init_scan_debug

logger = logging.getLogger(__name__)


def scan_all_artists() -> None:
    """Scan all active (non-paused) artists. Called by the scheduler."""
    db = SessionLocal()
    try:
        settings = load_settings()
        artists = db.query(Artist).filter(Artist.is_paused == False).all()

        if not artists:
            logger.info("No active artists to scan")
            return

        # Create scan run record
        scan_run = ScanRun(
            trigger="scheduled",
            status="running",
        )
        db.add(scan_run)
        db.commit()
        init_scan_debug(scan_run.id, settings.debug_scan_capture, settings.debug_scan_retention)

        total_found = 0
        total_confirmed = 0
        total_possible = 0
        errors = []

        for artist in artists:
            try:
                _set_scan_progress(db, scan_run.id, f"Scanning {artist.name}")
                found, confirmed, possible = _scan_single_artist(
                    db, artist, scan_run.id, settings
                )
                total_found += found
                total_confirmed += confirmed
                total_possible += possible
            except Exception as e:
                logger.error(f"Error scanning {artist.name}: {e}")
                errors.append(f"{artist.name}: {str(e)[:100]}")

        # Finalize scan run
        scan_run.status = "completed" if not errors else "completed"
        scan_run.events_found = total_found
        scan_run.new_confirmed = total_confirmed
        scan_run.new_possible = total_possible
        scan_run.completed_at = datetime.utcnow()
        if errors:
            scan_run.error_summary = "; ".join(errors[:5])
        else:
            scan_run.error_summary = None
        db.commit()

        logger.info(
            f"Scan complete: {total_found} events, {total_confirmed} confirmed, {total_possible} possible"
        )

        # Send review summary if we have possible events
        if total_possible > 0 and settings.notify_review_summary:
            _send_review_summary(db, settings, total_possible)

    except Exception as e:
        logger.error(f"Scan all failed: {e}")
    finally:
        db.close()


def scan_single_artist_manual(artist_id: int) -> dict:
    """Manually trigger a scan for a single artist. Returns a summary dict."""
    db = SessionLocal()
    try:
        settings = load_settings()
        artist = db.query(Artist).filter(Artist.id == artist_id).first()
        if not artist:
            return {"error": "Artist not found"}

        scan_run = ScanRun(
            artist_id=artist_id,
            trigger="manual_single",
            status="running",
        )
        db.add(scan_run)
        db.commit()
        init_scan_debug(scan_run.id, settings.debug_scan_capture, settings.debug_scan_retention)

        try:
            _set_scan_progress(db, scan_run.id, f"Scanning {artist.name}")
            found, confirmed, possible = _scan_single_artist(
                db, artist, scan_run.id, settings
            )
            scan_run.status = "completed"
            scan_run.events_found = found
            scan_run.new_confirmed = confirmed
            scan_run.new_possible = possible
            scan_run.error_summary = None
        except Exception as e:
            scan_run.status = "failed"
            scan_run.error_summary = str(e)[:500]
            logger.error(f"Manual scan of {artist.name} failed: {e}")

        scan_run.completed_at = datetime.utcnow()
        db.commit()

        return {
            "artist": artist.name,
            "events_found": scan_run.events_found,
            "new_confirmed": scan_run.new_confirmed,
            "new_possible": scan_run.new_possible,
            "status": scan_run.status,
        }
    finally:
        db.close()


# ── Internal ─────────────────────────────────────────────────────────

def _set_scan_progress(db: Session, scan_run_id: int, message: str) -> None:
    """Persist a lightweight progress note for the scan history page."""
    scan_run = db.get(ScanRun, scan_run_id)
    if not scan_run or scan_run.status != "running":
        return

    scan_run.error_summary = message[:500]
    db.commit()


def _scan_single_artist(
    db: Session,
    artist: Artist,
    scan_run_id: int,
    settings,
) -> tuple:  # (found, new_confirmed, new_possible)
    """Scan a single artist across all their sources.
    
    Returns (total_found, new_confirmed, new_possible).
    """
    found_total = 0
    new_confirmed = 0
    new_possible = 0

    # Get applicable location profiles
    profiles = get_profiles_for_artist(db, artist.id)

    # ── Ticketmaster ──
    tm_source = (
        db.query(ArtistSource)
        .filter(
            ArtistSource.artist_id == artist.id,
            ArtistSource.source_type == "ticketmaster",
        )
        .first()
    )

    if tm_source and settings.ticketmaster_api_key:
        _set_scan_progress(db, scan_run_id, f"{artist.name}: checking Ticketmaster")
        start_time = time_module.time()
        source_result = ScanSourceResult(
            scan_run_id=scan_run_id,
            artist_source_id=tm_source.id,
            source_type="ticketmaster",
            fetch_mode_used="ticketmaster",
        )

        try:
            client = TicketmasterClient(settings.ticketmaster_api_key)
            events = []

            if artist.ticketmaster_attraction_id:
                # Precise search by attraction ID
                for profile in profiles:
                    latlong = f"{profile.latitude},{profile.longitude}"
                    profile_events = client.search_events_by_attraction(
                        attraction_id=artist.ticketmaster_attraction_id,
                        latlong=latlong,
                        radius=profile.radius_km,
                        country_code=profile.country_code,
                    )
                    events.extend(profile_events)
            else:
                # Fallback: keyword search
                for profile in profiles:
                    latlong = f"{profile.latitude},{profile.longitude}"
                    profile_events = client.search_events_by_keyword(
                        keyword=artist.name,
                        latlong=latlong,
                        radius=profile.radius_km,
                        country_code=profile.country_code,
                    )
                    events.extend(profile_events)

            client.close()

            # Deduplicate within this batch (same TM event ID)
            seen_tm_ids = set()
            unique_events = []
            for ev in events:
                tm_id = ev.get("ticketmaster_event_id", "")
                if tm_id and tm_id in seen_tm_ids:
                    continue
                seen_tm_ids.add(tm_id)
                unique_events.append(ev)

            # Process each event
            processed_events = []
            for ev in unique_events:
                result = _process_event(
                    db, artist, ev, profiles, source_type="ticketmaster"
                )
                processed_events.append({**ev, "process_result": result})
                found_total += 1
                if result == "confirmed":
                    new_confirmed += 1
                elif result == "possible":
                    new_possible += 1

            _set_scan_progress(
                db,
                scan_run_id,
                f"{artist.name}: Ticketmaster returned {len(unique_events)} candidate events",
            )

            source_result.fetch_success = True
            source_result.events_extracted = len(unique_events)
            tm_source.last_success_at = datetime.utcnow()
            tm_source.consecutive_failures = 0
            tm_source.last_error = None
            append_source_debug(
                scan_run_id,
                settings.debug_scan_capture,
                {
                    "artist": artist.name,
                    "source_type": "ticketmaster",
                    "mode": "ticketmaster",
                    "profiles": [
                        {
                            "name": profile.name,
                            "latlong": f"{profile.latitude},{profile.longitude}",
                            "radius_km": profile.radius_km,
                            "country_code": profile.country_code,
                        }
                        for profile in profiles
                    ],
                    "search": {
                        "attraction_id": artist.ticketmaster_attraction_id,
                        "keyword_fallback": None if artist.ticketmaster_attraction_id else artist.name,
                    },
                    "events_returned": len(unique_events),
                    "events": processed_events,
                },
            )

        except Exception as e:
            source_result.fetch_success = False
            source_result.fetch_error = str(e)[:500]
            tm_source.consecutive_failures += 1
            tm_source.last_error = str(e)[:500]
            logger.error(f"Ticketmaster scan for {artist.name} failed: {e}")
            append_source_debug(
                scan_run_id,
                settings.debug_scan_capture,
                {
                    "artist": artist.name,
                    "source_type": "ticketmaster",
                    "mode": "ticketmaster",
                    "error": str(e),
                },
            )

        source_result.fetch_duration_seconds = time_module.time() - start_time
        tm_source.last_checked_at = datetime.utcnow()
        db.add(source_result)

    # ── Web Sources ──
    from app.services.crawler import CrawlerService, hash_content
    from app.services.extractor import ExtractorService

    web_sources = (
        db.query(ArtistSource)
        .filter(
            ArtistSource.artist_id == artist.id,
            ArtistSource.source_type.in_(["official_website", "manual_url"]),
        )
        .all()
    )

    if web_sources:
        crawler = CrawlerService(settings)
        extractor = ExtractorService(settings)

        for w_source in web_sources:
            if not w_source.url:
                continue

            start_time = time_module.time()
            source_result = ScanSourceResult(
                scan_run_id=scan_run_id,
                artist_source_id=w_source.id,
                source_type=w_source.source_type,
            )

            try:
                _set_scan_progress(db, scan_run_id, f"{artist.name}: crawling {w_source.url}")
                markdown, crawler_used = crawler.fetch_markdown(
                    url=w_source.url, preferred_crawler=w_source.preferred_crawler
                )
                
                if markdown:
                    source_result.fetch_success = True
                    source_result.fetch_mode_used = crawler_used
                    
                    cleaned_md = crawler.clean_markdown(markdown)
                    current_hash = hash_content(cleaned_md)
                    
                    # Optional enhancement: Skip extraction if content hash hasn't changed since last successful scan
                    # if w_source.last_content_hash == current_hash: ...
                    
                    _set_scan_progress(
                        db,
                        scan_run_id,
                        f"{artist.name}: sending {len(cleaned_md)} cleaned chars to Gemini",
                    )
                    extraction = extractor.extract_events(cleaned_md, artist.name)
                    processed_events = []
                    if extraction is not None:
                        source_result.events_extracted = len(extraction.events)
                        _set_scan_progress(
                            db,
                            scan_run_id,
                            f"{artist.name}: Gemini extracted {source_result.events_extracted} web events",
                        )
                        
                        for ev in extraction.events:
                            # Map properties
                            event_data = {
                                "event_name": ev.event_name,
                                "venue": ev.venue,
                                "city": ev.city,
                                "region": ev.region,
                                "country": ev.country,
                                "date": ev.date,
                                "time": ev.time,
                                "ticket_url": ev.ticket_url,
                                "source_url": w_source.url,
                                "evidence_text": ev.evidence_text
                            }
                            
                            result = _process_event(
                                db, artist, event_data, profiles, source_type=w_source.source_type
                            )
                            processed_events.append({
                                **event_data,
                                "confidence": ev.confidence.value if hasattr(ev.confidence, "value") else ev.confidence,
                                "process_result": result,
                            })
                            found_total += 1
                            if result == "confirmed":
                                new_confirmed += 1
                            elif result == "possible":
                                new_possible += 1

                        w_source.content_hash = current_hash
                        diagnostic = crawler.diagnose_event_content(
                            w_source.url, cleaned_md, len(extraction.events)
                        )
                        if diagnostic:
                            source_result.fetch_error = diagnostic
                            w_source.consecutive_failures += 1
                            w_source.last_error = diagnostic
                            logger.warning(
                                f"No events extracted for {w_source.url}: {diagnostic}"
                            )
                        else:
                            w_source.last_success_at = datetime.utcnow()
                            w_source.consecutive_failures = 0
                            w_source.last_error = None
                    else:
                        diagnostic = crawler.diagnose_event_content(
                            w_source.url, cleaned_md, 0
                        )
                        source_result.fetch_error = diagnostic or "Gemini extraction failed"
                        w_source.last_error = source_result.fetch_error
                        logger.warning(f"Extracted no events or LLM failed for {w_source.url}: {source_result.fetch_error}")
                        w_source.consecutive_failures += 1

                    append_source_debug(
                        scan_run_id,
                        settings.debug_scan_capture,
                        {
                            "artist": artist.name,
                            "source_type": w_source.source_type,
                            "url": w_source.url,
                            "crawler_used": crawler_used,
                            "markdown_chars": len(markdown),
                            "cleaned_markdown_chars": len(cleaned_md),
                            "cleaned_markdown_sample": cleaned_md[:5000],
                            "llm": extractor.last_debug,
                            "events_extracted": source_result.events_extracted,
                            "events": processed_events,
                            "diagnostic": source_result.fetch_error,
                        },
                    )
                else:
                    source_result.fetch_success = False
                    source_result.fetch_error = "Crawler failed to fetch markdown"
                    w_source.consecutive_failures += 1
                    w_source.last_error = source_result.fetch_error
                    append_source_debug(
                        scan_run_id,
                        settings.debug_scan_capture,
                        {
                            "artist": artist.name,
                            "source_type": w_source.source_type,
                            "url": w_source.url,
                            "error": source_result.fetch_error,
                        },
                    )

            except Exception as e:
                source_result.fetch_success = False
                source_result.fetch_error = str(e)[:500]
                w_source.consecutive_failures += 1
                w_source.last_error = str(e)[:500]
                logger.error(f"Web scan for {w_source.url} failed: {e}")
                append_source_debug(
                    scan_run_id,
                    settings.debug_scan_capture,
                    {
                        "artist": artist.name,
                        "source_type": w_source.source_type,
                        "url": w_source.url,
                        "error": str(e),
                    },
                )

            source_result.fetch_duration_seconds = time_module.time() - start_time
            w_source.last_checked_at = datetime.utcnow()
            db.add(source_result)

    db.commit()
    return (found_total, new_confirmed, new_possible)


def _process_event(
    db: Session,
    artist: Artist,
    event_data: dict,
    profiles: list,
    source_type: str,
) -> str:
    """Process a single discovered event: match, dedup, persist.
    
    Returns the status string: 'confirmed', 'possible', 'existing', or 'no_match'.
    """
    city = event_data.get("city", "")
    region = event_data.get("region", "")
    country = event_data.get("country", "")
    venue_lat = event_data.get("venue_lat")
    venue_lon = event_data.get("venue_lon")

    # Match against location profiles
    match = match_event_to_locations(
        event_city=city,
        event_region=region,
        event_country=country,
        event_lat=venue_lat,
        event_lon=venue_lon,
        profiles=profiles,
    )

    if not match or not match.matched:
        # Event is outside all tracked locations — skip
        return "no_match"

    # Determine status based on source and confidence
    if source_type == "ticketmaster" and match.confidence >= 0.8:
        status = "confirmed"
        confidence = match.confidence
    elif match.confidence >= 0.9:
        status = "confirmed"
        confidence = match.confidence
    else:
        status = "possible"
        confidence = match.confidence

    # Parse date/time
    event_date_parsed = None
    event_time_parsed = None
    if event_data.get("date") and event_data["date"] != "TBD":
        try:
            event_date_parsed = date.fromisoformat(event_data["date"])
        except ValueError:
            pass
    if event_data.get("time"):
        try:
            event_time_parsed = time.fromisoformat(event_data["time"])
        except ValueError:
            pass

    # Upsert
    event, is_new = upsert_event(
        db=db,
        artist_id=artist.id,
        event_name=event_data.get("event_name", ""),
        venue=event_data.get("venue", ""),
        city=city,
        region=region,
        country=country,
        event_date=event_date_parsed,
        event_time=event_time_parsed,
        ticket_url=event_data.get("ticket_url"),
        source_url=event_data.get("source_url"),
        source_type=source_type,
        ticketmaster_event_id=event_data.get("ticketmaster_event_id"),
        status=status,
        confidence_score=confidence,
        match_reason=match.reason,
        evidence_text=event_data.get("evidence_text"),
        matched_location_profile_id=match.profile.id if match.profile else None,
    )

    if is_new and status == "confirmed":
        _notify_confirmed(event, artist)
        return "confirmed"
    elif is_new and status == "possible":
        return "possible"
    else:
        return "existing"


def _notify_confirmed(event: Event, artist: Artist) -> None:
    """Send a Telegram notification for a confirmed event."""
    settings = load_settings()
    if not settings.notify_confirmed:
        return
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return

    message = format_event_notification(
        artist_name=artist.name,
        event_name=event.event_name,
        venue=event.venue,
        city=event.city,
        region=event.region,
        event_date=event.event_date.isoformat() if event.event_date else None,
        ticket_url=event.ticket_url,
        match_reason=event.match_reason,
        source_type=event.source_type,
    )

    if send_telegram(settings.telegram_bot_token, settings.telegram_chat_id, message):
        # Mark as notified in the database
        db = SessionLocal()
        try:
            evt = db.query(Event).filter(Event.id == event.id).first()
            if evt:
                evt.notified = True
                db.commit()
        finally:
            db.close()


def _send_review_summary(db: Session, settings, total_possible: int) -> None:
    """Send a summary of possible events needing review."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return

    from sqlalchemy import func

    # Get per-artist counts
    summaries = (
        db.query(Artist.name, func.count(Event.id))
        .join(Event, Event.artist_id == Artist.id)
        .filter(Event.status == "possible")
        .group_by(Artist.name)
        .all()
    )

    artist_summaries = [
        {"artist": name, "count": count}
        for name, count in summaries
    ]

    message = format_review_summary(total_possible, artist_summaries)
    send_telegram(settings.telegram_bot_token, settings.telegram_chat_id, message)

"""Opt-in scan debug artifact storage."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Optional

from app.config import DEBUG_DIR


MAX_TEXT_CHARS = 120_000


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value)


def _scrub(value: Any) -> Any:
    """Keep debug JSON useful while preventing giant accidental blobs."""
    if isinstance(value, str):
        return value[:MAX_TEXT_CHARS]
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, dict):
        scrubbed = {}
        for key, item in value.items():
            if key.lower() in {"apikey", "api_key", "key"}:
                scrubbed[key] = "REDACTED"
            else:
                scrubbed[key] = _scrub(item)
        return scrubbed
    return value


def artifact_path(scan_run_id: int) -> Path:
    return DEBUG_DIR / f"scan_{scan_run_id}.json"


def init_scan_debug(scan_run_id: int, enabled: bool, retention: int) -> None:
    if not enabled:
        return

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "scan_run_id": scan_run_id,
        "created_at": datetime.utcnow().isoformat(),
        "sources": [],
    }
    artifact_path(scan_run_id).write_text(json.dumps(data, indent=2, default=_json_default))
    prune_debug_artifacts(retention)


def append_source_debug(scan_run_id: int, enabled: bool, payload: dict) -> None:
    if not enabled:
        return

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = artifact_path(scan_run_id)
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except Exception:
            data = {"scan_run_id": scan_run_id, "created_at": datetime.utcnow().isoformat(), "sources": []}
    else:
        data = {"scan_run_id": scan_run_id, "created_at": datetime.utcnow().isoformat(), "sources": []}

    data.setdefault("sources", []).append(_scrub(payload))
    path.write_text(json.dumps(data, indent=2, default=_json_default))


def read_scan_debug(scan_run_id: int) -> Optional[dict]:
    path = artifact_path(scan_run_id)
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def has_scan_debug(scan_run_id: int) -> bool:
    return artifact_path(scan_run_id).exists()


def prune_debug_artifacts(retention: int) -> None:
    if retention <= 0 or not DEBUG_DIR.exists():
        return

    artifacts = sorted(
        DEBUG_DIR.glob("scan_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in artifacts[retention:]:
        path.unlink(missing_ok=True)

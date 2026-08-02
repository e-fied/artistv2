"""Central log redaction for credentials embedded in third-party request URLs."""

from __future__ import annotations

import logging
import re


_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:apikey|api_key|access_token|token|key)=)[^&\s\"']+"
)
_BEARER_RE = re.compile(r"(?i)(authorization[=:]\s*bearer\s+)[^\s,;]+")
_TELEGRAM_BOT_RE = re.compile(r"(?i)(/bot)[^/\s]+(/sendMessage)")


def redact_log_message(message: str) -> str:
    """Remove common URL/header credential forms from one rendered message."""
    redacted = _QUERY_SECRET_RE.sub(r"\1REDACTED", message)
    redacted = _BEARER_RE.sub(r"\1REDACTED", redacted)
    return _TELEGRAM_BOT_RE.sub(r"\1REDACTED\2", redacted)


class SensitiveDataFilter(logging.Filter):
    """Render and redact a log record before any handler persists it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_log_message(record.getMessage())
        record.args = ()
        return True

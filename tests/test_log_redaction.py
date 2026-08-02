from __future__ import annotations

import logging

from app.services.log_redaction import SensitiveDataFilter, redact_log_message


def test_redacts_query_keys_bearer_tokens_and_telegram_bot_urls():
    message = (
        "GET https://example.test/events?apikey=secret-123&size=10 "
        "Authorization=Bearer bearer-secret "
        "POST https://api.telegram.org/bot123456:ABC-secret/sendMessage"
    )

    redacted = redact_log_message(message)

    assert "secret-123" not in redacted
    assert "bearer-secret" not in redacted
    assert "123456:ABC-secret" not in redacted
    assert "apikey=REDACTED" in redacted
    assert "/botREDACTED/sendMessage" in redacted


def test_logging_filter_redacts_formatted_arguments():
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Request %s",
        args=("https://example.test/?api_key=do-not-log",),
        exc_info=None,
    )

    assert SensitiveDataFilter().filter(record) is True
    assert "do-not-log" not in record.getMessage()
    assert record.args == ()

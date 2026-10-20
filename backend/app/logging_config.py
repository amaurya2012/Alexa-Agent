"""Logging setup: request-id correlation plus best-effort secret redaction."""
from __future__ import annotations

import logging
import re
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_REDACTIONS = [
    (re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer [REDACTED]"),
    (
        re.compile(r"(?i)\b(secret|token|password|api[_-]?key|authorization|session[_-]?token)\b(\s*[=:]\s*)\S+"),
        r"\1\2[REDACTED]",
    ),
]


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class SafeFilter(logging.Filter):
    """Adds request_id to every record and redacts secrets from the message."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:  # never let logging break the app
            pass
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(SafeFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Keep third-party chatter (and anything that might echo headers) quiet.
    for noisy in ("botocore", "boto3", "urllib3", "httpx", "httpcore", "httpx2", "httpcore2", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

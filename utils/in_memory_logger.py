from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from typing import Deque, Dict, Any, List


class InMemoryLogHandler(logging.Handler):
    """Simple in-memory log handler that keeps the last *capacity* records.
    Each record is stored as a plain dict that is JSON-serialisable so that
    it can be returned directly from FastAPI endpoints.
    """

    def __init__(self, capacity: int = 1000) -> None:  # noqa: D401
        super().__init__()
        # We keep only the *last* ``capacity`` entries.
        self.capacity = capacity
        self.logs: Deque[Dict[str, Any]] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            # ``record.created`` is a POSIX timestamp (float). We convert it to ISO-8601.
            timestamp = datetime.utcfromtimestamp(record.created).isoformat()
            log_entry: Dict[str, Any] = {
                "timestamp": timestamp,
                "level": record.levelname.lower(),
                "message": record.getMessage(),
                "logger": record.name,
            }
            self.logs.append(log_entry)
        except Exception:  # pragma: no cover – best-effort
            # We must **never** raise from ``emit``.
            self.handleError(record)

    def get_logs(self, limit: int | None = None) -> List[Dict[str, Any]]:  # noqa: D401
        """Return at most *limit* most recent log entries (newest first)."""
        if limit is None or limit <= 0:
            return list(self.logs)
        return list(self.logs)[-limit:]


# ---------------------------------------------------------------------------
# Initialisation – attach the handler to the *root* logger so that it also
# picks up log messages coming from *structlog* (when it is configured with
# the stdlib logger factory) and standard ``logging``.
# ---------------------------------------------------------------------------

_LOG_HANDLER = InMemoryLogHandler()
_root_logger = logging.getLogger()  # This is the *root* logger.
_root_logger.setLevel(logging.INFO)
_root_logger.addHandler(_LOG_HANDLER)

# Export a lightweight accessor so that other modules can fetch logs without
# having to know about the underlying handler instance.


def get_recent_logs(limit: int = 100) -> List[Dict[str, Any]]:  # noqa: D401
    """Helper to obtain the most recent *limit* log entries."""
    return _LOG_HANDLER.get_logs(limit)

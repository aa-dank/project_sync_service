"""
Shared utilities: logging setup with run correlation ID, structured sync summary.
"""
from __future__ import annotations

import logging
import sys
import uuid
from typing import Any


# Module-level run correlation ID — set once per CLI invocation via setup_logging().
_run_id: str | None = None


def get_run_id() -> str:
    global _run_id
    if _run_id is None:
        _run_id = str(uuid.uuid4())
    return _run_id


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with structured formatting including the run correlation ID."""
    global _run_id
    _run_id = str(uuid.uuid4())

    log_level = getattr(logging, level.upper(), logging.INFO)
    run_id = _run_id

    class RunIdFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            record.run_id = run_id
            return True

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [run=%(run_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(RunIdFilter())

    root = logging.getLogger()
    root.setLevel(log_level)
    # Avoid duplicate handlers if setup_logging is called multiple times
    if root.handlers:
        root.handlers.clear()
    root.addHandler(handler)


def make_sync_summary(
    entity: str,
    added: int,
    updated: int,
    removed: int,
    errors: int = 0,
    error_details: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "entity": entity,
        "added": added,
        "updated": updated,
        "removed": removed,
        "errors": errors,
        "error_details": error_details or [],
    }

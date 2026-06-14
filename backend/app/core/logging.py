"""Structured, container-friendly logging.

Logs are emitted as single-line JSON to ``stdout`` so the Docker logging driver
(and downstream collectors such as Loki/CloudWatch) can ingest them without a
multi-line parser. Call :func:`configure_logging` once at application start-up;
modules obtain a logger via :func:`get_logger`.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any


class JsonLogFormatter(logging.Formatter):
    """Render log records as compact JSON objects."""

    # Attributes that are always present on a LogRecord; everything else the
    # caller attached via ``extra=`` is treated as a structured field.
    _RESERVED = frozenset(
        logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
    ) | {"message", "asctime", "taskName"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: int | str = logging.INFO) -> None:
    """Configure root logging to emit JSON to stdout (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers on re-import / reload (common under uvicorn).
    for handler in list(root.handlers):
        if getattr(handler, "_targetgraph_json", False):
            return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    handler._targetgraph_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger."""
    return logging.getLogger(name)

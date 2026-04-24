"""Minimal structured-ish logging; INFO = minimal, DEBUG = verbose."""

import json
import logging
import sys
from typing import Any


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "extra_fields"):
            payload.update(record.extra_fields)  # type: ignore[attr-defined]
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def log_extra(logger: logging.Logger, level: int, msg: str, **fields: Any) -> None:
    record = logger.makeRecord(
        logger.name, level, "", 0, msg, (), None, func=None, extra=None, sinfo=None
    )
    setattr(record, "extra_fields", fields)
    logger.handle(record)

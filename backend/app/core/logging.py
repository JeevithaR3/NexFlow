"""Structured logging (key=value text, or JSON when NEXFLOW_LOG_JSON=true)."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class _KVFormatter(logging.Formatter):
    def __init__(self, as_json: bool) -> None:
        super().__init__()
        self.as_json = as_json

    def format(self, record: logging.LogRecord) -> str:
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
        base = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **extras,
        }
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)  # server log only
        if self.as_json:
            return json.dumps(base, default=str)
        tail = " ".join(f"{k}={v}" for k, v in extras.items())
        line = f"{base['ts']} {base['level']:<7} {base['logger']}: {base['msg']} {tail}".rstrip()
        if "exc" in base:
            line += "\n" + base["exc"]
        return line


def configure_logging(level: str = "INFO", as_json: bool = False) -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_KVFormatter(as_json))
    root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"nexflow.{name}")

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str | None = None, json_output: bool = False) -> None:
    lvl = getattr(logging, (level or "INFO").upper(), logging.INFO)
    root = logging.getLogger()
    # Clear existing handlers (avoid duplicates)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stdout)
    if json_output:
        fmt = JsonFormatter()
    else:
        fmt = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    handler.setFormatter(fmt)
    root.addHandler(handler)
    root.setLevel(lvl)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

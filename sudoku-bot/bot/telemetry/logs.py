"""Journalisation : console lisible + fichier JSON lignes (rotation) + tampon pour le dashboard."""
from __future__ import annotations

import collections
import json
import logging
import logging.handlers
import sys
import time
from pathlib import Path
from typing import Callable


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "data", None)
        if isinstance(extra, dict):
            data["data"] = extra
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    COLORS = {"DEBUG": "\033[90m", "INFO": "\033[0m", "WARNING": "\033[33m", "ERROR": "\033[31m", "CRITICAL": "\033[41m"}

    def format(self, record: logging.LogRecord) -> str:
        t = time.strftime("%H:%M:%S", time.localtime(record.created))
        color = self.COLORS.get(record.levelname, "") if sys.stderr.isatty() else ""
        reset = "\033[0m" if color else ""
        base = f"{t} {record.levelname[:4]:<4} {record.name:<14} {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return f"{color}{base}{reset}"


class SinkHandler(logging.Handler):
    """Garde les derniers logs en mémoire et les pousse vers un callback (lien dashboard)."""

    def __init__(self, capacity: int = 500) -> None:
        super().__init__()
        self.buffer: collections.deque[dict] = collections.deque(maxlen=capacity)
        self.callback: Callable[[dict], None] | None = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            item = {"ts": round(record.created, 3), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
            self.buffer.append(item)
            if self.callback:
                self.callback(item)
        except Exception:  # un handler de log ne doit jamais faire planter l'appelant
            self.handleError(record)


def setup_logging(level: str, json_path: Path, max_mb: int) -> SinkHandler:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(ConsoleFormatter())
    root.addHandler(console)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(json_path, maxBytes=max_mb * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(JsonFormatter())
    root.addHandler(fh)
    sink = SinkHandler()
    root.addHandler(sink)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    return sink

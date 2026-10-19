"""Persistance JSON atomique (écriture dans un fichier temporaire puis `os.replace`)."""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("bot.state")


class JsonStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def load(self, default: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else dict(default or {})
        except FileNotFoundError:
            return dict(default or {})
        except (json.JSONDecodeError, OSError) as exc:
            # Fichier corrompu (coupure pendant une écriture non atomique d'un autre outil) :
            # on le met de côté au lieu de planter.
            log.error("état illisible %s (%s) : sauvegardé en .corrupt", self.path, exc)
            try:
                os.replace(self.path, self.path.with_suffix(".corrupt"))
            except OSError:
                pass
            return dict(default or {})

    def save(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)

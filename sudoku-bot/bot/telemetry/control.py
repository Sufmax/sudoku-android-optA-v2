"""Boîte de commandes locale (fichiers JSON) : permet `./run.sh ready` même sans dashboard."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path

log = logging.getLogger("bot.control")

ALLOWED_ACTIONS = {"ready", "pause", "resume", "set_speed", "stop", "snapshot"}


def write_command(inbox: Path, action: str, **params: object) -> Path:
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"action inconnue : {action}")
    inbox.mkdir(parents=True, exist_ok=True)
    cmd = {"id": uuid.uuid4().hex[:12], "action": action, "params": params, "ts": time.time(), "source": "cli"}
    tmp = inbox / f".{cmd['id']}.tmp"
    tmp.write_text(json.dumps(cmd), encoding="utf-8")
    final = inbox / f"{time.time_ns():020d}_{cmd['id']}.json"
    os.replace(tmp, final)
    return final


def drain(inbox: Path) -> list[dict]:
    """Lit puis supprime les commandes en attente, dans l'ordre d'arrivée."""
    if not inbox.exists():
        return []
    out: list[dict] = []
    for f in sorted(inbox.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("action") in ALLOWED_ACTIONS:
                out.append(data)
            else:
                log.warning("commande ignorée (invalide) : %s", f.name)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("commande illisible %s : %s", f.name, exc)
        finally:
            try:
                f.unlink()
            except OSError:
                pass
    return out

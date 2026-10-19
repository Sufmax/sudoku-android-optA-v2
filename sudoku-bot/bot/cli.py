"""Commandes locales : `python -m bot.cli ready|pause|resume|stop|snapshot|speed <mode>|status`."""
from __future__ import annotations

import json
import sys
import time

from bot.config import ROOT
from bot.telemetry.control import write_command

VAR = ROOT / "var"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "status":
        p = VAR / "state" / "status.json"
        if not p.exists():
            print("aucun statut (bot jamais lancé ?)")
            return 1
        st = json.loads(p.read_text(encoding="utf-8"))
        age = time.time() - st.get("updated", 0)
        print(f"état={st['state']} écran={st.get('screen')} pause={st['paused']} prêt={st['ready']} vitesse={st['speed']['label']} (màj il y a {age:.0f}s)")
        s = st.get("stats", {})
        print(f"parties: {s.get('games_won', 0)} réussies / {s.get('games_started', 0)} commencées · chiffres: {s.get('digits_placed', 0)} · moyenne {s.get('avg_game_s', 0)}s")
        return 0
    if cmd == "speed":
        if len(argv) < 2:
            print("usage : speed <adaptive|very_slow|slow|medium|fast|very_fast>")
            return 2
        write_command(VAR / "control" / "inbox", "set_speed", mode=argv[1])
    elif cmd in ("ready", "pause", "resume", "stop", "snapshot"):
        write_command(VAR / "control" / "inbox", cmd)
    else:
        print(f"commande inconnue : {cmd}")
        return 2
    print(f"commande « {cmd} » transmise au bot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
# =============================================================================
#  Superviseur (keepalive) — équivalent de la boucle de fin de start_services.sh
#  du dépôt android_emulator : toutes les 30 s, relance Xvfb / x11vnc / noVNC
#  s'ils sont morts, et l'émulateur s'il a disparu (crash, OOM, réveil après
#  hibernation). Lancé en arrière-plan par run.sh, arrêté par teardown.
#    bash scripts/supervisor.sh start|stop|status|loop
# =============================================================================
set -uo pipefail
source "$(dirname "$0")/lib.sh"
load_env
PIDF="$VAR/state/pids/supervisor.pid"; mkdir -p "$VAR/state/pids"
INTERVAL="${SUPERVISOR_INTERVAL_S:-30}"

loop() {
  local B S
  while true; do
    sleep "$INTERVAL"
    [[ -f "$VAR/state/supervisor.paused" ]] && continue
    bash "$ROOT/scripts/remote_view.sh" ensure >>"$VAR/logs/supervisor.log" 2>&1 || true
    B="$(backend)"; S="$(serial_for "$B")"
    [[ "$B" == "avd" ]] || continue
    if ! pgrep -f "qemu-system.*-avd $(avd_name)( |$)" >/dev/null 2>&1 && ! pgrep -f "emulator.*-avd $(avd_name)( |$)" >/dev/null 2>&1; then
      # Pas d'émulateur : on attend qu'un éventuel démarrage en cours libère le verrou, sinon on relance.
      echo "$(date -Is) émulateur absent → relance" >>"$VAR/logs/supervisor.log"
      bash "$ROOT/scripts/start_emulator.sh" >>"$VAR/logs/supervisor.log" 2>&1 || true
    elif [[ "$(adb_state "$S")" == "offline" ]]; then
      adbt reconnect offline >/dev/null 2>&1 || true
    fi
  done
}

case "${1:-start}" in
  start)
    if [[ -f "$PIDF" ]] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then ok "superviseur déjà actif"; exit 0; fi
    nohup bash "$0" loop >>"$VAR/logs/supervisor.log" 2>&1 8>&- 9>&- &
    echo $! > "$PIDF"; ok "superviseur actif (Xvfb/x11vnc/noVNC/émulateur relancés si besoin)" ;;
  stop)
    [[ -f "$PIDF" ]] && kill "$(cat "$PIDF")" 2>/dev/null; rm -f "$PIDF"; ok "superviseur arrêté" ;;
  status)
    if [[ -f "$PIDF" ]] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then echo "superviseur : actif"; else echo "superviseur : arrêté"; fi ;;
  loop) loop ;;
  *) die "usage : supervisor.sh start|stop|status|loop" ;;
esac

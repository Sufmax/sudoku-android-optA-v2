#!/usr/bin/env bash
# =============================================================================
#  Pile d'affichage distante — recette du dépôt android_emulator :
#    Xvfb :1 (écran virtuel)  →  x11vnc :5900 (-noshm !)  →  websockify/noVNC :6080
#  L'émulateur est lancé SANS -no-window et dessine sur cet écran ; noVNC le
#  rend accessible depuis le navigateur (phase de configuration manuelle).
#
#    bash scripts/remote_view.sh start|ensure|stop|status|url
#  `ensure` relance uniquement les composants morts (utilisé par le superviseur).
# =============================================================================
set -uo pipefail
source "$(dirname "$0")/lib.sh"
load_env

DISP="$(display_num)"; DNUM="${DISP#:}"
SCREEN="$(cfg display xvfb_screen 1920x1080x24)"
VNC="$(vnc_port)"; WEB="$(novnc_port)"
PIDS="$VAR/state/pids"; mkdir -p "$PIDS"

alive() { local f="$PIDS/$1.pid"; [[ -f "$f" ]] && kill -0 "$(cat "$f")" 2>/dev/null; }

novnc_web_dir() {
  local d
  for d in /usr/share/novnc /usr/share/webapps/novnc "$VAR/novnc"; do [[ -f "$d/vnc_lite.html" ]] && { echo "$d"; return 0; }; done
  return 1
}

start_xvfb() {
  if alive xvfb && [[ -S "/tmp/.X11-unix/X${DNUM}" ]]; then return 0; fi
  has Xvfb || { warn "Xvfb absent (utilise le devcontainer ou ./run.sh pour installer les paquets)"; return 1; }
  # Écran orphelin (processus tué brutalement) : on nettoie verrou et socket.
  pkill -f "Xvfb ${DISP} " 2>/dev/null || true
  rm -f "/tmp/.X${DNUM}-lock" "/tmp/.X11-unix/X${DNUM}" 2>/dev/null || true
  mkdir -p /tmp/.X11-unix 2>/dev/null || true
  nohup Xvfb "$DISP" -screen 0 "$SCREEN" -ac +extension GLX +render -noreset >"$VAR/logs/xvfb.log" 2>&1 8>&- 9>&- &
  echo $! > "$PIDS/xvfb.pid"
  local i; for i in $(seq 1 20); do [[ -S "/tmp/.X11-unix/X${DNUM}" ]] && break; sleep 0.5; done
  if alive xvfb; then ok "Xvfb ${DISP} (${SCREEN})"; else tail -n 20 "$VAR/logs/xvfb.log" >&2; warn "Xvfb n'a pas démarré"; return 1; fi
}

start_x11vnc() {
  if pgrep -f "x11vnc -display ${DISP} " >/dev/null 2>&1; then return 0; fi
  has x11vnc || { warn "x11vnc absent"; return 1; }
  local auth=(-nopw)
  if [[ "$(cfg display vnc_password true)" == "true" && -n "${DASHBOARD_PASSWORD:-}" ]]; then
    x11vnc -storepasswd "${DASHBOARD_PASSWORD:0:8}" "$VAR/state/vncpass" >/dev/null 2>&1 && auth=(-rfbauth "$VAR/state/vncpass")
  else
    warn "noVNC SANS mot de passe (définis DASHBOARD_PASSWORD dans .env pour le protéger)"
  fi
  # -noshm : indispensable dans les conteneurs CodeSandbox (erreur MIT-SHM sinon)
  x11vnc -display "$DISP" "${auth[@]}" -forever -shared -localhost -rfbport "$VNC" \
    -nossl -noshm -quiet -bg -o "$VAR/logs/x11vnc.log" >/dev/null 2>&1 8>&- 9>&- || true
  sleep 1
  if pgrep -f "x11vnc -display ${DISP} " >/dev/null 2>&1; then ok "x11vnc (port ${VNC}, local)"; else tail -n 20 "$VAR/logs/x11vnc.log" >&2; warn "x11vnc n'a pas démarré"; return 1; fi
}

start_novnc() {
  if alive websockify; then return 0; fi
  has websockify || { warn "websockify absent"; return 1; }
  local web; web="$(novnc_web_dir)" || { warn "noVNC (vnc_lite.html) introuvable"; return 1; }
  pkill -f "websockify.*${WEB}" 2>/dev/null || true
  nohup websockify --web="$web" --heartbeat=30 "0.0.0.0:${WEB}" "localhost:${VNC}" >"$VAR/logs/novnc.log" 2>&1 8>&- 9>&- &
  echo $! > "$PIDS/websockify.pid"
  sleep 1
  if alive websockify; then ok "noVNC (port ${WEB})"; else tail -n 20 "$VAR/logs/novnc.log" >&2; warn "websockify n'a pas démarré"; return 1; fi
}

stop_all() {
  local p
  for p in websockify xvfb; do [[ -f "$PIDS/$p.pid" ]] && kill "$(cat "$PIDS/$p.pid")" 2>/dev/null; rm -f "$PIDS/$p.pid"; done
  pkill -f "x11vnc -display ${DISP} " 2>/dev/null || true
  pkill -f "websockify.*${WEB}" 2>/dev/null || true
  ok "affichage distant arrêté"
}

case "${1:-start}" in
  start|ensure)
    start_xvfb || exit 1
    start_x11vnc || true
    start_novnc || true
    if [[ "${1:-start}" == "start" ]]; then
      echo "   ${c_bold}Écran Android :${c_off} $(novnc_url)"
      [[ -f "$VAR/state/vncpass" ]] && echo "   mot de passe VNC : les 8 premiers caractères de DASHBOARD_PASSWORD"
    fi
    ;;
  stop) stop_all ;;
  status)
    for p in xvfb websockify; do alive "$p" && echo "$p : actif" || echo "$p : arrêté"; done
    pgrep -f "x11vnc -display ${DISP} " >/dev/null && echo "x11vnc : actif" || echo "x11vnc : arrêté"
    ;;
  url) novnc_url ;;
  *) die "usage : remote_view.sh start|ensure|stop|status|url" ;;
esac
exit 0

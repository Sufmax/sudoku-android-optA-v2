#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════
#  SUDOKU BOT — point d'entrée UNIQUE et idempotent
#    ./run.sh               premier lancement OU relancement (détection auto)
#    ./run.sh ready         signale « PRÊT » (équivalent du bouton du dashboard)
#    ./run.sh pause|resume|stop|status|snapshot
#    ./run.sh speed <adaptive|very_slow|slow|medium|fast|very_fast>
#    ./run.sh screen        affiche l'URL de l'écran Android (noVNC)
#    ./run.sh emulator <start|stop|restart>
#    ./run.sh doctor        état complet (diagnostic, affichage, émulateur, bot)
#    ./run.sh diagnose | teardown [--purge] | logs | test
# ════════════════════════════════════════════════════════════════════════════
set -Eeuo pipefail
cd "$(dirname "$0")"
source scripts/lib.sh
load_env
PY="$ROOT/.venv/bin/python"

venv_ok() {
  local stamp="$ROOT/.venv/.req.sha" want
  want="$(sha1sum requirements.txt | cut -d' ' -f1)"
  [[ -x "$PY" && "$(cat "$stamp" 2>/dev/null)" == "$want" ]]
}

ensure_venv() {
  local stamp="$ROOT/.venv/.req.sha" want
  want="$(sha1sum requirements.txt | cut -d' ' -f1)"
  if venv_ok; then return 0; fi
  if [[ ! -x "$PY" ]]; then python3 -m venv "$ROOT/.venv" || { rm -rf "$ROOT/.venv"; return 1; }; fi
  "$PY" -m pip install -q --upgrade pip && "$PY" -m pip install -q -r requirements.txt && echo "$want" > "$stamp"
}

need_py() { [[ -x "$PY" ]] || die "environnement Python absent : lance d'abord ./run.sh"; }

doctor() {
  bash scripts/diagnose.sh || true
  echo "${c_bold}── Affichage distant ──────────────────────────────────────${c_off}"
  bash scripts/remote_view.sh status | sed 's/^/  /'
  echo "  URL : $(novnc_url)"
  echo "${c_bold}── Émulateur ──────────────────────────────────────────────${c_off}"
  bash scripts/supervisor.sh status | sed 's/^/  /'
  echo "  AVD : $(avd_name) · image : $(system_image) · accel : $(accel_mode)"
  [[ -f "$VAR/state/emulator.json" ]] && echo "  état : $(cat "$VAR/state/emulator.json")"
  adb devices 2>/dev/null | sed 's/^/  /' || true
  echo "${c_bold}── Bot ────────────────────────────────────────────────────${c_off}"
  if [[ -x "$PY" ]]; then "$PY" -m bot.cli status 2>/dev/null | sed 's/^/  /' || echo "  bot jamais lancé"; else echo "  venv absent"; fi
}

cmd="${1:-start}"
case "$cmd" in
  ready|pause|resume|stop|status|snapshot|speed) need_py; exec "$PY" -m bot.cli "$@" ;;
  diagnose) exec bash scripts/diagnose.sh ;;
  doctor) doctor; exit 0 ;;
  screen) echo "$(novnc_url)"; exit 0 ;;
  emulator)
    case "${2:-start}" in
      start) exec bash scripts/start_emulator.sh ;;
      stop) bash scripts/supervisor.sh stop; exec bash scripts/start_emulator.sh --stop ;;
      restart) exec bash scripts/start_emulator.sh --restart ;;
      *) die "usage : ./run.sh emulator start|stop|restart" ;;
    esac ;;
  teardown) shift; exec bash scripts/teardown.sh "$@" ;;
  logs) touch "$VAR/logs/bot.jsonl"; exec tail -n 100 -f "$VAR/logs/bot.jsonl" ;;
  test) ensure_venv || die "installation des dépendances Python échouée"; exec "$PY" -m pytest -q tests ;;
  start) ;;
  *) die "commande inconnue : $cmd (voir l'en-tête de run.sh)" ;;
esac

exec 9>"$VAR/state/run.lock"
flock -n 9 || die "une instance de run.sh tourne déjà (./run.sh doctor pour l'état, ./run.sh ready pour PRÊT)"

[[ -f .env ]] || warn ".env absent : copie .env.example en .env (mot de passe du dashboard / noVNC, URL du Worker)"
bash scripts/diagnose.sh
if [[ -n "${ANDROID_BACKEND:-}" && "${ANDROID_BACKEND}" != "auto" ]]; then echo "$ANDROID_BACKEND" > "$VAR/backend"; fi
B="$(backend)"

is_first() {
  if [[ "$B" == "avd" ]]; then
    [[ ! -f "$VAR/.setup_avd_$(variant)" || ! -f "$ANDROID_AVD_HOME/$(avd_name).ini" ]]
  else
    [[ ! -f "$VAR/.setup_${B}" ]]
  fi
}
FIRST=0; is_first && FIRST=1
# « Premier lancement » au sens utilisateur = aucun boot réussi n'a encore eu lieu (compte Google à connecter).
NEVER_BOOTED=1; [[ -f "$VAR/state/booted_$(variant)" ]] && NEVER_BOOTED=0

echo
if (( FIRST )); then
  info "${c_bold}PREMIER LANCEMENT${c_off} — backend ${B} ($(variant)) : installation"
  bash scripts/setup_emulator.sh "$B"
else
  info "${c_bold}RELANCEMENT${c_off} — backend ${B} ($(variant)) : réveil sans réinstallation"
fi

# Dépendances Python en arrière-plan pendant le boot d'Android (plusieurs minutes sans KVM).
VENV_LOG="$VAR/logs/pip.log"
if venv_ok; then VENV_PID=""; ok "environnement Python prêt"
else info "dépendances Python : installation en arrière-plan (var/logs/pip.log)"; ( ensure_venv >"$VENV_LOG" 2>&1 ) 9>&- & VENV_PID=$!; fi

start_device() {
  local rc=0
  bash scripts/start_emulator.sh || rc=$?
  if (( rc == 3 )) && [[ "$B" == "avd" && "$(variant)" == "playstore" && -z "${IMAGE_VARIANT:-}" \
        && "$(cfg emulator image_fallback true)" == "true" && ! -f "$VAR/state/booted_playstore" ]]; then
    warn "l'image Google Play n'a pas terminé son premier boot dans le délai imparti."
    warn "bascule automatique sur la recette d'origine : image « default » + Aurora Store (client Play Store)."
    bash scripts/start_emulator.sh --stop || true
    echo "aurora" > "$VAR/state/image_variant"
    bash scripts/setup_emulator.sh avd
    rc=0; bash scripts/start_emulator.sh || rc=$?
  fi
  return $rc
}

if ! start_device; then
  warn "l'appareil Android n'est pas prêt. L'écran reste accessible pour diagnostic : $(novnc_url)"
  die "voir var/logs/emulator.log · ./run.sh doctor · ./run.sh emulator restart"
fi

if [[ "$B" == "avd" && "$(variant)" == "aurora" ]]; then
  bash scripts/bootstrap_apps.sh || warn "Aurora Store non installé automatiquement (réessaie : bash scripts/bootstrap_apps.sh)"
fi
[[ "$B" == "avd" ]] && bash scripts/supervisor.sh start

if [[ -n "${VENV_PID:-}" ]]; then
  info "finalisation des dépendances Python…"
  wait "$VENV_PID" || { tail -n 30 "$VENV_LOG" >&2; die "installation des dépendances Python échouée (var/logs/pip.log)"; }
  ok "environnement Python prêt"
fi

STORE="Play Store"; [[ "$(variant)" == "aurora" ]] && STORE="Aurora Store (connexion anonyme ou compte Google)"
echo
echo "${c_bold}════════ CONFIGURATION MANUELLE ════════${c_off}"
echo "  Écran Android : ${c_bold}$(novnc_url)${c_off}"
[[ -f "$VAR/state/vncpass" ]] && echo "  (mot de passe VNC : 8 premiers caractères de DASHBOARD_PASSWORD)"
echo "  ou : dashboard › section « Écran » (contrôle tactile intégré)"
if (( NEVER_BOOTED )); then
  echo "  1. Connecte ton compte Google, installe le Sudoku depuis ${STORE}"
  echo "  2. Ouvre le jeu et règle ce dont tu as besoin"
else
  echo "  1. Ouvre le jeu depuis l'écran distant et ajuste tes réglages"
fi
echo "  → puis appuie sur ${c_bold}PRÊT${c_off} dans le dashboard, ou lance :  ${c_bold}./run.sh ready${c_off}"
echo

trap 'echo; warn "interruption : le bot sauvegarde son état (relance : ./run.sh) — l’émulateur continue de tourner"' INT TERM
"$PY" -m bot.main

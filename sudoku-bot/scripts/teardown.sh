#!/usr/bin/env bash
# =============================================================================
#  Arrêt propre : bot, superviseur, émulateur (snapshot Quick Boot si activé),
#  affichage distant.
#    --purge [--yes] : supprime aussi l'AVD (compte Google, jeu), le SDK local
#                      éventuel et les données du bot (irréversible).
#  Le SDK préinstallé dans l'image Docker (/opt/android-sdk) n'est jamais supprimé.
# =============================================================================
set -uo pipefail
source "$(dirname "$0")/lib.sh"
load_env
B="$(backend)"; S="$(serial_for "$B")"

info "arrêt du bot…"
(cd "$ROOT" && "$ROOT/.venv/bin/python" -m bot.cli stop >/dev/null 2>&1) || true
for _ in $(seq 1 20); do pgrep -f "bot.main" >/dev/null || break; sleep 0.5; done
pkill -f "bot.main" 2>/dev/null || true

bash "$ROOT/scripts/supervisor.sh" stop >/dev/null 2>&1 || true
bash "$ROOT/scripts/start_emulator.sh" --stop || true
[[ "$B" == "remote" ]] && adb disconnect "$S" >/dev/null 2>&1 || true
bash "$ROOT/scripts/remote_view.sh" stop >/dev/null 2>&1 || true

if [[ "${1:-}" == "--purge" ]]; then
  if [[ "${2:-}" != "--yes" ]]; then
    read -r -p "Supprimer définitivement l'AVD (compte Google, jeu), le SDK local et les données ? [tape OUI] " a
    [[ "$a" == "OUI" ]] || exit 0
  fi
  docker rm -f sudoku-redroid >/dev/null 2>&1 || true
  rm -rf "$ANDROID_DIR" "$VAR/redroid-data" "$VAR"/.setup_* "$VAR/backend" "$VAR/state/booted_"* "$VAR/state/image_variant" "$VAR/apks"
  ok "purge effectuée"
fi
ok "tout est arrêté (relance : ./run.sh)"

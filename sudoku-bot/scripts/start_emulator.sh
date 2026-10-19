#!/usr/bin/env bash
# =============================================================================
#  Démarrage / réveil du backend Android. Idempotent.
#    bash scripts/start_emulator.sh            démarre si nécessaire, attend le boot
#    bash scripts/start_emulator.sh --restart  arrêt propre puis redémarrage (bot, dernier recours)
#    bash scripts/start_emulator.sh --stop     arrêt propre (snapshot Quick Boot si activé)
#
#  Codes de sortie : 0 = appareil prêt · 1 = erreur · 3 = boot non terminé (timeout
#  ou crash de l'émulateur) → run.sh peut basculer sur l'image « aurora ».
#
#  Commande émulateur = recette éprouvée du dépôt android_emulator :
#    DISPLAY=:1 emulator -avd … -no-boot-anim -no-audio -gpu swiftshader_indirect
#      -accel off -no-snapshot-save -no-metrics -memory 4096 -cores 3 -port 5554
#      -dns-server 8.8.8.8,8.8.4.4
#  (SANS -no-window : l'écran Xvfb est capturé par x11vnc → noVNC)
# =============================================================================
set -Eeuo pipefail
source "$(dirname "$0")/lib.sh"
load_env
B="$(backend)"; S="$(serial_for "$B")"
PIDF="$VAR/state/pids/emulator.pid"; mkdir -p "$VAR/state/pids"
MODE="start"
case "${1:-}" in --restart) MODE="restart" ;; --stop) MODE="stop" ;; "") ;; *) die "option inconnue : $1" ;; esac

# Un seul démarrage à la fois (run.sh, superviseur et bot peuvent tous l'appeler).
exec 8>"$VAR/state/emulator.lock"
if ! flock -w "$(( $(cfg emulator boot_timeout_s 1500) + 120 ))" 8; then die "verrou émulateur indisponible"; fi

emu_pid_alive() { [[ -f "$PIDF" ]] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }

qemu_pids() {  # processus qemu de CET AVD (y compris lancés hors de ce script)
  pgrep -f "qemu-system.*-avd $(avd_name)( |$)" 2>/dev/null || true
  pgrep -f "emulator.*-avd $(avd_name)( |$)" 2>/dev/null || true
}

stop_avd() {
  local name; name="$(avd_name)"
  if [[ -z "$(qemu_pids)" ]] && ! emu_pid_alive; then rm -f "$PIDF"; return 0; fi
  info "arrêt de l'émulateur ${name}…"
  write_emulator_state stopping
  adbt -s "$S" emu kill >/dev/null 2>&1 || true
  local i
  for i in $(seq 1 60); do [[ -z "$(qemu_pids)" ]] && break; sleep 2; done   # jusqu'à 2 min (sauvegarde Quick Boot)
  if [[ -n "$(qemu_pids)" ]]; then
    warn "arrêt propre trop long : SIGTERM puis SIGKILL"
    # shellcheck disable=SC2046
    kill $(qemu_pids) 2>/dev/null || true; sleep 5
    # shellcheck disable=SC2046
    kill -9 $(qemu_pids) 2>/dev/null || true
  fi
  rm -f "$PIDF"
  clean_locks
  write_emulator_state stopped
  ok "émulateur arrêté"
}

clean_locks() {  # verrous laissés par un arrêt brutal (hibernation, kill -9) → « AVD already running »
  local d; d="$(avd_dir)"
  [[ -n "$(qemu_pids)" ]] && return 0
  rm -f "$d"/*.lock "$d"/hardware-qemu.ini.lock "$d"/multiinstance.lock "$d"/snapshot.lock.lock 2>/dev/null || true
  find "$d" -maxdepth 1 -name '*.lock' -type d -exec rm -rf {} + 2>/dev/null || true
}

explain_crash() {
  local log="$VAR/logs/emulator.log"
  tail -n 25 "$log" >&2 || true
  if grep -qiE "requires hardware acceleration|x86_64 emulation currently requires" "$log" 2>/dev/null; then
    warn "cette version de l'émulateur refuse l'ABI x86_64 sans KVM → mets « abi: x86 » dans config.yaml puis ./run.sh"
  elif grep -qiE "another emulator instance|running multiple emulators with the same AVD" "$log" 2>/dev/null; then
    warn "verrou d'AVD orphelin : relance ./run.sh (les verrous sont nettoyés au démarrage)"
  elif grep -qiE "cannot open display|could not connect to display|qt.qpa.xcb" "$log" 2>/dev/null; then
    warn "écran Xvfb indisponible : bash scripts/remote_view.sh start"
  elif grep -qiE "not enough space|no space left" "$log" 2>/dev/null; then
    warn "disque plein : libère de l'espace (./run.sh teardown, purge des captures var/failures)"
  fi
}

start_avd() {
  local name timeout; name="$(avd_name)"; timeout="$(cfg emulator boot_timeout_s 1500)"
  adb start-server >/dev/null 2>&1 8>&- 9>&- || true

  if booted "$S"; then
    ok "émulateur déjà en marche ($S)"
    bash "$ROOT/scripts/remote_view.sh" ensure >/dev/null 2>&1 8>&- 9>&- || true
    return 0
  fi

  if emu_pid_alive || [[ -n "$(qemu_pids)" ]]; then
    info "émulateur ${name} déjà lancé mais Android pas encore prêt : attente du boot"
    write_emulator_state booting "boot en cours"
    local rc=0; wait_boot "$S" "$timeout" "$(cat "$PIDF" 2>/dev/null || true)" || rc=$?
    (( rc == 0 )) && return 0
    write_emulator_state failed "boot non terminé"; explain_crash; exit 3
  fi

  if [[ ! -f "$ANDROID_AVD_HOME/${name}.ini" || ! -f "$(avd_dir)/config.ini" ]]; then
    warn "AVD ${name} absent : création"
    bash "$ROOT/scripts/setup_emulator.sh" avd 8>&- 9>&-
  fi

  ensure_host_dns
  bash "$ROOT/scripts/remote_view.sh" start 8>&- 9>&- || die "affichage virtuel (Xvfb) indisponible : l'émulateur ne peut pas dessiner sa fenêtre"
  export DISPLAY; DISPLAY="$(display_num)"
  clean_locks

  local accel; accel="$(accel_mode)"
  local args=(
    -avd "$name"
    -port "$(console_port)"
    -no-boot-anim
    -no-audio
    -gpu "$(cfg emulator gpu swiftshader_indirect)"
    -accel "$accel"
    -no-metrics
    -memory "$(cfg emulator ram_mb 4096)"
    -cores "$(cfg emulator cores 3)"
    -dns-server "$(cfg emulator dns_servers 8.8.8.8,8.8.4.4)"
    -netdelay none
    -netspeed full
  )
  if [[ "$(cfg emulator quickboot false)" == "true" ]]; then
    local snap; snap="$(cfg emulator checkpoint_snapshot bot_checkpoint)"
    if [[ -d "$(avd_dir)/snapshots/${snap}" ]]; then args+=(-snapshot "$snap"); info "réveil depuis le snapshot « ${snap} »"
    else info "Quick Boot activé (snapshot default_boot s'il existe, sauvegardé à l'arrêt propre)"; fi
  else
    args+=(-no-snapshot-save)
    info "boot à froid (quickboot: false) — données, compte Google et jeu conservés dans l'AVD"
  fi

  if [[ "$accel" == "on" ]]; then info "KVM disponible : accélération matérielle"
  else info "pas de KVM : émulation logicielle (-accel off) — boot de 3 à 20 min selon l'image"; fi

  write_emulator_state starting "lancement"
  {
    echo "=== $(date -Is) emulator ${args[*]}"
  } >>"$VAR/logs/emulator.log"
  # 8>&- 9>&- : l'émulateur ne doit PAS hériter des verrous (emulator.lock / run.lock), sinon
  # ils resteraient tenus tant qu'il tourne et bloqueraient --stop/--restart et ./run.sh.
  nohup env DISPLAY="$DISPLAY" LIBGL_ALWAYS_SOFTWARE=1 "$ANDROID_SDK_ROOT/emulator/emulator" "${args[@]}" >>"$VAR/logs/emulator.log" 2>&1 8>&- 9>&- &
  echo $! > "$PIDF"
  ok "émulateur lancé (PID $(cat "$PIDF"), série $S)"
  echo "   ${c_bold}Suivre le boot en direct :${c_off} $(novnc_url)"
  sleep 6
  if ! emu_pid_alive; then
    write_emulator_state failed "arrêt immédiat"
    explain_crash
    exit 3
  fi

  write_emulator_state booting "boot en cours"
  local rc=0; wait_boot "$S" "$timeout" "$(cat "$PIDF")" || rc=$?
  if (( rc != 0 )); then
    write_emulator_state failed "boot non terminé après ${timeout}s"
    explain_crash
    exit 3
  fi
  date +%s > "$VAR/state/booted_$(variant)"
}

start_redroid() {
  local image; image="$(cfg emulator redroid_image redroid/redroid:13.0.0_gapps)"
  if docker ps --format '{{.Names}}' | grep -qx sudoku-redroid; then
    [[ "$MODE" == "restart" ]] && docker restart sudoku-redroid >/dev/null
  elif docker ps -a --format '{{.Names}}' | grep -qx sudoku-redroid; then
    docker start sudoku-redroid >/dev/null
  else
    mkdir -p "$VAR/redroid-data"
    docker run -d --privileged --name sudoku-redroid --restart unless-stopped -v "$VAR/redroid-data:/data" -p 5555:5555 "$image" \
      androidboot.redroid_width="$(cfg emulator width 1080)" androidboot.redroid_height="$(cfg emulator height 2340)" \
      androidboot.redroid_dpi="$(cfg emulator density 420)" androidboot.redroid_gpu_mode=guest >/dev/null
  fi
  sleep 5; adbt connect "$S" >/dev/null || true
  wait_boot "$S" 300 || die "redroid ne démarre pas (docker logs sudoku-redroid)"
}

start_remote() {
  adb start-server >/dev/null 8>&- 9>&-
  [[ "$S" == *:* ]] && adbt connect "$S" >/dev/null 2>&1 || true
  if ! booted "$S"; then
    warn "appareil distant $S injoignable. Le bot attendra et réessaiera (tunnel ADB actif ?)."
    return 0
  fi
  ok "appareil distant $S connecté"
}

case "$B" in
  avd)
    case "$MODE" in
      stop) stop_avd; exit 0 ;;
      restart) stop_avd; start_avd ;;
      start) start_avd ;;
    esac ;;
  redroid) [[ "$MODE" == "stop" ]] && { docker stop sudoku-redroid >/dev/null 2>&1 || true; exit 0; }; start_redroid ;;
  remote) [[ "$MODE" == "stop" ]] && exit 0; start_remote ;;
  *) die "backend inconnu : $B" ;;
esac

if booted "$S"; then
  tune_device "$S"
  write_emulator_state ready "Android $(adbt -s "$S" shell getprop ro.build.version.release 2>/dev/null | tr -d '\r')"
  ok "appareil prêt ($S)"
fi
exit 0

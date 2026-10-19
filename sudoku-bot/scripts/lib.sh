#!/usr/bin/env bash
# =============================================================================
#  Fonctions communes aux scripts (sourcé, jamais exécuté directement).
#
#  Emplacements :
#   - SDK Android : /opt/android-sdk si l'image du devcontainer l'a préinstallé
#                   (cas normal sur CodeSandbox), sinon var/android/sdk.
#   - AVD         : TOUJOURS dans var/android/avd (workspace persistant) → le
#                   compte Google et le jeu installé survivent aux redémarrages,
#                   à l'hibernation et aux reconstructions du conteneur.
#   - Clés ADB    : laissées à leur emplacement standard ($HOME/.android). Ne PAS
#                   déplacer ANDROID_EMULATOR_HOME / ANDROID_USER_HOME : l'émulateur
#                   injecte $HOME/.android/adbkey.pub dans l'invité à chaque boot, et
#                   adb doit utiliser la même clé (sinon appareil « unauthorized »
#                   sur les images Play Store, qui sont des builds « user »).
# =============================================================================
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VAR="$ROOT/var"
ANDROID_DIR="${ANDROID_DIR:-$VAR/android}"

if [[ -z "${ANDROID_SDK_ROOT:-}" || ! -d "${ANDROID_SDK_ROOT:-/nonexistent}" ]]; then
  if [[ -x /opt/android-sdk/emulator/emulator ]]; then
    ANDROID_SDK_ROOT=/opt/android-sdk
  else
    ANDROID_SDK_ROOT="$ANDROID_DIR/sdk"
  fi
fi
export ANDROID_SDK_ROOT
export ANDROID_HOME="$ANDROID_SDK_ROOT"
export ANDROID_AVD_HOME="$ANDROID_DIR/avd"
unset ANDROID_EMULATOR_HOME ANDROID_USER_HOME
export PATH="$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$PATH"
if [[ -z "${JAVA_HOME:-}" && -d /usr/lib/jvm/java-17-openjdk-amd64 ]]; then export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64; fi
export LIBGL_ALWAYS_SOFTWARE=1
mkdir -p "$VAR/logs" "$VAR/state" "$VAR/control/inbox" "$ANDROID_DIR" "$ANDROID_AVD_HOME" "$HOME/.android"

c_bold=$'\033[1m'; c_red=$'\033[31m'; c_grn=$'\033[32m'; c_ylw=$'\033[33m'; c_cyn=$'\033[36m'; c_off=$'\033[0m'
info()  { echo "${c_bold}▸${c_off} $*"; }
ok()    { echo "${c_grn}✔${c_off} $*"; }
warn()  { echo "${c_ylw}!${c_off} $*" >&2; }
die()   { echo "${c_red}✖ $*${c_off}" >&2; exit 1; }
has()   { command -v "$1" >/dev/null 2>&1; }

load_env() {
  if [[ -f "$ROOT/.env" ]]; then
    set -a; # shellcheck disable=SC1091
    source "$ROOT/.env"; set +a
  fi
}

# Lecture d'une clé simple de config.yaml (section.clé), sans dépendance Python.
cfg() {
  local section="$1" key="$2" default="${3:-}"
  local v
  v="$(awk -v s="$section:" -v k="$key:" '
    $0 ~ "^"s {in_s=1; next}
    in_s && /^[^ #]/ {in_s=0}
    in_s && $1==k {sub(/^[^:]*:[ ]*/, ""); sub(/[ ]+#.*/, ""); gsub(/"/, ""); print; exit}
  ' "$ROOT/config/config.yaml")"
  echo "${v:-$default}"
}

SUDO=""
if [[ "$(id -u)" -ne 0 ]]; then
  if has sudo && sudo -n true 2>/dev/null; then SUDO="sudo"; fi
fi
can_root() { [[ "$(id -u)" -eq 0 || -n "$SUDO" ]]; }

# --------------------------------------------------------------------- backend
# Par défaut : émulateur LOCAL (avd), avec ou sans KVM. « remote » / « redroid »
# restent disponibles mais uniquement sur demande explicite.
backend() {
  local b="${ANDROID_BACKEND:-$(cfg emulator backend auto)}"
  if [[ "$b" == "auto" ]]; then
    if [[ -f "$VAR/backend" ]]; then b="$(cat "$VAR/backend")"; else b="avd"; fi
  fi
  echo "$b"
}

console_port() { cfg emulator console_port 5554; }

serial_for() {
  case "$1" in
    avd) echo "${ADB_SERIAL:-emulator-$(console_port)}" ;;
    *)   echo "${REMOTE_ADB_SERIAL:-$(cfg emulator remote_serial 127.0.0.1:5555)}" ;;
  esac
}

# --------------------------------------------------------------------- image
# Variante effective : IMAGE_VARIANT (.env) > choix mémorisé (après bascule auto) > config.
variant() {
  local v="${IMAGE_VARIANT:-}"
  [[ -z "$v" && -f "$VAR/state/image_variant" ]] && v="$(cat "$VAR/state/image_variant")"
  [[ -z "$v" ]] && v="$(cfg emulator image_variant playstore)"
  case "$v" in playstore|aurora) echo "$v" ;; *) echo "playstore" ;; esac
}
image_tag() { [[ "$(variant)" == "playstore" ]] && echo "google_apis_playstore" || echo "default"; }
api_level() { cfg emulator api_level 29; }
abi()       { cfg emulator abi x86_64; }
system_image() { echo "system-images;android-$(api_level);$(image_tag);$(abi)"; }
avd_name()  { echo "$(cfg emulator avd_name sudoku)_$(variant)"; }
avd_dir()   { echo "$ANDROID_AVD_HOME/$(avd_name).avd"; }

# --------------------------------------------------------------------- accélération
kvm_usable() { [[ -e /dev/kvm && -r /dev/kvm && -w /dev/kvm ]]; }
accel_mode() {   # → "on" (KVM) ou "off" (émulation logicielle TCG)
  local a="${EMULATOR_ACCEL:-$(cfg emulator accel auto)}"
  case "$a" in
    on)  echo on ;;
    off) echo off ;;
    *)   if kvm_usable; then echo on; else echo off; fi ;;
  esac
}

# --------------------------------------------------------------------- affichage
display_num() { cfg display xvfb_display ":1"; }
novnc_port()  { cfg display novnc_port 6080; }
vnc_port()    { cfg display vnc_port 5900; }

# URL publique de noVNC (CodeSandbox expose chaque port en https://<id>-<port>.csb.app)
novnc_url() {
  local port; port="$(novnc_port)"
  local id="${CSB_SANDBOX_ID:-${CODESANDBOX_HOST:-}}"
  if [[ -n "${CSB_SANDBOX_ID:-}" ]]; then
    echo "https://${CSB_SANDBOX_ID}-${port}.csb.app/vnc_lite.html?autoconnect=1&resize=scale"
  elif [[ -n "$id" ]]; then
    echo "https://${id/\$PORT/$port}/vnc_lite.html?autoconnect=1&resize=scale"
  else
    echo "http://localhost:${port}/vnc_lite.html?autoconnect=1&resize=scale  (CodeSandbox : onglet « Ports » › ${port})"
  fi
}

# --------------------------------------------------------------------- état émulateur
# var/state/emulator.json : lu par le bot (et donc affiché dans le dashboard).
write_emulator_state() {   # $1 = état (stopped|starting|booting|ready|failed) [$2 = détail]
  local st="$1" detail="${2:-}"
  local tmp="$VAR/state/.emulator.json.tmp"
  cat > "$tmp" <<JSON
{"state":"$st","detail":"${detail//\"/\'}","backend":"$(backend)","variant":"$(variant)","image":"$(system_image)","avd":"$(avd_name)","accel":"$(accel_mode)","kvm":$(kvm_usable && echo true || echo false),"serial":"$(serial_for "$(backend)")","novnc_url":"$(novnc_url | cut -d' ' -f1)","ts":$(date +%s)}
JSON
  mv -f "$tmp" "$VAR/state/emulator.json"
}

# adb borné dans le temps : juste après le boot, l'invité (sans KVM) est saturé par
# l'optimisation des services Google et un `adb shell` peut bloquer plusieurs minutes.
adbt() { timeout --kill-after=5 "${ADB_CMD_TIMEOUT_S:-25}" adb "$@"; }

adb_state() {   # $1 = serial → device | offline | unauthorized | (vide)
  adbt devices 2>/dev/null | awk -v s="$1" '$1==s {print $2}'
}

booted() {      # $1 = serial
  [[ "$(adb_state "$1")" == "device" ]] && \
  [[ "$(adbt -s "$1" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r\n')" == "1" ]]
}

wait_boot() {   # $1 = serial, $2 = timeout s, $3 = pid à surveiller (optionnel)
  local serial="$1" timeout="${2:-900}" pid="${3:-}" t=0 st=""
  info "attente du démarrage complet d'Android ($serial, max ${timeout}s)…"
  adb start-server >/dev/null 2>&1 8>&- 9>&- || true
  while (( t < timeout )); do
    if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
      echo; warn "le processus de l'émulateur s'est arrêté pendant le boot"; return 2
    fi
    st="$(adb_state "$serial")"
    case "$st" in
      device)
        if [[ "$(adbt -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r\n')" == "1" ]]; then
          echo; ok "Android démarré en ${t}s"; return 0
        fi ;;
      offline) adbt reconnect offline >/dev/null 2>&1 || true ;;
      unauthorized) (( t % 60 == 0 )) && warn "ADB « unauthorized » : clé ADB pas encore acceptée par l'invité" ;;
    esac
    printf '.'
    (( t > 0 && t % 120 == 0 )) && printf ' %ss (adb: %s)\n' "$t" "${st:-absent}"
    sleep 5; t=$((t + 5))
  done
  echo; return 1
}

tune_device() {  # réglages qui fiabilisent la vision (pas d'animations, écran toujours allumé)
  local s="$1"
  adbt -s "$s" shell input keyevent 82 >/dev/null 2>&1 || true            # déverrouillage
  adbt -s "$s" shell settings put global window_animation_scale 0 >/dev/null 2>&1 || true
  adbt -s "$s" shell settings put global transition_animation_scale 0 >/dev/null 2>&1 || true
  adbt -s "$s" shell settings put global animator_duration_scale 0 >/dev/null 2>&1 || true
  adbt -s "$s" shell settings put system screen_off_timeout 2147483647 >/dev/null 2>&1 || true
  adbt -s "$s" shell settings put global stay_on_while_plugged_in 7 >/dev/null 2>&1 || true
  adbt -s "$s" shell svc power stayon true >/dev/null 2>&1 || true
  adbt -s "$s" shell input keyevent 224 >/dev/null 2>&1 || true           # réveil écran
}

# DNS de l'hôte : certains conteneurs CodeSandbox n'ont pas de résolution fonctionnelle
# au démarrage (constaté dans le dépôt d'origine). On ne corrige QUE si nécessaire.
ensure_host_dns() {
  if getent hosts dl.google.com >/dev/null 2>&1; then return 0; fi
  if can_root && [[ -w /etc/resolv.conf || -n "$SUDO" ]]; then
    warn "résolution DNS de l'hôte en échec : écriture de /etc/resolv.conf (8.8.8.8 / 1.1.1.1)"
    cp -f /etc/resolv.conf "$VAR/state/resolv.conf.bak" 2>/dev/null || true
    printf 'nameserver 8.8.8.8\nnameserver 8.8.4.4\nnameserver 1.1.1.1\n' | $SUDO tee /etc/resolv.conf >/dev/null 2>&1 || true
  else
    warn "résolution DNS de l'hôte en échec et /etc/resolv.conf non modifiable"
  fi
}

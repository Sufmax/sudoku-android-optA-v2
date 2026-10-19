#!/usr/bin/env bash
# =============================================================================
#  Installation idempotente : paquets système, SDK Android, image système,
#  création de l'AVD (backend avd) — ou outils minimaux (remote / redroid).
#
#    bash scripts/setup_emulator.sh [avd|redroid|remote]
#
#  Dans le devcontainer CodeSandbox (.devcontainer/Dockerfile), paquets + SDK +
#  images sont déjà présents : seul l'AVD est créé (≈ 10 s). Hors devcontainer,
#  tout est installé (root requis pour apt).
# =============================================================================
set -Eeuo pipefail
source "$(dirname "$0")/lib.sh"
load_env
B="${1:-$(backend)}"
CMDLINE_URL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"

APT_PACKAGES=(
  ca-certificates curl wget unzip git procps psmisc lsof iproute2 util-linux jq dnsutils
  python3 python3-venv python3-pip
  tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng
  openjdk-17-jdk-headless
  xvfb x11vnc novnc websockify
  libgl1-mesa-glx libgl1-mesa-dri mesa-utils libgles2-mesa libglu1-mesa
  libpulse0 libx11-6 libx11-xcb1 libxcb1 libxext6 libxi6 libxrender1 libxtst6
  libnss3 libxcomposite1 libxcursor1 libxdamage1 libxkbfile1 libasound2 libglib2.0-0
)

install_packages() {
  local missing=()
  for c in java Xvfb x11vnc websockify tesseract unzip wget curl flock; do has "$c" || missing+=("$c"); done
  python3 -c "import venv, ensurepip" >/dev/null 2>&1 || missing+=("python3-venv")
  if (( ${#missing[@]} == 0 )); then ok "paquets système déjà présents"; return 0; fi
  if ! can_root; then
    warn "commandes manquantes (${missing[*]}) et pas de droits root : utilise le devcontainer (.devcontainer/)"
    return 0
  fi
  info "paquets système manquants : ${missing[*]} → apt-get…"
  export DEBIAN_FRONTEND=noninteractive
  for i in 1 2 3; do $SUDO apt-get update -qq && break || sleep 10; done
  $SUDO apt-get install -y -qq --no-install-recommends --fix-missing "${APT_PACKAGES[@]}" >/dev/null \
    || die "installation apt échouée (voir ci-dessus)"
  [[ -z "${JAVA_HOME:-}" && -d /usr/lib/jvm/java-17-openjdk-amd64 ]] && export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
  ok "paquets système installés"
}

install_cmdline_tools() {
  if [[ -x "$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" ]]; then return 0; fi
  info "téléchargement des Android cmdline-tools…"
  mkdir -p "$ANDROID_SDK_ROOT/cmdline-tools"
  local tmp; tmp="$(mktemp -d)"
  wget -q -O "$tmp/clt.zip" "$CMDLINE_URL" || die "téléchargement cmdline-tools impossible (réseau/DNS ?)"
  unzip -q "$tmp/clt.zip" -d "$tmp"
  rm -rf "$ANDROID_SDK_ROOT/cmdline-tools/latest"
  mv "$tmp/cmdline-tools" "$ANDROID_SDK_ROOT/cmdline-tools/latest"
  rm -rf "$tmp"
  ok "cmdline-tools installés"
}

sdk() {
  local i
  for i in 1 2 3; do
    # Pas de « yes | sdkmanager » : avec pipefail, le SIGPIPE de `yes` ferait échouer un succès.
    if sdkmanager --sdk_root="$ANDROID_SDK_ROOT" "$@" < <(yes 2>/dev/null) >"$VAR/logs/sdkmanager.log" 2>&1; then return 0; fi
    warn "sdkmanager $* : échec (tentative $i/3), nouvel essai…"; sleep 10
  done
  tail -n 20 "$VAR/logs/sdkmanager.log" >&2
  die "sdkmanager $* a échoué (voir var/logs/sdkmanager.log)"
}

ensure_sdk_writable() {
  if [[ ! -w "$ANDROID_SDK_ROOT" ]]; then
    if [[ -n "$SUDO" ]]; then $SUDO chown -R "$(id -u):$(id -g)" "$ANDROID_SDK_ROOT"
    else die "$ANDROID_SDK_ROOT non modifiable : impossible d'y ajouter des paquets SDK"; fi
  fi
}

install_platform_tools() {
  if [[ -x "$ANDROID_SDK_ROOT/platform-tools/adb" ]]; then ok "platform-tools présents"; return 0; fi
  install_cmdline_tools; ensure_sdk_writable
  info "platform-tools (adb)…"; sdkmanager --sdk_root="$ANDROID_SDK_ROOT" --licenses < <(yes 2>/dev/null) >/dev/null 2>&1 || true
  sdk "platform-tools"; ok "adb prêt"
}

install_emulator_and_image() {
  local img; img="$(system_image)"
  local img_dir="$ANDROID_SDK_ROOT/system-images/android-$(api_level)/$(image_tag)/$(abi)"
  local need=()
  [[ -x "$ANDROID_SDK_ROOT/emulator/emulator" ]] || need+=("emulator")
  [[ -d "$ANDROID_SDK_ROOT/platforms/android-$(api_level)" ]] || need+=("platforms;android-$(api_level)")
  [[ -f "$img_dir/system.img" ]] || need+=("$img")
  if (( ${#need[@]} == 0 )); then ok "émulateur + image $img présents ($ANDROID_SDK_ROOT)"; return 0; fi
  local free; free=$(df -Pk "$ANDROID_SDK_ROOT" | awk 'NR==2 {printf "%d", $4/1024/1024}')
  (( free >= 6 )) || die "espace disque insuffisant (${free} Go libres, ≥ 6 requis pour l'image système)"
  install_cmdline_tools; ensure_sdk_writable
  sdkmanager --sdk_root="$ANDROID_SDK_ROOT" --licenses < <(yes 2>/dev/null) >/dev/null 2>&1 || true
  info "téléchargement : ${need[*]} (≈ 1 à 1,5 Go)…"
  sdk "${need[@]}"
  [[ -f "$img_dir/system.img" ]] || die "image $img introuvable après installation"
  ok "émulateur + image $img installés"
}

set_ini() {  # $1 = fichier, $2 = clé, $3 = valeur
  local ini="$1" k="$2" v="$3"
  if grep -q "^${k}[ ]*=" "$ini" 2>/dev/null; then sed -i "s|^${k}[ ]*=.*|${k}=${v}|" "$ini"; else echo "${k}=${v}" >> "$ini"; fi
}

create_avd() {
  local name dir img
  name="$(avd_name)"; dir="$(avd_dir)"; img="$(system_image)"
  if [[ -f "$ANDROID_AVD_HOME/${name}.ini" && -f "$dir/config.ini" ]]; then
    ok "AVD ${name} déjà créé (non recréé : compte Google et jeu conservés)"
  else
    info "création de l'AVD ${name} ($img, profil $(cfg emulator device_profile pixel_4))…"
    mkdir -p "$ANDROID_AVD_HOME"
    echo "no" | avdmanager create avd --name "$name" --package "$img" \
      --device "$(cfg emulator device_profile pixel_4)" --path "$dir" --force >"$VAR/logs/avdmanager.log" 2>&1 \
      || { tail -n 20 "$VAR/logs/avdmanager.log" >&2; die "avdmanager create avd a échoué"; }
    # Certaines versions d'avdmanager ignorent ANDROID_AVD_HOME pour le fichier .ini : on le garantit.
    if [[ ! -f "$ANDROID_AVD_HOME/${name}.ini" ]]; then
      printf 'avd.ini.encoding=UTF-8\npath=%s\npath.rel=avd/%s.avd\ntarget=android-%s\n' "$dir" "$name" "$(api_level)" > "$ANDROID_AVD_HOME/${name}.ini"
    fi
    rm -f "$HOME/.android/avd/${name}.ini" 2>/dev/null || true
  fi
  # (Ré)application de la configuration matérielle à chaque setup : sans risque pour les données.
  local ini="$dir/config.ini" cold="yes"
  [[ "$(cfg emulator quickboot false)" == "true" ]] && cold="no"
  set_ini "$ini" hw.ramSize "$(cfg emulator ram_mb 4096)"
  set_ini "$ini" vm.heapSize "$(cfg emulator vm_heap_mb 512)"
  set_ini "$ini" hw.cpu.ncore "$(cfg emulator cores 3)"
  set_ini "$ini" disk.dataPartition.size "$(cfg emulator data_partition 6G)"
  set_ini "$ini" hw.lcd.width "$(cfg emulator width 1080)"
  set_ini "$ini" hw.lcd.height "$(cfg emulator height 2340)"
  set_ini "$ini" hw.lcd.density "$(cfg emulator density 420)"
  set_ini "$ini" skin.name "$(cfg emulator width 1080)x$(cfg emulator height 2340)"
  set_ini "$ini" skin.dynamic yes
  set_ini "$ini" showDeviceFrame no
  set_ini "$ini" hw.gpu.enabled yes
  set_ini "$ini" hw.gpu.mode "$(cfg emulator gpu swiftshader_indirect)"
  set_ini "$ini" hw.audioInput no
  set_ini "$ini" hw.audioOutput no
  set_ini "$ini" hw.camera.back none
  set_ini "$ini" hw.camera.front none
  set_ini "$ini" hw.wifi yes
  set_ini "$ini" hw.keyboard yes
  set_ini "$ini" hw.initialOrientation portrait
  set_ini "$ini" fastboot.forceColdBoot "$cold"
  set_ini "$ini" fastboot.forceFastBoot no
  if [[ "$(variant)" == "playstore" ]]; then set_ini "$ini" PlayStore.enabled true; else set_ini "$ini" PlayStore.enabled false; fi
  ok "AVD ${name} configuré ($(cfg emulator ram_mb 4096) Mo, $(cfg emulator cores 3) cœurs, $(cfg emulator width 1080)x$(cfg emulator height 2340)@$(cfg emulator density 420) dpi)"
}

setup_avd() {
  ensure_host_dns
  install_platform_tools
  install_emulator_and_image
  create_avd
  date +%s > "$VAR/.setup_avd_$(variant)"
}

setup_redroid() {
  has docker || die "Docker absent : backend redroid impossible"
  can_root && $SUDO modprobe binder_linux devices="binder,hwbinder,vndbinder" 2>/dev/null || true
  install_platform_tools
  local image; image="$(cfg emulator redroid_image redroid/redroid:13.0.0_gapps)"
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    info "construction d'une image redroid + GApps (MindTheGapps) via redroid-script…"
    local dir="$VAR/redroid-script"
    [[ -d "$dir" ]] || git clone --depth 1 https://github.com/ayasa520/redroid-script "$dir"
    (cd "$dir" && python3 -m pip install --user -q -r requirements.txt && python3 redroid.py -a 13.0.0 -mtg)
    local built; built="$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -m1 'redroid/redroid:13.0.0_' || true)"
    [[ -n "$built" ]] || die "construction redroid échouée (voir sortie ci-dessus)"
    docker tag "$built" "$image"
  fi
  ok "image $image prête"
  date +%s > "$VAR/.setup_redroid"
}

setup_remote() {
  install_platform_tools
  ok "backend remote : seul adb est nécessaire. Configure REMOTE_ADB_SERIAL dans .env."
  date +%s > "$VAR/.setup_remote"
}

install_packages
case "$B" in
  avd) setup_avd ;;
  redroid) setup_redroid ;;
  remote) setup_remote ;;
  *) die "backend inconnu : $B" ;;
esac
ok "installation ${B} terminée"

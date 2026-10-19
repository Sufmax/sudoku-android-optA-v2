#!/usr/bin/env bash
# =============================================================================
#  Diagnostic de l'environnement : KVM, virtualisation imbriquée, cgroups, root,
#  affichage virtuel, SDK, ressources. Écrit var/diagnose.json et var/backend.
#
#  Décision (corrigée par rapport à la v2.0) :
#    - /dev/kvm utilisable  → backend avd, chemin A : émulateur accéléré (-accel on)
#    - /dev/kvm absent      → backend avd, chemin B : émulation logicielle (-accel off)
#      C'est la recette validée sur CodeSandbox par le dépôt android_emulator
#      (API 29 x86_64 + SwiftShader + Xvfb). Le backend « remote » n'est plus
#      jamais choisi automatiquement.
# =============================================================================
set -uo pipefail
source "$(dirname "$0")/lib.sh"
load_env

kvm_dev="absent"; kvm_rw=false
if [[ -e /dev/kvm ]]; then kvm_dev="présent"; kvm_usable && kvm_rw=true; fi
vmx=$(grep -cE 'vmx|svm' /proc/cpuinfo 2>/dev/null || true); vmx=${vmx:-0}
nested="inconnu"
for f in /sys/module/kvm_intel/parameters/nested /sys/module/kvm_amd/parameters/nested; do [[ -r $f ]] && nested="$(cat "$f")"; done
modules="$( (lsmod 2>/dev/null || cat /proc/modules 2>/dev/null) | awk '{print $1}' | grep -E '^(kvm|kvm_intel|kvm_amd|binder_linux)$' | tr '\n' ' ' | xargs || true)"
hypervisor="$(grep -m1 -o 'hypervisor' /proc/cpuinfo 2>/dev/null || true)"
vendor="$( (cat /sys/class/dmi/id/sys_vendor 2>/dev/null; cat /sys/class/dmi/id/product_name 2>/dev/null) | tr '\n' ' ' | xargs || true)"
vendor="$(echo "${vendor:-inconnu}" | tr -d '"\n' | xargs)"
cgroup="v1"; [[ -f /sys/fs/cgroup/cgroup.controllers ]] && cgroup="v2"
root=false; can_root && root=true
in_container=false; { [[ -f /.dockerenv ]] || grep -qE 'docker|containerd|kubepods' /proc/1/cgroup 2>/dev/null; } && in_container=true
cpus=$(nproc 2>/dev/null || echo 1)
mem_mb=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 ))
disk_free_gb=$(df -Pk "$ROOT" | awk 'NR==2 {printf "%d", $4/1024/1024}')
kernel="$(uname -r)"
sdk_ok=false; [[ -x "$ANDROID_SDK_ROOT/emulator/emulator" ]] && sdk_ok=true
img_ok=false; [[ -d "$ANDROID_SDK_ROOT/system-images/android-$(api_level)/$(image_tag)/$(abi)" ]] && img_ok=true
x_ok=false; has Xvfb && has x11vnc && has websockify && x_ok=true
ocr_ok=false; has tesseract && ocr_ok=true
java_ok=false; has java && java_ok=true

recommended="$(backend)"
accel="$(accel_mode)"
if [[ "$recommended" == "avd" ]]; then
  if [[ "$accel" == "on" ]]; then reason="KVM utilisable : émulateur accéléré (chemin A)"
  else reason="pas de KVM : émulation logicielle -accel off (chemin B, recette CodeSandbox éprouvée)"; fi
else
  reason="backend « $recommended » imposé par la configuration / .env"
fi
(( disk_free_gb < 10 )) && reason="$reason — ATTENTION : seulement ${disk_free_gb} Go libres (≥ 10 recommandés)"
(( mem_mb < 6000 )) && reason="$reason — ATTENTION : RAM ${mem_mb} Mo (baisse emulator.ram_mb à 3072)"

cat > "$VAR/diagnose.json" <<JSON
{"kvm_device":"$kvm_dev","kvm_rw":$kvm_rw,"cpu_virt_flags":$vmx,"nested":"$nested","kernel_modules":"$modules",
 "hypervisor_flag":"${hypervisor:-non}","platform":"$vendor","cgroup":"$cgroup","root":$root,"container":$in_container,
 "cpus":$cpus,"mem_mb":$mem_mb,"disk_free_gb":$disk_free_gb,"kernel":"$kernel","sdk_root":"$ANDROID_SDK_ROOT",
 "sdk":$sdk_ok,"system_image":$img_ok,"image":"$(system_image)","xvfb_vnc_novnc":$x_ok,"tesseract":$ocr_ok,"java":$java_ok,
 "recommended_backend":"$recommended","accel":"$accel","variant":"$(variant)","reason":"$reason","ts":$(date +%s)}
JSON
echo "$recommended" > "$VAR/backend.recommended"
[[ -f "$VAR/backend" ]] || echo "$recommended" > "$VAR/backend"

yn() { [[ "$1" == true ]] && echo "oui" || echo "non"; }
echo "${c_bold}── Diagnostic ─────────────────────────────────────────────${c_off}"
printf '  %-28s %s\n' \
  "/dev/kvm" "$kvm_dev (rw: $(yn $kvm_rw))" \
  "Flags vmx/svm (CPU)" "$vmx" \
  "Virtualisation imbriquée" "$nested" \
  "Modules noyau" "${modules:-aucun}" \
  "Plateforme" "${vendor:-inconnue} (conteneur: $(yn $in_container))" \
  "cgroups" "$cgroup" \
  "root/sudo" "$(yn $root)" \
  "vCPU / RAM" "$cpus / ${mem_mb} Mo" \
  "Disque libre" "${disk_free_gb} Go" \
  "Noyau" "$kernel" \
  "SDK Android" "$ANDROID_SDK_ROOT ($(yn $sdk_ok))" \
  "Image système" "$(system_image) ($(yn $img_ok))" \
  "Xvfb + x11vnc + noVNC" "$(yn $x_ok)" \
  "Java / Tesseract" "$(yn $java_ok) / $(yn $ocr_ok)"
echo "  ${c_bold}Backend : $recommended · accélération : $accel · variante : $(variant)${c_off}"
echo "  → $reason"
if [[ "$accel" == "off" && "$recommended" == "avd" ]]; then
  echo "  ${c_cyn}Sans KVM : boot à froid 3–10 min (jusqu'à 20 min au tout premier boot Play Store),"
  echo "  puis ~0,3–0,8 s par appui ADB. Le mode vitesse « Adaptatif » s'y cale tout seul.${c_off}"
fi
exit 0

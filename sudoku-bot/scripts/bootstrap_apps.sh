#!/usr/bin/env bash
# =============================================================================
#  Variante « aurora » uniquement : installe Aurora Store (client libre du
#  Google Play Store, connexion anonyme OU avec ton compte Google) depuis F-Droid.
#  Logique de sélection du versionCode reprise du dépôt android_emulator.
#  Idempotent : ne fait rien si Aurora Store est déjà installé.
# =============================================================================
set -uo pipefail
source "$(dirname "$0")/lib.sh"
load_env
S="${1:-$(serial_for "$(backend)")}"
APK_DIR="$VAR/apks"; mkdir -p "$APK_DIR"
PACKAGES=("com.aurora.store")
[[ "${INSTALL_FDROID:-0}" == "1" ]] && PACKAGES+=("org.fdroid.fdroid")

is_installed() { adbt -s "$S" shell pm path "$1" 2>/dev/null | grep -q '^package:'; }

# Retourne l'URL du meilleur APK F-Droid compatible x86/x86_64 (stdout), logs sur stderr.
fdroid_latest_url() {
  local pkg="$1" suffix
  [[ "$(abi)" == "x86" ]] && suffix=30 || suffix=10   # suffixes de versionCode F-Droid multi-arch
  local tmp; tmp="$(mktemp)"
  local code; code=$(curl --globoff -s --max-time 20 --retry 2 -w "%{http_code}" -o "$tmp" "https://f-droid.org/api/v1/packages/${pkg}")
  if [[ "$code" != "200" ]]; then echo "  [F-Droid] HTTP $code pour $pkg" >&2; rm -f "$tmp"; return 1; fi
  python3 - "$tmp" "$suffix" "$pkg" <<'PYEOF'
import json, sys
from collections import defaultdict
path, suffix, pkg = sys.argv[1], int(sys.argv[2]), sys.argv[3]
data = json.load(open(path))
groups = defaultdict(list)
for p in data.get("packages", []):
    groups[p["versionName"]].append(p["versionCode"])
selected = []
for name, codes in groups.items():
    if len(codes) == 1:
        selected.append(codes[0]); continue
    arch = [c for c in codes if c % 100 == suffix]
    if arch:
        selected.append(max(arch)); continue
    generic = [c for c in codes if c % 100 == 0]
    selected.append(max(generic) if generic else min(codes))
if not selected:
    sys.exit(1)
print(f"https://f-droid.org/repo/{pkg}_{max(selected)}.apk")
PYEOF
  local rc=$?; rm -f "$tmp"; return $rc
}

install_pkg() {
  local pkg="$1" apk="$APK_DIR/${1}.apk" url
  if is_installed "$pkg"; then ok "$pkg déjà installé"; return 0; fi
  info "recherche F-Droid : $pkg"
  url="$(fdroid_latest_url "$pkg")" || { warn "aucun APK trouvé pour $pkg"; return 1; }
  info "téléchargement $(basename "$url")"
  curl --globoff -fL --retry 3 --connect-timeout 20 --max-time 300 -o "$apk" "$url" || { warn "téléchargement échoué"; return 1; }
  [[ "$(head -c 2 "$apk")" == "PK" ]] || { warn "fichier téléchargé invalide (pas un APK)"; rm -f "$apk"; return 1; }
  ADB_CMD_TIMEOUT_S=300 adbt -s "$S" install -r -g "$apk" >/dev/null 2>&1 && ok "$pkg installé" || { warn "installation de $pkg échouée"; return 1; }
}

booted "$S" || die "appareil $S non démarré"
adbt -s "$S" shell settings put global package_verifier_enable 0 >/dev/null 2>&1 || true
adbt -s "$S" shell settings put secure install_non_market_apps 1 >/dev/null 2>&1 || true
rc=0
for p in "${PACKAGES[@]}"; do install_pkg "$p" || rc=1; done
exit $rc

# Émulateur Android sur CodeSandbox — v2.1 (corrigée)

## 1. Pourquoi la v2.0 ne démarrait pas

| # | Cause | Effet | Correction v2.1 |
|---|---|---|---|
| 1 | `diagnose.sh` choisissait **`remote`** dès que `/dev/kvm` manquait | aucun émulateur local n'était jamais lancé sur CodeSandbox | sans KVM → backend `avd` avec `-accel off` (chemin B) |
| 2 | Image **API 33** `google_apis_playstore` | trop lourde pour l'émulation logicielle | **API 29** x86_64, celle de la recette `android_emulator` qui fonctionne |
| 3 | Aucun devcontainer : paquets installés à la volée, souvent sans root | Java, Xvfb, x11vnc, noVNC absents | `.devcontainer/Dockerfile` (Ubuntu 22.04, root, SDK + images préinstallés) |
| 4 | `-no-window` par défaut, Xvfb `:99` lancé seulement « si présent » | écran noir dans noVNC | Xvfb `:1` → x11vnc → noVNC **avant** l'émulateur, jamais `-no-window` |
| 5 | x11vnc sans `-noshm` | erreur MIT-SHM dans le conteneur | `-noshm` (déjà corrigé dans la recette d'origine) |
| 6 | `ANDROID_EMULATOR_HOME` / `ANDROID_USER_HOME` déplacés | clé ADB injectée différente de celle d'adb → `unauthorized` (images Play Store) | clés laissées dans `$HOME/.android` ; seul `ANDROID_AVD_HOME` est déplacé |
| 7 | `yes \| sdkmanager` avec `set -o pipefail` | un téléchargement réussi était vu comme un échec (code 141, SIGPIPE) | `sdkmanager … < <(yes)` |
| 8 | Verrous hérités par les processus d'arrière-plan (`flock`) | `--restart`/`--stop` bloqués, `./run.sh` croyait une instance encore active | `8>&- 9>&-` sur chaque processus lancé en arrière-plan |
| 9 | `adb shell` sans délai maximal | blocage infini juste après le boot (invité saturé) | wrapper `adbt` (`timeout 25 s`) |
| 10 | Verrous d'AVD orphelins après hibernation / `kill -9` | « another emulator instance is running » | nettoyage des `*.lock` quand aucun qemu ne tourne |
| 11 | DNS de l'invité non fixé | le Play Store ne se connecte pas | `-dns-server 8.8.8.8,8.8.4.4` + correction de `/etc/resolv.conf` uniquement si nécessaire |

## 2. Validation réelle (mesurée, pas supposée)

Sur une machine de test **sans KVM** (4 vCPU, **3,9 Go** de RAM, Debian 12) :

- `setup_emulator.sh` : SDK + `system-images;android-29;google_apis_playstore;x86_64` + AVD → OK (3,9 Go sur disque)
- `start_emulator.sh` (2 cœurs, 2 Go invités) : ADB `device` à 120 s, **`sys.boot_completed=1` à 340 s**
- `com.android.vending` (Play Store) et `com.google.android.gms` présents ; écran d'accueil capturé par `screencap`
- Pile Xvfb → x11vnc → noVNC : `vnc_lite.html` répond en HTTP 200
- Juste après le boot, l'invité est saturé (« System UI isn't responding ») : la règle `anr` du bot appuie sur « Attendre ».

Sur CodeSandbox (8 Go, 3 cœurs et 4 Go invités), compte **3 à 10 min** de boot à froid ; le tout premier boot Play Store peut aller jusqu'à 20 min.

**Pas encore vérifié :** la connexion au compte Google et une session de jeu complète. Ces deux étapes demandent ton compte et ton intervention.

## 3. Architecture

```
run.sh
 ├─ diagnose.sh          KVM ? → accel on/off ; backend avd
 ├─ setup_emulator.sh    (1er lancement) SDK/image si absents, AVD dans var/android/avd
 ├─ start_emulator.sh
 │    ├─ remote_view.sh  Xvfb :1 → x11vnc :5900 (-noshm, local) → websockify/noVNC :6080
 │    └─ emulator -avd sudoku_<variante> -port 5554 -gpu swiftshader_indirect -accel off|on
 │                -no-snapshot-save -no-metrics -memory 4096 -cores 3 -dns-server …
 ├─ bootstrap_apps.sh    (variante aurora) Aurora Store depuis F-Droid
 ├─ supervisor.sh        toutes les 30 s : relance Xvfb/x11vnc/noVNC/émulateur si morts
 └─ python -m bot.main   attend PRÊT, puis joue
```

## 4. Variantes d'image

| Variante | Image | Store | Quand l'utiliser |
|---|---|---|---|
| `playstore` (défaut) | `android-29;google_apis_playstore;x86_64` | Google Play natif | cas nominal |
| `aurora` | `android-29;default;x86_64` (recette d'origine) | Aurora Store (client Play, compte Google ou anonyme) | bascule automatique si le 1er boot Play Store échoue (`image_fallback: true`), ou `IMAGE_VARIANT=aurora` |

Chaque variante a son propre AVD (`sudoku_playstore` / `sudoku_aurora`). La bascule ne supprime rien.

## 5. Persistance et hibernation

- L'AVD (partition data : compte Google, jeu, réglages) est dans `sudoku-bot/var/android/avd`, dans le workspace persistant.
- Si la microVM reprend après une hibernation **avec sa mémoire**, les processus continuent. Sinon, `./run.sh` relance tout sans rien réinstaller.
- `quickboot: false` (défaut, recette éprouvée) : boot à froid à chaque démarrage, données conservées. `quickboot: true` sauvegarde la RAM invitée (≈ 4 Go) à chaque arrêt propre. C'est plus rapide au réveil, mais coûteux sans KVM.

## 6. Estimations

| Élément | Disque | RAM |
|---|---|---|
| Image Docker (Ubuntu + JDK + Xvfb/noVNC + Tesseract) | ~1,5 Go | — |
| SDK (emulator + platform-tools + plateforme 29) | ~1,2 Go | — |
| Image Play Store API 29 x86_64 (+ default si préchargée) | ~3 Go (+ ~1,5 Go) | — |
| AVD (data 6 Go, sparse) | 2 à 6 Go | — |
| Émulateur (qemu, 4 Go invités) | — | ~3,6 à 4,2 Go |
| Xvfb + x11vnc + noVNC | — | ~150 Mo |
| Bot Python + OpenCV + Tesseract | ~400 Mo | ~300 à 500 Mo |
| **Total** | **~10 à 14 Go / 30** | **~4,5 à 5 Go / 8** |

## 7. Dépannage

| Symptôme | Action |
|---|---|
| `x86_64 emulation currently requires hardware acceleration` | `abi: "x86"` dans `config.yaml` (recette guide 1, également validée), puis `./run.sh` |
| Écran noir dans noVNC | `bash scripts/remote_view.sh status` ; l'émulateur ne doit pas tourner avec `-no-window` |
| `unauthorized` dans `adb devices` | `adb kill-server && ./run.sh emulator restart` |
| Boot interminable | `tail -f var/logs/emulator.log` ; baisse `ram_mb` à 3072 ; essaie `IMAGE_VARIANT=aurora` |
| Play Store sans réseau | vérifie `dns_servers` ; dans l'invité : Paramètres › Réseau |
| État global | `./run.sh doctor` |

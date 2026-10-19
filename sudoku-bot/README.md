# Sudoku Bot v2 — Python + ADB + vision, piloté depuis Cloudflare

Joue en autonomie à **Sudoku (`easy.sudoku.puzzle.solver.free`)** : *Nouvelle partie → Débutant → lecture → résolution → saisie par vagues → recommence*, 100 % par analyse d'image (aucune coordonnée mémorisée), observable et pilotable depuis un dashboard Cloudflare.

> Audit de l'ancien projet, faisabilité et architecture détaillée : [`docs/PHASE1_AUDIT_ARCHITECTURE.md`](docs/PHASE1_AUDIT_ARCHITECTURE.md). Protocole : [`worker/PROTOCOL.md`](worker/PROTOCOL.md).

## Émulateur Android sur CodeSandbox (v2.1, corrigée)
L'émulateur tourne **en local sur CodeSandbox, même sans `/dev/kvm`**. La recette vient du dépôt `android_emulator` :
API 29 x86_64, SwiftShader, fenêtre dessinée sur Xvfb `:1`, x11vnc `-noshm`, noVNC sur le port 6080, `-accel off`.
Elle a été testée sans KVM : Android 10 avec Play Store démarre en 340 s sur 2 cœurs et 2 Go.
Détails, causes de l'ancienne panne et dépannage : [`docs/EMULATOR.md`](docs/EMULATOR.md).

| Chemin | Quand | Résultat |
|---|---|---|
| **A** `avd` + KVM | `/dev/kvm` utilisable | émulateur accéléré, boot en ~1 min |
| **B** `avd` sans KVM *(cas CodeSandbox)* | par défaut | émulation logicielle : boot de 3 à 10 min, appuis ADB de 0,3 à 0,8 s, le mode vitesse « Adaptatif » s'y cale |
| `remote` / `redroid` | uniquement si `ANDROID_BACKEND` le demande | appareil ADB distant / conteneur Android |

Image : `playstore` (Google Play natif, par défaut). Si le tout premier boot n'aboutit pas, le script bascule automatiquement sur `aurora` : image AOSP de la recette d'origine + Aurora Store, client du Play Store qui accepte ton compte Google.

## Installation et utilisation
1. Pousse le dépôt sur CodeSandbox. Le dossier **`.devcontainer/`** (à la racine) construit l'image : Ubuntu 22.04, root, JDK 17, Xvfb/x11vnc/noVNC, Tesseract, SDK Android et images système préinstallés. Si CodeSandbox ne le fait pas tout seul : `Ctrl+Shift+P` › *Rebuild Container*.
2. Dans le terminal :
```bash
cd sudoku-bot
cp .env.example .env          # mot de passe (dashboard + noVNC), URL du Worker
./run.sh                      # point d'entrée UNIQUE (idempotent)
```
- **Premier lancement** : diagnostic → création de l'AVD → affichage distant → boot. Les dépendances Python s'installent en parallèle. Ensuite, le script attend.
- **Relancement** : réveil de l'AVD existant, sans rien recréer.
- **Écran Android** : `https://<id-sandbox>-6080.csb.app/vnc_lite.html` (affiché par le script, ou `./run.sh screen`). Mot de passe VNC : les 8 premiers caractères de `DASHBOARD_PASSWORD`. Le contrôle tactile est aussi intégré au dashboard.
- Connecte ton compte Google, installe le jeu, ouvre-le, puis **PRÊT** (bouton du dashboard ou `./run.sh ready`). Le bot joue alors en boucle.
- `Ctrl+C`, crash ou hibernation : `./run.sh` reprend. Le superviseur relance l'affichage et l'émulateur s'ils meurent.

Autres commandes : `./run.sh doctor` (état complet), `./run.sh emulator start|stop|restart`, `./run.sh pause|resume|status|stop|snapshot`, `./run.sh speed fast`, `./run.sh logs`, `./run.sh test`, `./run.sh teardown [--purge]`.
Tâches CodeSandbox prêtes à l'emploi : `.codesandbox/tasks.json`.
Analyse hors ligne d'une capture : `.venv/bin/python -m bot.main --analyze capture.png`.

## Déploiement du dashboard (Cloudflare)
```bash
# à la racine du dépôt (dashboard React)
npm install && npm run build                     # → dist/
cd sudoku-bot/worker && npm install
npx wrangler login
npx wrangler secret put DASHBOARD_PASSWORD       # même valeur que dans sudoku-bot/.env
npx wrangler secret put SESSION_SECRET           # chaîne aléatoire longue
npx wrangler deploy                              # → https://sudoku-hub.<compte>.workers.dev
```
Puis dans `sudoku-bot/.env` : `DASHBOARD_URL=wss://sudoku-hub.<compte>.workers.dev/ws/bot`.
Le bot ouvre une **connexion sortante** : aucun port entrant n'est nécessaire sur le VPS.

## Architecture
```
bot/adb        client ADB async (shell persistant, screencap brut), humanisation des appuis
bot/vision     grid.py (N et blocs R×C déduits des lignes), glyphs/digits.py (cases + gabarits),
               keypad.py (pavé re-détecté à chaque vague), buttons.py, screens.py (classification)
bot/ocr        Tesseract TSV (double polarité) + correspondance floue sans accents
bot/solver     solveur N×N R×C (unicité, timeout distinct de « insoluble »)
bot/input      vagues : planification, coupure, évaluation, correction, taille dynamique
bot/speed      paliers + adaptatif (hystérésis, cooldown, plafond temporaire)
bot/state      machine à états, persistance atomique
bot/telemetry  logs JSON, statistiques persistées, lien WebSocket, commandes CLI
worker/        Worker + Durable Object « Hub » (auth, WebSockets hibernables, multi-machines)
```

## Sécurité de jeu : le bot refuse d'agir quand il doute
- Confiance minimale (`detection.min_confidence_action`) pour tout appui ; sinon nouvelle capture.
- 2 lectures concordantes avant résolution ; chiffres initiaux validés (unicité ligne/colonne/bloc) ; solution **unique** exigée.
- Un chiffre initial n'est jamais touché ; si un chiffre initial « change » après une vague → lecture suspecte → nouvelle observation.
- Vague coupée après la complétion d'un chiffre ; évaluation après chaque vague (ok/manquant/faux/rouge) ; taille réduite si le taux d'échec dépasse le seuil.
- Après `safety.max_game_errors` erreurs rouges : vitesse minimale et vagues unitaires ; corrections répétées sur une même case → pause de sécurité.
- Écran inconnu : attente → RETOUR → relance du jeu ; ADB perdu : reconnexion → redémarrage de l'émulateur.

## Estimations
Disque : ~10 à 14 Go sur 30. RAM : ~4,5 à 5 Go sur 8 (détail dans `docs/EMULATOR.md`).

## Dépannage
| Symptôme | Piste |
|---|---|
| `l'émulateur s'est arrêté immédiatement` | `tail var/logs/emulator.log` ; si « requires hardware acceleration » → `abi: "x86"` |
| Écran noir dans noVNC | `bash scripts/remote_view.sh status` puis `./run.sh emulator restart` |
| Le bot attend sans rien faire | il attend « PRÊT » (`./run.sh ready`) ou sa confiance est trop basse (voir le journal, `var/failures/`) |
| `OCR indisponible` | `sudo apt install tesseract-ocr tesseract-ocr-fra` |
| Les menus ne sont pas reconnus | adapte `screens` / `labels` dans `config/config.yaml` (rechargement à chaud) |
| Chiffres mal lus après un changement de thème | supprime `var/state/templates.npz` et démarre une partie neuve (pavé complet = ré-apprentissage) |
| Dashboard « hors ligne » | `DASHBOARD_URL` en `wss://…/ws/bot`, même mot de passe des deux côtés |

## Tests
Les captures réelles du jeu (`tests/fixtures/screens/*.jpg`) ne sont pas versionnées. Sans elles, les tests de vision sont ignorés au lieu d'échouer.
`./run.sh test` : 47 tests (solveur 4×4 à 16×16, vision sur les captures réelles du dépôt d'origine, grilles synthétiques 4×4/6×6/8×8/9×9/12×12/16×16, OCR/TSV/règles, vagues, vitesse adaptative, machine à états, humanisation, ADB, config à chaud).

# Phase 1 — Audit, faisabilité et architecture

> Document de référence. Distinction systématique : **[SU]** = vérifié (lu dans le dépôt / mesuré),
> **[SUP]** = hypothèse, **[AV]** = à vérifier sur la machine cible.

## 1. Audit du dépôt existant (`Auto_sudoku-android-main`)

### 1.1 Architecture actuelle [SU]
| Élément | Rôle |
|---|---|
| `autojs/agent.js` (22 Ko) | « Yeux + mains » AutoJS6 : `captureScreen`, `press(x,y,d)`, OCR AutoJS en secours, long-polling HTTP vers Termux |
| `server/sudokubot/server.py` | Serveur HTTP Termux (127.0.0.1:8765), page web, API |
| `server/sudokubot/controller.py` (2 840 lignes) | Cerveau monolithique : menus, pop-ups, lecture, salves, reprises |
| `server/sudokubot/vision.py` | Détection grille par « crêtes » numpy/Pillow, gabarits de chiffres, pavé |
| `server/sudokubot/spots.py` | **Emplacements mémorisés** : calibration de hitboxes depuis `emplacements/*.jpg` → `data/spots.json` |
| `server/sudokubot/solver.py` | Solveur N×N, blocs br×bc, bitmasks + MRV |
| `server/sudokubot/speed.py`, `human.py` | Paliers + adaptatif, humanisation |
| `bus.py` | File d'ordres contrôleur ↔ agent |
| `config.json` / `config.example.json` | ~17 Ko de réglages, dont des **positions fractionnaires fixes** |
| `web/` | Page de pilotage locale |

Application cible [SU] : `easy.sudoku.puzzle.solver.free`, captures en 1080×2340 (Redmi Note 13).

### 1.2 Coordonnées en dur / zones fixes repérées [SU]
- `config.json › menus` : `rate_close_pos [0.5,0.625]`, `streak_flame_pos [0.5,0.32]`, `streak_retour_pos [0.5,0.92]`,
  `tutorial_close_pos [0.93,0.745]`, `tutorial_next_pos [0.5,0.93]`, `bonus_close_pos [0.5,0.72]`, `win_ok_pos [0.5,0.73]`, `tutorial_bottom_frac 0.72`.
- `spots.py` : hitboxes calibrées (`game`, `fin_partie`, `niveaux`) + boutons « appris » (`spots["learned"]`).
- `controller._tap_frac_pos`, `_express_blinds`, `_menus_fallback_taps`, `_postgame_express` : appuis à positions mémorisées.
→ **Tout est supprimé** dans le nouveau projet, y compris l'option d'enregistrement.

### 1.3 Bugs et erreurs logiques identifiés
| # | Fichier | Problème | Gravité |
|---|---|---|---|
| B1 | `controller._express_blinds` + `_postgame_express` | **Appuis « aveugles »** (sans capture) à des positions mémorisées pendant les enchaînements post-partie : si l'écran a changé (pub, autre pop-up), le bot tape n'importe où | Critique |
| B2 | `controller.execute` / `build_taps` | Les positions du pavé sont calculées **avant** la salve. Quand un chiffre est complété, sa touche **disparaît** (mesuré sur `grid_red_digits.jpg` / `screen_9.jpg` : les autres touches gardent leur position — *correction : j'avais d'abord supposé un recentrage, la mesure l'infirme*). Les coups suivants de ce chiffre dans la même salve tapent alors une zone vide, sont comptés comme « ratés » et faussent l'adaptatif ; la salve n'est pas interrompue (`KeyError` géré uniquement à la construction) | Moyenne |
| B3 | `vision.detect_keypad` | Hypothèse « ordre gauche→droite = 1..N » (docstring + README) : fausse dès qu'un chiffre est complété ; rustine `_keypad_infer_from_counts` heuristique | Élevée |
| B4 | `bus.AgentLink.call` | Après timeout, `pending/inflight` sont **forcés à None** alors que l'agent peut encore exécuter l'ordre → un ordre périmé (tap) peut s'exécuter après coup ; les résultats tardifs s'accumulent dans `results` (fuite mémoire) | Élevée |
| B5 | `solver.Sudoku.solve` | Timeout par horloge murale : un dépassement renvoie `0` solution, **indiscernable d'une grille impossible** → relectures inutiles / grille rejetée à tort | Moyenne |
| B6 | `human.point_in` | Le biais « droitier » (+2 % / +3 %) est ajouté **après** le bornage → le point peut sortir de la borne prévue (jusqu'au bord de case avec `edge_max=0.46`) | Moyenne |
| B7 | `controller.py` | 16 blocs `except Exception: pass` silencieux : erreurs avalées, pas de journalisation, états incohérents possibles | Moyenne |
| B8 | `speed.Speed.report` | `order.index(...)` sur liste vide → `ValueError` ; pas de cooldown/hystérésis → oscillation possible ; `save_perf` avale toute erreur | Faible |
| B9 | `controller` (salves « one_go ») | Une seule vérification pour toute la partie : une erreur de lecture du pavé se propage à 50+ coups | Élevée |
| B10 | Architecture | Monolithe 2 840 lignes, fortement couplé à AutoJS6 (accessibilité, overlay, Volume+) | — |

### 1.4 Ce qui est récupéré (réécrit, pas copié)
- Principe du solveur bitmask + MRV (corrigé : statut `timeout` distinct, unicité).
- Idée des gabarits de chiffres appris depuis le pavé (le pavé complet en début de partie est étiqueté par ordre, puis sert de référence — corrige B3).
- Ordre de saisie « humain » (cases évidentes, proximité, même chiffre).
- Textes des menus (`Nouvelle partie`, `Débutant`, pop-ups « Aimez-vous le Sudoku ? », « Bonus débutant », « Touchez la flamme », « Série quotidienne », « Bien joué ! »).

## 2. Faisabilité de l'infrastructure (CodeSandbox, 4 vCPU / 8 GiB / 30 GB)

### 2.1 KVM — constat honnête
- CodeSandbox exécute les environnements dans des **microVM Firecracker** [SU, documentation publique]. Firecracker **n'expose pas VMX/SVM** aux invités → **pas de `/dev/kvm`** et aucune virtualisation imbriquée. [AV via `scripts/diagnose.sh`]
- L'émulateur Android officiel refuse les images x86/x86_64 sans accélération (« x86_64 emulation currently requires hardware acceleration ») ; les images ARM64 récentes ne sont pas supportées sur hôte x86_64.
- QEMU pur en TCG (Android-x86/BlissOS) : démarrage 10-25 min, images à plusieurs secondes, Play Services en ANR. **Rejeté** : ce n'est pas un produit utilisable.

### 2.2 Chemins implémentés (choix automatique par `diagnose.sh`)
| Chemin | Condition | Play Store | Performance attendue |
|---|---|---|---|
| **A — `avd`** | `/dev/kvm` lisible/écrivable | Image officielle `google_apis_playstore` x86_64 | Boot à froid 60-120 s, Quick Boot 8-20 s, tap ADB 30-80 ms, capture raw 120-300 ms |
| **B — `redroid`** | Docker + binder (binderfs/`binder_linux`) dans le noyau | Image redroid + GApps construite via `redroid-script` (MindTheGapps), enregistrement de l'appareil « non certifié » nécessaire | Proche natif (conteneur), capture 80-200 ms |
| **C — `remote`** | Ni A ni B (cas **attendu** sur CodeSandbox) | Émulateur Play Store officiel sur un hôte KVM (PC, serveur dédié, GCE nested) **ou téléphone réel**, joint par tunnel ADB (SSH inverse / Tailscale) | Dépend du lien : +20-80 ms par commande, capture 200-600 ms. Le mode adaptatif absorbe ces latences |

**Ce que je ne promets pas** : que l'émulateur démarre *dans* CodeSandbox. Le script le tente si le diagnostic le permet, sinon il le dit et bascule sur C. Le bot, le dashboard, l'état et la reprise restent 100 % identiques quel que soit le chemin.

### 2.3 Estimation disque (chemin A)
| Élément | Disque |
|---|---|
| cmdline-tools + platform-tools + emulator | ~0,7 GB |
| Image système API 33 `google_apis_playstore` x86_64 | ~4,5 GB (zip 1,5 GB supprimé après extraction) |
| AVD : userdata (6 GB alloués, sparse) | 2-4 GB réels |
| Snapshots (Quick Boot + `bot_checkpoint`) | 2 × 1,5-3 GB |
| JDK headless + Tesseract fra/eng + Xvfb/x11vnc/noVNC | ~0,6 GB |
| venv Python (OpenCV headless, numpy, pydantic, websockets) | ~0,4 GB |
| Logs, stats, captures d'échec (bornées) | < 0,5 GB |
| **Total** | **~13-17 GB / 30 GB** |

### 2.4 Estimation RAM
| Processus | RAM |
|---|---|
| Émulateur (invité 3 GB + QEMU/swiftshader) | ~3,8 GB |
| Bot Python (OpenCV, buffers) | 250-450 MB |
| Tesseract (transitoire, écrans de menu) | ~150 MB |
| Xvfb + x11vnc + websockify (optionnels) | ~120 MB |
| **Total** | **~4,5 GB / 8 GB** |

## 3. Architecture globale
```
run.sh ─► scripts/diagnose.sh ─► setup_emulator.sh (1er lancement) ─► start_emulator.sh ─► python -m bot.main
                                                                                         │
 ┌──────────────── bot/ ───────────────────────────────────────────────────────────────┐ │
 │ adb/      AdbClient (subprocess async, shell persistant, screencap raw)  Humanizer  │◄┘
 │ vision/   grid.py (géométrie N, R×C) digits.py (cases+gabarits) keypad.py           │
 │           buttons.py (zone cliquable) screens.py (classification d'écran)           │
 │ ocr/      engine.py (Tesseract TSV + confiance) text.py (normalisation, fuzzy)      │
 │ solver/   solver.py (N×N R×C, unicité, timeout distinct)                            │
 │ input/    waves.py (planification, coupure de vague, évaluation) executor.py        │
 │ speed/    manager.py (paliers + adaptatif avec hystérésis et plafond)               │
 │ state/    machine.py (états/transitions) store.py (JSON atomique) controller.py     │
 │ telemetry/ logs JSON, métriques persistées, lien WebSocket, boîte de commandes CLI  │
 └─────────────────────────────────────────────────────────────────────────────────────┘
          │ WebSocket sortant (wss, backoff exponentiel)
          ▼
 Cloudflare Worker ── Durable Object « Hub » (machines, flux, logs, commandes) ── Dashboard (assets)
```
Modèles de données : `Rect`, `GridGeometry(n, box_rows, box_cols, xs, ys, confidence)`, `CellRead(value, kind, confidence)`,
`GridRead`, `KeyRead`, `KeypadRead`, `ScreenObservation(kind, confidence, …)`, `Move(r,c,v)`, `WaveResult`, `Stats`.

## 4. Pipeline de vision
1. **Grille** : niveaux de gris → seuillage adaptatif inverse → ouverture morphologique par noyaux longs (≥ 8 % de la largeur, plus longs qu'un trait de chiffre) → masques lignes H/V → plus grand contour quasi carré.
2. **N** : profils de couverture des masques dans la boîte ; pour chaque N candidat (config), on exige une ligne détectée à chaque position attendue `i·L/N` (tolérance relative) ; on retient le **plus grand N entièrement validé** (N=18 échoue car aucun trait au milieu des cases).
3. **Blocs R×C** : épaisseur × noirceur de chaque ligne interne (médiane sur la longueur, robuste aux chiffres) → séparation en 2 classes par le plus grand rapport ; les indices épais doivent être multiples d'un pas r | N ; R = pas horizontal, C = pas vertical, contrôle R·C = N. Sinon table de repli (confiance réduite).
4. **Cases** : fond estimé sur un anneau intérieur (gère les cases surlignées), encre = distance couleur > seuil ; composantes connexes ; le glyphe doit mesurer ≥ 35 % de la hauteur (exclut les notes au crayon) ; couleur → `GIVEN` (noir), `USER` (bleu), `ERROR` (rouge).
5. **Chiffres** : glyphe normalisé 32×32 → corrélation normalisée avec gabarits appris. Confiance = f(score, marge avec 2ᵉ). **Amorçage 100 % visuel** : en début de partie le pavé contient les N chiffres dans l'ordre → étiquetage par rang, puis gabarits persistés.
6. **Pavé** : composantes colorées sous la grille, regroupées par rangée, hauteur compatible ; rangée la plus fournie et régulière. Étiquetage par rang si complet, sinon par gabarits (unicité exigée). **Re-détecté après chaque vague** (corrige B2/B3).
7. **Boutons** : OCR Tesseract (TSV, `psm 11`), correspondance floue sans accents, puis expansion de la zone cliquable par croissance de région de couleur autour du texte.
8. **Écrans anormaux** : voile sombre sur la grille (modal), bloc saturé sur la grille (bulle d'info), règles OCR (pub, notation, série, bonus, ANR système), écran inconnu.
9. **Relecture** : 2 lectures concordantes exigées (configurable) ; grille incohérente/insoluble/multi-solutions → relecture, bornée.

## 5. Machine à états
`BOOT → WAIT_DEVICE → WAIT_READY → OBSERVE → {HOME, DIFFICULTY, LOADING, SOLVING, GAME_OVER, POPUP, UNKNOWN} → OBSERVE …`
plus `PAUSED`, `RECOVERING`, `STOPPING`. Toute action est précédée d'une observation fraîche et suivie d'une confirmation.
Reprise : l'état persistant n'est **qu'un indice** ; au redémarrage on repasse toujours par `OBSERVE` (jamais d'action rejouée à l'aveugle).
`PRÊT` est persisté : après hibernation, attente courte (relancement) ou automatique selon `workflow.auto_ready_on_resume`.

## 6. Vagues et mode adaptatif
- Vague = jusqu'à `wave_size × facteur` coups ; **coupée après tout coup qui complète un chiffre** (la touche disparaît ; garde-fou `waves.cut_on_digit_complete` pour les jeux qui recentrent le pavé).
- Après la vague : stabilisation, capture, relecture, comparaison : `ok / manquant / faux / erreur`. Corrections replanifiées.
- Taux d'échec > seuil → facteur × `shrink` ; vagues propres consécutives → facteur × `grow` (≤ 1).
- Adaptatif : départ « Moyen » ; monte après K vagues propres si latence ADB, temps de rendu et charge CPU sous seuils ; descend immédiatement sur échec ; cooldown ; plafond mémorisé temporairement après échec à un palier.

## 7. Protocole bot ↔ Worker
Voir `worker/PROTOCOL.md` (schéma complet de chaque message).

## 8. Roadmap (lots)
| Lot | Objectif | Fichiers | Acceptation |
|---|---|---|---|
| 1 | Config + modèles + solveur | `config/`, `bot/config.py`, `bot/models.py`, `bot/solver/` | tests solveur 4×4/6×6/9×9/12×12 |
| 2 | Vision grille/cases/pavé | `bot/vision/` | tests sur captures réelles du dépôt |
| 3 | OCR + écrans + boutons | `bot/ocr/`, `bot/vision/screens.py` | tests parsing TSV, fuzzy |
| 4 | ADB + humanisation | `bot/adb/` | tests bornes de tap, parsing screencap |
| 5 | Vagues + vitesse | `bot/input/`, `bot/speed/` | tests coupure/évaluation/adaptatif |
| 6 | Machine à états + contrôleur + télémétrie | `bot/state/`, `bot/telemetry/`, `bot/main.py` | tests transitions |
| 7 | Scripts infra | `run.sh`, `scripts/` | `bash -n`, diagnostic |
| 8 | Worker + DO + dashboard | `worker/`, dashboard React | build OK |

## 9. Informations encore manquantes (hypothèses prises)
- [SUP] Le libellé exact de l'écran de **défaite** (3 erreurs) n'est pas dans les captures : règles génériques fournies (`partie terminée`, `seconde chance`, `game over`), à ajuster dans `config.yaml`.
- [SUP] Le format des **publicités** n'est pas capturé : stratégie générique (attente, texte « Fermer/Ignorer/Skip/×», puis BACK).
- [SUP] Taper un autre chiffre sur une case erronée la remplace (sinon `input.correction: erase_then_write` utilise « Effacer »).

> **Mise à jour v2.1 :** le chemin « remote par défaut sans KVM » décrit ci-dessous est obsolète. L'émulateur tourne désormais en local sans KVM (voir `EMULATOR.md`).

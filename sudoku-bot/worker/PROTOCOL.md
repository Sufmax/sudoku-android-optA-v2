# Protocole bot ↔ Worker ↔ dashboard (v1)

Transport : WebSocket sur TLS (`wss://`). Messages JSON UTF-8, un objet par trame.
Champs communs émis par le bot : `v` (version du protocole = 1), `type`, `machine` (ID), `ts` (epoch s, flottant).

## 1. Connexions

| Canal | URL | Authentification |
|---|---|---|
| Bot → Hub | `wss://<worker>/ws/bot?machine=<ID>` | en-tête `X-Bot-Key: <DASHBOARD_PASSWORD>` (+ `X-Bot-Version`) |
| Dashboard → Hub | `wss://<worker>/ws/client` | cookie `sudoku_sid` (session HMAC, HttpOnly, Secure, SameSite=Strict) + contrôle d'origine |

Une nouvelle connexion bot avec le même ID ferme l'ancienne (code 4000). Le bot se reconnecte
avec backoff exponentiel `1 s → 60 s` + jitter 30 %.

## 2. Bot → Hub

| type | Champs | Fréquence |
|---|---|---|
| `hello` | `version: str`, `protocol: 1` | à chaque connexion |
| `status` | `status: Status` | à chaque transition + toutes les ~5 s |
| `metrics` | `stats: Stats` | fin de vague / partie + ~5 s |
| `device` | `device: Device` | après connexion ADB |
| `log` | `entry: {ts, level, logger, msg}` | chaque ligne de log |
| `frame` | `mime: "image/jpeg"`, `width`, `height` (taille réelle de l'écran), `data: base64` | `stream_fps`, uniquement si `viewers > 0` ; jamais mis en file (dernière image seulement) |
| `config` | `yaml: str` | réponse à `get_config` / `set_config` |
| `ack` | `id: str`, `ok: bool`, `info: str` | réponse à chaque commande |

```ts
Status = {
  state: "boot"|"wait_device"|"wait_ready"|"observe"|"navigate"|"loading"|"solving"|"game_over"|"recovering"|"paused"|"stopping",
  since: number, detail: string, screen: string, paused: boolean, ready: boolean,
  speed: { mode: string, tier: string, label: string, choices: {id: string, label: string}[], wave_factor: number },
  progress: { filled: number, total: number },
  game: { id?: string, n?: number, box?: [number, number], started?: number, errors?: number, waves?: number },
  adb: { serial: string, latency_ms: number, capture_ms: number, failures: number },
  device: Device, templates: number
}
Stats = { games_started, games_won, games_failed, total_game_s, last_game_s, digits_placed, corrections, rereads,
          waves, failed_waves, errors, game_errors_red, total_runtime_s, first_seen,
          avg_game_s, avg_digit_s, wave_fail_rate, correction_rate, uptime_s }
Device = { model, android, sdk, width, height, density, ram_mb, battery, serial }
```

## 3. Hub → Bot

| type | Champs | Signification |
|---|---|---|
| `viewers` | `count: int` | nombre de dashboards qui regardent cette machine (active/coupe le flux) |
| `command` | `id: str`, `action: Action`, `params: object` | commande relayée depuis le dashboard |

`Action` et `params` :

| action | params | Effet |
|---|---|---|
| `ready` | — | fin de la configuration manuelle, démarrage autonome (persisté) |
| `pause` / `resume` | — | effet au prochain point d'arrêt (entre deux coups, jamais au milieu) ; reprise = nouvelle observation complète |
| `set_speed` | `mode: "adaptive"\|"very_slow"\|"slow"\|"medium"\|"fast"\|"very_fast"` | palier à chaud |
| `set_stream` | `fps: number` | fréquence du flux d'écran |
| `get_config` | — | demande le YAML courant |
| `set_config` | `yaml: str` | validation pydantic puis écriture atomique ; `ack.info` liste les clés nécessitant un redémarrage |
| `tap` | `x, y ∈ [0,1]` | contrôle manuel (uniquement en attente de PRÊT ou en pause) |
| `swipe` | `x1, y1, x2, y2 ∈ [0,1]`, `ms` | idem |
| `key` | `key: "back"\|"home"\|"recents"\|"enter"\|"del"` | idem |
| `text` | `text: str` | saisie clavier (idem) |
| `snapshot` | — | sauvegarde d'un snapshot émulateur (backend avd) |
| `stop` | — | arrêt propre du bot |

## 4. Dashboard ↔ Hub

Client → Hub : `{"type":"subscribe","machine":ID}`, `{"type":"command","machine":ID,"id":uuid,"action":…, "params":{…}}`, `{"type":"ping"}`.

Hub → Client :
- `{"type":"snapshot","machines":[Machine…],"logs":{ID:[entry…]}}` à la connexion ;
- `{"type":"machine","machine":Machine}` à chaque changement ;
- `frame`, `log`, `config`, `ack` relayés (filtrés sur la machine abonnée) ; `pong`.

`Machine = { id, version, connected, lastSeen (ms), connectedAt (ms), status: Status|null, stats: Stats|null, device: Device|null }`.

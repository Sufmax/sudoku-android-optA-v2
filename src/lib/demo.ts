// Simulateur fidèle du bot : utilisé quand le dashboard n'est pas servi par le Worker (aperçu).
import type { Ack, Action, Frame, LogEntry, Machine, Stats, Status } from "./types";
// La vraie configuration du bot, affichée et éditable en mode démo.
import configYaml from "../../sudoku-bot/config/config.yaml?raw";

const PUZZLE = "000143008094257163013608250109465387306829540400730926507914630040076810630080009";
const SOLUTION = "265143798894257163713698254129465387376829541458731926587914632942376815631582479";

const TIERS = [
  { id: "very_slow", label: "Très lent", wave: 2, ms: 2600 },
  { id: "slow", label: "Lent", wave: 4, ms: 2200 },
  { id: "medium", label: "Moyen", wave: 8, ms: 1800 },
  { id: "fast", label: "Rapide", wave: 14, ms: 1500 },
  { id: "very_fast", label: "Très rapide", wave: 24, ms: 1300 },
];

export interface DemoSink {
  machine(m: Machine): void;
  log(e: LogEntry): void;
  frame(f: Frame): void;
  ack(a: Ack): void;
  config(yaml: string): void;
}

function svgScreen(screen: string, filled: Set<number>, errorCell: number | null): string {
  const W = 1080, H = 2340, gx = 14, gy = 513, gs = 1053, cs = gs / 9;
  const ink = "#1a1a1a", blue = "#2f5bd3";
  let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}"><rect width="${W}" height="${H}" fill="#f4f6fb"/>`;
  s += `<text x="70" y="230" font-family="Arial" font-size="44" fill="#222">←  Parcours 12</text>`;
  if (screen === "solving" || screen === "loading" || screen === "game_over") {
    s += `<rect x="${gx}" y="${gy}" width="${gs}" height="${gs}" fill="#fff"/>`;
    for (let i = 0; i < 81; i++) {
      const r = Math.floor(i / 9), c = i % 9;
      const given = PUZZLE[i] !== "0";
      const show = given || filled.has(i);
      if (i === errorCell) s += `<rect x="${gx + c * cs}" y="${gy + r * cs}" width="${cs}" height="${cs}" fill="#fde2e2"/>`;
      if (show) {
        const color = given ? ink : i === errorCell ? "#e0393e" : blue;
        s += `<text x="${gx + c * cs + cs / 2}" y="${gy + r * cs + cs * 0.72}" font-family="Arial" font-size="78" text-anchor="middle" fill="${color}">${SOLUTION[i]}</text>`;
      }
    }
    for (let i = 0; i <= 9; i++) {
      const w = i % 3 === 0 ? 6 : 2, p = i * cs;
      s += `<line x1="${gx}" y1="${gy + p}" x2="${gx + gs}" y2="${gy + p}" stroke="#333" stroke-width="${w}"/>`;
      s += `<line x1="${gx + p}" y1="${gy}" x2="${gx + p}" y2="${gy + gs}" stroke="#333" stroke-width="${w}"/>`;
    }
    for (let d = 1; d <= 9; d++) s += `<text x="${40 + (d - 1) * 117 + 50}" y="1990" font-family="Arial" font-size="92" text-anchor="middle" fill="${blue}">${d}</text>`;
    if (screen === "loading") s += `<rect x="190" y="900" width="700" height="220" rx="24" fill="#1f4fd1"/><text x="540" y="1025" font-family="Arial" font-size="40" text-anchor="middle" fill="#fff">Plus de 19 % des joueurs bloqués…</text>`;
    if (screen === "game_over") s += `<rect width="${W}" height="${H}" fill="#0008"/><rect x="90" y="420" width="900" height="900" rx="40" fill="#fff"/><text x="540" y="640" font-family="Arial" font-size="72" text-anchor="middle" fill="#111">Coup de génie !</text><rect x="240" y="1600" width="600" height="120" rx="20" fill="#1f4fd1"/><text x="540" y="1680" font-family="Arial" font-size="48" text-anchor="middle" fill="#fff">Nouvelle partie</text>`;
  } else {
    s += `<text x="540" y="1150" font-family="Arial" font-size="64" text-anchor="middle" fill="#666">Sudoku classique</text>`;
    s += `<rect x="240" y="1300" width="600" height="120" rx="20" fill="#1f4fd1"/><text x="540" y="1380" font-family="Arial" font-size="48" text-anchor="middle" fill="#fff">Nouvelle partie</text>`;
    if (screen === "difficulty") {
      s += `<rect y="1250" width="${W}" height="1090" rx="40" fill="#fff"/><text x="540" y="1370" font-family="Arial" font-size="54" text-anchor="middle">Nouvelle partie</text>`;
      ["Débutant", "Facile", "Moyen", "Difficile"].forEach((t, i) => (s += `<rect x="50" y="${1460 + i * 140}" width="980" height="110" rx="18" fill="#f1f3f8"/><text x="120" y="${1530 + i * 140}" font-family="Arial" font-size="44">${t}</text>`));
    }
  }
  return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(s + "</svg>")))}`;
}

export class DemoBot {
  private status: Status;
  private stats: Stats;
  private filled = new Set<number>();
  private queue: number[] = [];
  private screen = "home";
  private tier = 2;
  private mode = "adaptive";
  private clean = 0;
  private timer: number | undefined;
  private frameTimer: number | undefined;
  private yaml = configYaml;
  private startedAt = Date.now() / 1000;
  private errorCell: number | null = null;
  private gameStart = 0;

  constructor(private sink: DemoSink) {
    const now = Date.now() / 1000;
    this.stats = {
      games_started: 148, games_won: 146, games_failed: 2, total_game_s: 146 * 71.4, last_game_s: 68.2, digits_placed: 6962,
      corrections: 41, rereads: 97, waves: 1022, failed_waves: 37, errors: 3, game_errors_red: 4, total_runtime_s: 3600 * 31.5,
      first_seen: now - 86400 * 3, avg_game_s: 71.4, avg_digit_s: 1.497, wave_fail_rate: 0.036, correction_rate: 0.006, uptime_s: 0,
    };
    this.status = {
      state: "wait_ready", since: now, detail: "premier lancement : connecte Google, installe le jeu, ouvre-le, puis PRÊT",
      screen: "home", paused: false, ready: false,
      speed: { mode: "adaptive", tier: "medium", label: "Adaptatif › Moyen", choices: [{ id: "adaptive", label: "Adaptatif" }, ...TIERS.map((t) => ({ id: t.id, label: t.label }))], wave_factor: 1 },
      progress: { filled: 0, total: 0 }, game: {},
      adb: { serial: "127.0.0.1:5555", latency_ms: 46, capture_ms: 212, failures: 0 },
      device: { model: "sdk_gphone_x86_64", android: "10", sdk: "29", width: 1080, height: 2340, density: 420, ram_mb: 3946, battery: 100, serial: "emulator-5554" },
      emulator: { state: "ready", backend: "avd", variant: "playstore", image: "system-images;android-29;google_apis_playstore;x86_64", avd: "sudoku_playstore", accel: "off", kvm: false, serial: "emulator-5554", novnc_url: "" },
      templates: 9,
    };
  }

  start(): void {
    this.emit();
    this.log("INFO", "bot.main", "Sudoku Bot 2.0.0 — machine csb-01 (mode démo)");
    this.log("INFO", "bot.ctrl", "appareil prêt : sdk_gphone64_x86_64 Android 13 1080x2340");
    this.log("WARNING", "bot.ctrl", "EN ATTENTE DE « PRÊT » — Dashboard (bouton PRÊT) ou : ./run.sh ready");
    this.frameTimer = window.setInterval(() => this.sendFrame(), 1000);
    this.sendFrame();
    this.sink.config(this.yaml);
  }

  stop(): void {
    window.clearTimeout(this.timer);
    window.clearInterval(this.frameTimer);
  }

  private machine(): Machine {
    this.stats.uptime_s = Date.now() / 1000 - this.startedAt;
    return { id: "csb-01", version: "2.0.0", connected: true, lastSeen: Date.now(), connectedAt: this.startedAt * 1000, status: { ...this.status }, stats: { ...this.stats }, device: this.status.device };
  }

  private emit(): void { this.sink.machine(this.machine()); }

  private log(level: string, logger: string, msg: string): void {
    this.sink.log({ ts: Date.now() / 1000, level, logger, msg });
  }

  private sendFrame(): void {
    this.sink.frame({ data: svgScreen(this.screen, this.filled, this.errorCell), mime: "image/svg+xml", width: 1080, height: 2340, ts: Date.now() / 1000 });
  }

  private setState(state: Status["state"], detail: string, screen?: string): void {
    if (state !== this.status.state) this.log("INFO", "bot.ctrl", `état ${this.status.state} → ${state}${detail ? ` (${detail})` : ""}`);
    this.status.state = state;
    this.status.since = Date.now() / 1000;
    this.status.detail = detail;
    if (screen) { this.screen = screen; this.status.screen = screen; }
    this.emit();
  }

  private speedLabel(): void {
    const t = TIERS[this.tier];
    this.status.speed = { ...this.status.speed, mode: this.mode, tier: t.id, label: this.mode === "adaptive" ? `Adaptatif › ${t.label}` : t.label };
  }

  private schedule(ms: number, fn: () => void): void {
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => {
      if (this.status.paused) { this.schedule(500, fn); return; }
      fn();
    }, ms);
  }

  private loop(): void {
    this.setState("navigate", "home", "home");
    this.schedule(1100, () => {
      this.log("INFO", "bot.ctrl", "home : appui sur « nouvelle partie » (confiance 0.93)");
      this.setState("navigate", "difficulty", "difficulty");
      this.schedule(1100, () => {
        this.log("INFO", "bot.ctrl", "difficulty : appui sur « debutant » (confiance 0.95)");
        this.setState("loading", "message transitoire sur la grille", "loading");
        this.schedule(1600, () => this.newGame());
      });
    });
  }

  private newGame(): void {
    this.filled.clear();
    this.errorCell = null;
    this.queue = [...PUZZLE].map((ch, i) => (ch === "0" ? i : -1)).filter((i) => i >= 0).sort(() => Math.random() - 0.5);
    this.stats.games_started++;
    this.gameStart = Date.now() / 1000;
    this.status.game = { id: Math.random().toString(16).slice(2, 18), n: 9, box: [3, 3], started: this.gameStart, errors: 0, waves: 0 };
    this.status.progress = { filled: 0, total: this.queue.length };
    this.log("INFO", "bot.ctrl", `nouvelle partie ${this.status.game.id} (9x9, blocs 3x3)`);
    this.log("INFO", "bot.ctrl", "solveur : unique (61 nœuds, 0.004s)");
    this.setState("solving", "9x9 blocs 3x3", "solving");
    this.wave();
  }

  private wave(): void {
    const t = TIERS[this.tier];
    const size = Math.max(1, Math.round(t.wave * this.status.speed.wave_factor));
    this.status.detail = `vague de ${Math.min(size, this.queue.length)} coup(s) · ${this.status.speed.label}`;
    this.emit();
    this.schedule(t.ms + Math.min(size, this.queue.length) * 90, () => {
      const wave = this.queue.splice(0, size);
      const fail = this.tier >= 3 && Math.random() < 0.18 && wave.length > 2;
      let ok = wave.length, missing = 0;
      if (fail) { const lost = wave.pop()!; this.queue.unshift(lost); ok--; missing = 1; }
      wave.forEach((i) => this.filled.add(i));
      this.stats.digits_placed += ok;
      this.stats.waves++;
      this.status.game.waves = (this.status.game.waves || 0) + 1;
      if (fail) this.stats.failed_waves++;
      this.status.progress = { filled: this.filled.size, total: this.filled.size + this.queue.length };
      this.status.adb.latency_ms = Math.round(38 + Math.random() * 30 + this.tier * 6);
      this.log("INFO", "bot.ctrl", `vague ${this.status.game.waves} : ${ok} ok, ${missing} manquant(s), 0 faux, 0 erreur(s) · rendu ${Math.round(500 + Math.random() * 300)} ms · ADB ${this.status.adb.latency_ms} ms`);
      if (this.mode === "adaptive") this.adapt(fail);
      this.sendFrame();
      if (this.queue.length) this.wave();
      else this.finish();
    });
  }

  private adapt(fail: boolean): void {
    if (fail && this.tier > 0) {
      this.tier--; this.clean = 0;
      this.log("WARNING", "bot.speed", `vitesse adaptative down → Adaptatif › ${TIERS[this.tier].label}`);
    } else if (!fail && ++this.clean >= 3 && this.tier < 4) {
      this.tier++; this.clean = 0;
      this.log("INFO", "bot.speed", `vitesse adaptative up → Adaptatif › ${TIERS[this.tier].label}`);
    }
    this.speedLabel();
  }

  private finish(): void {
    this.setState("game_over", "game_over", "game_over");
    const dur = Date.now() / 1000 - this.gameStart;
    this.stats.games_won++;
    this.stats.total_game_s += dur;
    this.stats.last_game_s = dur;
    this.stats.avg_game_s = this.stats.total_game_s / this.stats.games_won;
    this.stats.wave_fail_rate = this.stats.failed_waves / this.stats.waves;
    this.log("INFO", "bot.ctrl", `partie ${this.status.game.id} réussie en ${dur.toFixed(1)}s`);
    this.sendFrame();
    this.schedule(1800, () => this.loop());
  }

  command(action: Action, params: Record<string, unknown>, id: string): void {
    let ok = true, info = "";
    switch (action) {
      case "ready":
        if (!this.status.ready) { this.status.ready = true; info = "PRÊT reçu"; this.loop(); }
        break;
      case "pause":
        this.status.paused = true; this.setState("paused", "pause demandée"); break;
      case "resume":
        this.status.paused = false; this.log("INFO", "bot.ctrl", "reprise après pause : nouvelle observation complète");
        this.setState(this.screen === "solving" ? "solving" : "observe", "reprise"); break;
      case "set_speed": {
        const m = String(params.mode);
        const idx = TIERS.findIndex((t) => t.id === m);
        if (m === "adaptive") { this.mode = m; this.tier = 2; } else if (idx >= 0) { this.mode = m; this.tier = idx; } else ok = false;
        this.speedLabel(); info = this.status.speed.label; break;
      }
      case "set_config":
        if (typeof params.yaml === "string" && params.yaml.includes("speed:")) { this.yaml = params.yaml; info = "appliquée à chaud"; this.sink.config(this.yaml); }
        else { ok = false; info = "configuration refusée : section speed manquante"; }
        break;
      case "get_config": this.sink.config(this.yaml); break;
      case "tap": case "swipe": case "key": case "text":
        if (!["wait_ready", "paused"].includes(this.status.state)) { ok = false; info = "contrôle manuel disponible uniquement en attente de PRÊT ou en pause"; }
        else info = `${action} transmis`;
        break;
      case "set_stream": info = `flux ${params.fps} img/s`; break;
      case "snapshot": info = "snapshot bot_checkpoint sauvegardé"; break;
      case "stop": ok = false; info = "arrêt désactivé en démo"; break;
    }
    this.log(ok ? "INFO" : "WARNING", "bot.ctrl", `commande ${action} → ${ok ? "ok" : "refusée"} ${info}`);
    this.sink.ack({ id, ok, info });
    this.emit();
  }
}

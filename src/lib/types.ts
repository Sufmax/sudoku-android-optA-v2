// Types du protocole bot ↔ Hub ↔ dashboard (voir sudoku-bot/worker/PROTOCOL.md)
export type BotStateName =
  | "boot" | "wait_device" | "wait_ready" | "observe" | "navigate" | "loading"
  | "solving" | "game_over" | "recovering" | "paused" | "stopping";

export interface SpeedInfo {
  mode: string;
  tier: string;
  label: string;
  choices: { id: string; label: string }[];
  wave_factor: number;
}

export interface Device {
  model: string; android: string; sdk: string; width: number; height: number;
  density: number; ram_mb: number; battery: number; serial: string;
}

/** État de l'émulateur publié par scripts/start_emulator.sh (var/state/emulator.json). */
export interface EmulatorState {
  state?: "stopped" | "stopping" | "starting" | "booting" | "ready" | "failed";
  detail?: string; backend?: string; variant?: "playstore" | "aurora"; image?: string; avd?: string;
  accel?: "on" | "off"; kvm?: boolean; serial?: string; novnc_url?: string; ts?: number;
}

export interface Status {
  state: BotStateName;
  since: number;
  detail: string;
  screen: string;
  paused: boolean;
  ready: boolean;
  speed: SpeedInfo;
  progress: { filled: number; total: number };
  game: { id?: string; n?: number; box?: [number, number]; started?: number; errors?: number; waves?: number };
  adb: { serial: string; latency_ms: number; capture_ms: number; failures: number };
  device: Device;
  emulator?: EmulatorState;
  templates: number;
}

export interface Stats {
  games_started: number; games_won: number; games_failed: number; total_game_s: number; last_game_s: number;
  digits_placed: number; corrections: number; rereads: number; waves: number; failed_waves: number; errors: number;
  game_errors_red: number; total_runtime_s: number; first_seen: number; avg_game_s: number; avg_digit_s: number;
  wave_fail_rate: number; correction_rate: number; uptime_s: number;
}

export interface Machine {
  id: string; version: string; connected: boolean; lastSeen: number; connectedAt: number;
  status: Status | null; stats: Stats | null; device: Device | null;
}

export interface LogEntry { ts: number; level: string; logger: string; msg: string }

export interface Frame { data: string; mime: string; width: number; height: number; ts: number }

export type Action =
  | "ready" | "pause" | "resume" | "set_speed" | "set_stream" | "get_config" | "set_config"
  | "tap" | "swipe" | "key" | "text" | "snapshot" | "stop";

export interface Ack { id: string; ok: boolean; info: string }

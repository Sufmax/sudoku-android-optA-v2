import type { Action, Machine } from "../lib/types";
import { cn } from "../utils/cn";
import { formatDuration } from "./ui";

const TITLES: Record<string, [string, string]> = {
  wait_ready: ["Prêt quand", "tu l'es."],
  solving: ["Résout", "la grille."],
  navigate: ["Navigue", "les menus."],
  loading: ["Patiente", "un instant."],
  game_over: ["Partie", "gagnée."],
  paused: ["En", "pause."],
  wait_device: ["Cherche", "l'appareil."],
  recovering: ["Se", "rétablit."],
  observe: ["Observe", "l'écran."],
  boot: ["Démarre", "le système."],
  stopping: ["S'arrête", "proprement."],
  offline: ["Hors", "ligne."],
};

const SCREENS: Record<string, string> = {
  home: "Accueil", difficulty: "Choix de difficulté", game: "Grille", loading: "Message transitoire", overlay: "Fenêtre modale",
  game_over: "Fin de partie", loss: "Défaite", rate_popup: "Demande de note", bonus_popup: "Bonus", streak_flame: "Série — flamme",
  streak_summary: "Série quotidienne", well_done: "Bien joué", ad: "Publicité", anr: "Application figée", unknown: "Écran inconnu", solving: "Grille",
};

export function Control({ machine, command, now }: { machine: Machine | null; command: (a: Action, p?: Record<string, unknown>) => string; now: number }) {
  const st = machine?.status;
  const key = !machine?.connected ? "offline" : st?.state ?? "boot";
  const [l1, l2] = TITLES[key] ?? TITLES.boot;
  const paused = !!st?.paused;
  const ready = !!st?.ready;
  const pct = st && st.progress.total ? Math.round((st.progress.filled / st.progress.total) * 100) : 0;
  const disabled = !machine?.connected;

  return (
    <section id="pilotage" className="pb-16 pt-10 md:pb-24 md:pt-16">
      <div className="grid gap-12 md:grid-cols-12">
        <div className="md:col-span-8">
          <div className="label flex flex-wrap items-center gap-x-4 gap-y-2">
            <span className="flex items-center gap-2">
              <span className={cn("inline-block h-2.5 w-2.5 rounded-full border-2 border-ink", machine?.connected ? "live-dot bg-lime" : "bg-transparent")} />
              {machine?.id ?? "aucune machine"}
            </span>
            <span className="text-mute">· {st ? `depuis ${formatDuration(now - st.since)}` : "en attente du bot"}</span>
          </div>
          <h1 className="display mt-6 text-[19vw] md:text-[9.5rem]">
            {l1}
            <br />
            <span className={cn(key === "solving" && "text-violet", key === "wait_ready" && "underline decoration-lime decoration-[0.14em] underline-offset-[0.08em]")}>{l2}</span>
          </h1>
          <p className="mt-8 max-w-xl text-lg font-medium leading-snug text-mute md:text-xl">
            {st?.detail || "Le bot rapporte ici chaque décision : écran reconnu, action en cours, raison d'un refus d'agir."}
          </p>
        </div>

        <div className="flex flex-col justify-end gap-10 md:col-span-4">
          <div className="flex items-end gap-6">
            <button
              className="orb h-36 w-36 bg-lime md:h-44 md:w-44"
              disabled={disabled || ready}
              onClick={() => command("ready")}
              aria-label="Signaler PRÊT"
            >
              <span className="text-center">
                <span className="display block text-4xl md:text-5xl">{ready ? "OK" : "PRÊT"}</span>
                <span className="label mt-2 block">{ready ? "autonome" : "démarrer"}</span>
              </span>
            </button>
            <button
              className={cn("orb h-24 w-24 md:h-28 md:w-28", paused ? "bg-violet text-white" : "bg-paper")}
              disabled={disabled}
              onClick={() => command(paused ? "resume" : "pause")}
              aria-label={paused ? "Reprendre" : "Mettre en pause"}
            >
              {paused ? (
                <svg viewBox="0 0 24 24" className="h-9 w-9"><path d="M7 4l13 8-13 8z" fill="currentColor" /></svg>
              ) : (
                <svg viewBox="0 0 24 24" className="h-9 w-9"><path d="M6 4h4v16H6zM14 4h4v16h-4z" fill="currentColor" /></svg>
              )}
            </button>
          </div>

          <div>
            <label className="label text-mute" htmlFor="speed">Vitesse</label>
            <div className="relative mt-3">
              <select
                id="speed"
                className="select-pill w-full"
                disabled={disabled}
                value={st?.speed.mode ?? "adaptive"}
                onChange={(e) => command("set_speed", { mode: e.target.value })}
              >
                {(st?.speed.choices ?? [{ id: "adaptive", label: "Adaptatif" }]).map((c) => (
                  <option key={c.id} value={c.id}>{c.label}</option>
                ))}
              </select>
              <svg className="pointer-events-none absolute right-5 top-1/2 h-3 w-4 -translate-y-1/2" viewBox="0 0 16 10" aria-hidden="true"><path d="M1 1l7 7 7-7" stroke="currentColor" strokeWidth="2.6" fill="none" /></svg>
            </div>
            <p className="mt-3 text-sm font-semibold">
              {st?.speed.label ?? "Adaptatif › Moyen"}
              <span className="text-mute"> · vague ×{(st?.speed.wave_factor ?? 1).toFixed(2)}</span>
            </p>
          </div>
        </div>
      </div>

      <div className="mt-16 grid gap-8 md:grid-cols-12">
        <div className="md:col-span-8">
          <div className="flex items-baseline justify-between">
            <span className="label text-mute">Progression de la grille</span>
            <span className="label">{SCREENS[st?.screen ?? ""] ?? st?.screen ?? "—"}</span>
          </div>
          <div className="mt-4 h-5 w-full rounded-full border-[3px] border-ink">
            <div className="h-full rounded-full bg-ink transition-[width] duration-300" style={{ width: `${pct}%` }} />
          </div>
        </div>
        <div className="flex items-end gap-8 md:col-span-4">
          <div>
            <div className="display text-6xl tabular-nums">{st?.progress.filled ?? 0}<span className="text-mute">/{st?.progress.total ?? 0}</span></div>
            <div className="label mt-2 text-mute">cases remplies</div>
          </div>
          <div>
            <div className="display text-6xl tabular-nums">{st?.game.waves ?? 0}</div>
            <div className="label mt-2 text-mute">vagues</div>
          </div>
        </div>
      </div>
    </section>
  );
}

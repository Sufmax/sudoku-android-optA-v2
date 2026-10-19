import { useRef, useState } from "react";
import type { Action, Frame, Machine } from "../lib/types";
import { cn } from "../utils/cn";
import { Arrow, Section } from "./ui";

const FPS = [0.2, 0.5, 1, 2];

export function ScreenPanel({ frame, machine, command }: { frame: Frame | null; machine: Machine | null; command: (a: Action, p?: Record<string, unknown>) => string }) {
  const [fps, setFps] = useState(0.5);
  const [text, setText] = useState("");
  const [mark, setMark] = useState<{ x: number; y: number } | null>(null);
  const start = useRef<{ x: number; y: number; t: number } | null>(null);
  const state = machine?.status?.state;
  const manual = state === "wait_ready" || state === "paused" || state === "wait_device";

  const norm = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
  };

  const onDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!manual) return;
    start.current = { ...norm(e), t: performance.now() };
  };
  const onUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!manual || !start.current) return;
    const p = norm(e), s = start.current;
    start.current = null;
    setMark(p);
    window.setTimeout(() => setMark(null), 450);
    if (Math.hypot(p.x - s.x, p.y - s.y) < 0.02) command("tap", { x: p.x, y: p.y });
    else command("swipe", { x1: s.x, y1: s.y, x2: p.x, y2: p.y, ms: Math.max(120, Math.round(performance.now() - s.t)) });
  };

  return (
    <Section id="ecran" index="02" kicker="Écran distant" title={<>Voir.<br />Toucher.</>}>
      <div className="grid gap-10 lg:grid-cols-[minmax(0,340px)_1fr]">
        <div className="relative mx-auto w-full max-w-[340px]">
          <div className="absolute inset-0 translate-x-3 translate-y-3 rounded-[38px] bg-ink" />
          <div className="relative rounded-[38px] border-[3px] border-ink bg-paper p-3">
            <div
              className={cn("relative overflow-hidden rounded-[26px] border-2 border-ink bg-ivory touch-none select-none", manual ? "cursor-crosshair" : "cursor-not-allowed")}
              style={{ aspectRatio: frame ? `${frame.width} / ${frame.height}` : "1080 / 2340" }}
              onPointerDown={onDown}
              onPointerUp={onUp}
            >
              {frame ? (
                <img src={frame.data} alt="Écran de l'appareil Android" className="h-full w-full object-cover" draggable={false} />
              ) : (
                <div className="grid h-full place-items-center p-6 text-center">
                  <span className="label text-mute">Aucune image<br />reçue pour l'instant</span>
                </div>
              )}
              {mark && <span className="pointer-events-none absolute h-8 w-8 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-ink bg-lime" style={{ left: `${mark.x * 100}%`, top: `${mark.y * 100}%` }} />}
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-10">
          <p className="max-w-md text-lg font-medium leading-snug">
            {manual
              ? "Contrôle manuel actif. Touche l'écran pour taper, glisse pour faire défiler : connexion Google, Play Store, réglages du jeu."
              : "Le bot joue. Mets-le en pause pour reprendre la main ; il refera une observation complète à la reprise."}
          </p>

          <div>
            <div className="label text-mute">Fréquence du flux</div>
            <div className="mt-3 flex flex-wrap gap-3">
              {FPS.map((f) => (
                <button key={f} className={cn("btn", fps === f ? "btn-primary" : "btn-ghost")} onClick={() => { setFps(f); command("set_stream", { fps: f }); }}>
                  {f} img/s
                </button>
              ))}
            </div>
            <p className="mt-3 text-sm text-mute">JPEG compressé, envoyé uniquement quand quelqu'un regarde.</p>
          </div>

          <div>
            <div className="label text-mute">Touches système</div>
            <div className="mt-3 flex flex-wrap gap-3">
              {[["back", "Retour"], ["home", "Accueil"], ["recents", "Récents"]].map(([k, l]) => (
                <button key={k} className="btn btn-ghost" disabled={!manual} onClick={() => command("key", { key: k })}>{l}</button>
              ))}
            </div>
          </div>

          <form
            className="flex max-w-md gap-3"
            onSubmit={(e) => { e.preventDefault(); if (text) { command("text", { text }); setText(""); } }}
          >
            <input className="field" placeholder="Saisir du texte sur l'appareil" value={text} onChange={(e) => setText(e.target.value)} disabled={!manual} />
            <button className="btn btn-primary shrink-0" disabled={!manual || !text} aria-label="Envoyer le texte"><Arrow /></button>
          </form>
        </div>
      </div>
    </Section>
  );
}

import type { ReactNode } from "react";
import { cn } from "../utils/cn";

export function Arrow({ className }: { className?: string }) {
  return (
    <svg className={cn("h-4 w-5", className)} viewBox="0 0 20 16" fill="none" aria-hidden="true">
      <path d="M1 8h16M11 2l6 6-6 6" stroke="currentColor" strokeWidth="2.6" strokeLinecap="square" />
    </svg>
  );
}

export function Section({ index, title, kicker, children, id, className }: { index: string; title: ReactNode; kicker?: string; children: ReactNode; id: string; className?: string }) {
  return (
    <section id={id} className={cn("border-t border-line py-16 md:py-24", className)}>
      <div className="grid gap-10 md:grid-cols-12">
        <header className="md:col-span-4">
          <div className="label flex items-center gap-3 text-mute">
            <span className="text-ink">{index}</span>
            <span className="h-px w-8 bg-ink" />
            {kicker}
          </div>
          <h2 className="display mt-5 text-5xl md:text-6xl">{title}</h2>
        </header>
        <div className="md:col-span-8">{children}</div>
      </div>
    </section>
  );
}

export function Stat({ value, unit, label, accent }: { value: ReactNode; unit?: string; label: string; accent?: boolean }) {
  return (
    <div className="border-t-[3px] border-ink pt-4">
      <div className="label text-mute">{label}</div>
      <div className="mt-3 flex items-baseline gap-2">
        <span className={cn("display text-5xl md:text-6xl tabular-nums", accent && "bg-lime px-1")}>{value}</span>
        {unit && <span className="text-lg font-bold text-mute">{unit}</span>}
      </div>
    </div>
  );
}

export function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-line py-3">
      <span className="label text-mute">{k}</span>
      <span className="text-right font-semibold tabular-nums">{v}</span>
    </div>
  );
}

export function formatDuration(s: number): string {
  if (!isFinite(s) || s <= 0) return "0 s";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  if (d) return `${d} j ${h} h`;
  if (h) return `${h} h ${String(m).padStart(2, "0")}`;
  if (m) return `${m} min ${String(sec).padStart(2, "0")}`;
  return `${sec} s`;
}

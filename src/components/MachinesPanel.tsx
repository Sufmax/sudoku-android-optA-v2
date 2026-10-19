import type { Machine } from "../lib/types";
import { cn } from "../utils/cn";
import { Section, formatDuration } from "./ui";

export function MachinesPanel({ machines, selected, select, now }: { machines: Machine[]; selected: string | null; select: (id: string) => void; now: number }) {
  return (
    <Section id="machines" index="07" kicker="Flotte" title={<>Les<br />machines.</>}>
      {machines.length === 0 && <p className="text-lg font-medium text-mute">Aucun bot ne s'est encore connecté. Renseigne DASHBOARD_URL et DASHBOARD_PASSWORD dans le .env du VPS.</p>}
      <div>
        {machines.map((m) => (
          <button
            key={m.id}
            onClick={() => select(m.id)}
            className={cn("group grid w-full grid-cols-[auto_1fr_auto] items-center gap-6 border-b border-line py-6 text-left", selected === m.id && "border-b-[3px] border-ink")}
          >
            <span className={cn("h-5 w-5 rounded-full border-[3px] border-ink", m.connected ? "bg-lime" : "bg-transparent")} />
            <span>
              <span className="display block text-3xl md:text-4xl">{m.id}</span>
              <span className="label mt-2 block text-mute">
                {m.connected ? m.status?.state ?? "connecté" : "hors ligne"} · v{m.version} · vu il y a {formatDuration(now - m.lastSeen / 1000)}
              </span>
            </span>
            <span className="label transition-transform group-hover:translate-x-1">{selected === m.id ? "Affichée" : "Afficher →"}</span>
          </button>
        ))}
      </div>
    </Section>
  );
}

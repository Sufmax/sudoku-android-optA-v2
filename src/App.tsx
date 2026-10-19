import { useEffect, useMemo, useState } from "react";
import { Control } from "./components/Control";
import { ConfigPanel } from "./components/ConfigPanel";
import { DevicePanel } from "./components/DevicePanel";
import { LogPanel } from "./components/LogPanel";
import { MachinesPanel } from "./components/MachinesPanel";
import { Numbers } from "./components/Numbers";
import { ScreenPanel } from "./components/ScreenPanel";
import { useHub } from "./lib/useHub";
import { cn } from "./utils/cn";

const NAV = [
  ["pilotage", "Pilotage"],
  ["ecran", "Écran"],
  ["chiffres", "Chiffres"],
  ["appareil", "Appareil"],
  ["reglages", "Réglages"],
  ["journal", "Journal"],
  ["machines", "Machines"],
] as const;

function useNow(): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(t);
  }, []);
  return now;
}

export default function App() {
  const { state, select, command, logout } = useHub();
  const now = useNow();
  const machines = useMemo(() => Object.values(state.machines).sort((a, b) => Number(b.connected) - Number(a.connected) || a.id.localeCompare(b.id)), [state.machines]);
  const machine = state.selected ? state.machines[state.selected] ?? null : null;
  const logs = state.selected ? state.logs[state.selected] ?? [] : [];

  return (
    <div className="min-h-screen bg-ivory text-ink">
      {state.mode === "demo" && (
        <div className="border-b-[3px] border-ink bg-lime">
          <div className="mx-auto flex max-w-[1320px] flex-wrap items-center gap-x-4 gap-y-1 px-5 py-2.5 md:px-10">
            <span className="label">Mode démo</span>
            <span className="text-sm font-semibold">
              Simulation fidèle du bot (vraie config.yaml). Déployé sur le Worker, ce poste se branche sur tes machines réelles.
            </span>
          </div>
        </div>
      )}

      <header className="sticky top-0 z-20 border-b border-line bg-ivory/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-[1320px] items-center gap-6 px-5 py-4 md:px-10">
          <a href="#pilotage" className="flex items-center gap-3" aria-label="Sudoku Bot">
            <span className="grid h-9 w-9 grid-cols-3 gap-[2px] rounded-[10px] border-[3px] border-ink bg-ink p-[3px]">
              {Array.from({ length: 9 }).map((_, i) => (
                <span key={i} className={cn("rounded-[1px]", i === 4 ? "bg-lime" : i === 2 || i === 6 ? "bg-violet" : "bg-ivory")} />
              ))}
            </span>
            <span className="text-lg font-black tracking-tight">SUDOKU/BOT</span>
          </a>
          <nav className="scroll-thin ml-4 hidden gap-6 overflow-x-auto lg:flex">
            {NAV.map(([id, label]) => (
              <a key={id} href={`#${id}`} className="label whitespace-nowrap text-mute transition-colors hover:text-ink">
                {label}
              </a>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-4">
            <span className="label hidden items-center gap-2 sm:flex">
              <span className={cn("h-2.5 w-2.5 rounded-full border-2 border-ink", state.online ? "bg-violet" : "bg-transparent")} />
              {state.mode === "connecting" ? "Connexion…" : state.online ? (state.mode === "demo" ? "Démo" : "Hub en ligne") : "Hub injoignable"}
            </span>
            {machines.length > 1 && (
              <select className="select-pill !py-2 !pr-6 !text-sm" value={state.selected ?? ""} onChange={(e) => select(e.target.value)} aria-label="Machine">
                {machines.map((m) => (
                  <option key={m.id} value={m.id}>{m.id}</option>
                ))}
              </select>
            )}
            {state.mode === "live" && (
              <button className="btn btn-ghost !px-4 !py-2 !text-sm" onClick={logout}>Sortir</button>
            )}
          </div>
        </div>
        <nav className="scroll-thin flex gap-5 overflow-x-auto border-t border-line px-5 py-2.5 lg:hidden">
          {NAV.map(([id, label]) => (
            <a key={id} href={`#${id}`} className="label whitespace-nowrap text-mute">{label}</a>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-[1320px] px-5 md:px-10">
        <Control machine={machine} command={command} now={now} />
        <ScreenPanel frame={state.frame} machine={machine} command={command} />
        <Numbers machine={machine} />
        <DevicePanel machine={machine} />
        <ConfigPanel yaml={state.config} command={command} lastAck={state.lastAck} />
        <LogPanel logs={logs} />
        <MachinesPanel machines={machines} selected={state.selected} select={select} now={now} />

        <section className="border-t border-line py-20 md:py-28">
          <div className="grid gap-12 md:grid-cols-12">
            <div className="md:col-span-7">
              <div className="label text-mute">Principe</div>
              <p className="display mt-6 text-4xl md:text-6xl">
                Il voit, il vérifie,
                <br />
                puis il touche.
                <br />
                <span className="text-violet">Sinon il attend.</span>
              </p>
            </div>
            <div className="space-y-6 text-[17px] font-medium leading-relaxed md:col-span-5 md:pt-14">
              <p>
                Aucune coordonnée mémorisée : la grille, sa taille, ses blocs, le pavé et chaque bouton sont redétectés sur chaque capture.
                Deux lectures concordantes, une solution unique, jamais un chiffre initial touché.
              </p>
              <p className="text-mute">
                Sur CodeSandbox (microVM Firecracker, sans KVM), le bot pilote par ADB un émulateur Play Store ou un téléphone distant.
                Avec KVM, il embarque son propre émulateur. Le diagnostic choisit seul.
              </p>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t-[3px] border-ink">
        <div className="mx-auto flex max-w-[1320px] flex-wrap items-center justify-between gap-4 px-5 py-6 md:px-10">
          <span className="label">Sudoku Bot · v2.0</span>
          <span className="label text-mute">Python · ADB · OpenCV · Cloudflare Durable Objects</span>
        </div>
      </footer>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import type { LogEntry } from "../lib/types";
import { cn } from "../utils/cn";
import { Section } from "./ui";

const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"] as const;

export function LogPanel({ logs }: { logs: LogEntry[] }) {
  const [min, setMin] = useState<(typeof LEVELS)[number]>("INFO");
  const [follow, setFollow] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  const shown = useMemo(() => logs.filter((l) => LEVELS.indexOf((l.level === "CRITICAL" ? "ERROR" : l.level) as (typeof LEVELS)[number]) >= LEVELS.indexOf(min)).slice(-250), [logs, min]);

  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [shown, follow]);

  return (
    <Section id="journal" index="06" kicker="Flux en direct" title={<>Le<br />journal.</>}>
      <div className="flex flex-wrap items-center gap-3">
        {LEVELS.map((l) => (
          <button key={l} className={cn("btn !px-4 !py-2 !text-sm", min === l ? "btn-primary" : "btn-ghost")} onClick={() => setMin(l)}>
            {l === "WARNING" ? "WARN" : l}+
          </button>
        ))}
        <label className="label ml-auto flex cursor-pointer items-center gap-2">
          <input type="checkbox" className="h-4 w-4 accent-[#6A2CFF]" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
          Suivre
        </label>
      </div>
      <div ref={box} className="scroll-thin mt-6 h-[420px] overflow-y-auto border-y-[3px] border-ink py-3 font-mono text-[12.5px] leading-6">
        {shown.length === 0 && <div className="py-10 text-center text-mute">Aucun message à ce niveau.</div>}
        {shown.map((l, i) => (
          <div key={`${l.ts}-${i}`} className="grid grid-cols-[64px_44px_1fr] gap-3 border-b border-line/60 md:grid-cols-[72px_52px_110px_1fr]">
            <span className="text-mute tabular-nums">{new Date(l.ts * 1000).toLocaleTimeString("fr-FR")}</span>
            <span className={cn("font-semibold", l.level === "ERROR" || l.level === "CRITICAL" ? "bg-alert px-1 text-white" : l.level === "WARNING" ? "text-violet" : "text-mute")}>{l.level.slice(0, 4)}</span>
            <span className="hidden truncate text-mute md:block">{l.logger}</span>
            <span className="break-words">{l.msg}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

import { useEffect, useState } from "react";
import type { Ack, Action } from "../lib/types";
import { cn } from "../utils/cn";
import { Arrow, Section } from "./ui";

export function ConfigPanel({ yaml, command, lastAck }: { yaml: string; command: (a: Action, p?: Record<string, unknown>) => string; lastAck: Ack | null }) {
  const [draft, setDraft] = useState(yaml);
  const [pending, setPending] = useState<string | null>(null);
  const dirty = draft !== yaml;

  useEffect(() => { setDraft(yaml); }, [yaml]);
  const ack = lastAck && pending === lastAck.id ? lastAck : null;

  return (
    <Section id="reglages" index="05" kicker="Configuration" title={<>Tout est<br />réglable.</>}>
      <p className="max-w-xl text-lg font-medium leading-snug">
        Seuils de détection, délais, vagues, paliers, libellés, écrans reconnus. Validé côté bot avant écriture ; appliqué à chaud sauf
        <span className="bg-lime px-1">émulateur</span>, <span className="bg-lime px-1">machine</span> et URL du dashboard.
      </p>
      <div className="relative mt-8">
        <div className="absolute inset-0 translate-x-2.5 translate-y-2.5 rounded-3xl bg-ink" />
        <textarea
          className="scroll-thin relative block h-[460px] w-full resize-y rounded-3xl border-[3px] border-ink bg-paper p-6 font-mono text-[13px] leading-relaxed outline-none"
          spellCheck={false}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Chargement de config.yaml…"
        />
      </div>
      <div className="mt-8 flex flex-wrap items-center gap-4">
        <button className="btn btn-primary" disabled={!dirty} onClick={() => setPending(command("set_config", { yaml: draft }))}>
          Appliquer <Arrow />
        </button>
        <button className="btn btn-ghost" disabled={!dirty} onClick={() => setDraft(yaml)}>Annuler</button>
        <button className="btn btn-ghost" onClick={() => setPending(command("get_config"))}>Recharger</button>
        {ack && (
          <span className={cn("label border-l-4 py-1 pl-3", ack.ok ? "border-violet" : "border-alert")}>{ack.ok ? "Accepté" : "Refusé"} — <span className="normal-case tracking-normal">{ack.info}</span></span>
        )}
      </div>
    </Section>
  );
}

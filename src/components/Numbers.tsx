import type { Machine } from "../lib/types";
import { Row, Section, Stat, formatDuration } from "./ui";

export function Numbers({ machine }: { machine: Machine | null }) {
  const s = machine?.stats;
  const success = s && s.games_started ? Math.round((s.games_won / s.games_started) * 100) : 0;
  return (
    <Section id="chiffres" index="03" kicker="Statistiques" title={<>Les<br />chiffres.</>}>
      <div className="grid grid-cols-2 gap-x-8 gap-y-12 md:grid-cols-3">
        <Stat label="Parties jouées" value={s?.games_started ?? 0} />
        <Stat label="Terminées" value={s?.games_won ?? 0} accent />
        <Stat label="Réussite" value={success} unit="%" />
        <Stat label="Temps moyen" value={Math.round(s?.avg_game_s ?? 0)} unit="s / partie" />
        <Stat label="Chiffres placés" value={(s?.digits_placed ?? 0).toLocaleString("fr-FR")} />
        <Stat label="Par chiffre" value={(s?.avg_digit_s ?? 0).toFixed(2)} unit="s" />
      </div>
      <div className="mt-14 grid gap-x-12 md:grid-cols-2">
        <div>
          <Row k="Uptime (session)" v={formatDuration(s?.uptime_s ?? 0)} />
          <Row k="Temps total d'exécution" v={formatDuration(s?.total_runtime_s ?? 0)} />
          <Row k="Dernière partie" v={formatDuration(s?.last_game_s ?? 0)} />
          <Row k="Parties échouées" v={s?.games_failed ?? 0} />
        </div>
        <div>
          <Row k="Taux d'échec des vagues" v={`${((s?.wave_fail_rate ?? 0) * 100).toFixed(1)} %`} />
          <Row k="Taux de correction" v={`${((s?.correction_rate ?? 0) * 100).toFixed(1)} %`} />
          <Row k="Relectures" v={s?.rereads ?? 0} />
          <Row k="Erreurs rencontrées" v={`${s?.errors ?? 0} · rouges ${s?.game_errors_red ?? 0}`} />
        </div>
      </div>
    </Section>
  );
}

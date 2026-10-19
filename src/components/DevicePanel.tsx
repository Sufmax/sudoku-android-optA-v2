import type { Machine } from "../lib/types";
import { Row, Section } from "./ui";

export function DevicePanel({ machine }: { machine: Machine | null }) {
  const d = machine?.device ?? machine?.status?.device;
  const adb = machine?.status?.adb;
  const emu = machine?.status?.emulator;
  const emuState: Record<string, string> = { ready: "prêt", booting: "démarrage…", starting: "lancement…", failed: "échec", stopped: "arrêté", stopping: "arrêt…" };
  return (
    <Section id="appareil" index="04" kicker="Téléphone émulé" title={<>L'appa&shy;reil.</>}>
      <div className="grid gap-12 md:grid-cols-2">
        <div>
          <div className="display text-4xl md:text-5xl">{d?.model || "—"}</div>
          <p className="mt-3 font-semibold text-mute">Android {d?.android ?? "?"} · API {d?.sdk ?? "?"}</p>
          <div className="mt-8">
            <Row k="Résolution" v={d ? `${d.width} × ${d.height}` : "—"} />
            <Row k="Densité" v={d ? `${d.density} dpi` : "—"} />
            <Row k="Mémoire" v={d ? `${(d.ram_mb / 1024).toFixed(1)} Go` : "—"} />
            <Row k="Batterie simulée" v={d && d.battery >= 0 ? `${d.battery} %` : "—"} />
          </div>
        </div>
        <div className="md:pt-24">
          <Row k="Émulateur" v={emu?.state ? emuState[emu.state] ?? emu.state : "—"} />
          <Row k="Accélération" v={emu?.accel ? (emu.accel === "on" ? "KVM (matérielle)" : "logicielle (sans KVM)") : "—"} />
          <Row k="Image" v={emu?.variant ? (emu.variant === "playstore" ? "Google Play" : "AOSP + Aurora Store") : "—"} />
          <Row k="AVD" v={emu?.avd ?? "—"} />
          <Row k="Liaison ADB" v={adb ? (adb.failures ? `${adb.failures} échec(s)` : "stable") : "—"} />
          <Row k="Série" v={adb?.serial ?? "—"} />
          <Row k="Latence d'appui" v={adb ? `${adb.latency_ms} ms` : "—"} />
          <Row k="Capture d'écran" v={adb ? `${adb.capture_ms} ms` : "—"} />
          <Row k="Gabarits appris" v={machine?.status?.templates ?? 0} />
          <Row k="Version du bot" v={machine?.version ?? "—"} />
          {emu?.novnc_url ? (
            <a href={emu.novnc_url} target="_blank" rel="noreferrer"
              className="mt-8 inline-flex items-center gap-3 rounded-full border-[3px] border-ink px-6 py-3 font-extrabold uppercase tracking-[0.12em] text-sm transition-transform active:translate-x-[2px] active:translate-y-[2px]">
              Écran noVNC <span aria-hidden>↗</span>
            </a>
          ) : null}
        </div>
      </div>
    </Section>
  );
}

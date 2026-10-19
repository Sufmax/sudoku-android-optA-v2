// Connexion au Durable Object « Hub » (WebSocket authentifié par cookie) avec repli en mode démo.
import { useCallback, useEffect, useRef, useState } from "react";
import { DemoBot } from "./demo";
import type { Ack, Action, Frame, LogEntry, Machine } from "./types";

export type Mode = "connecting" | "live" | "demo";

export interface HubState {
  mode: Mode;
  online: boolean;
  machines: Record<string, Machine>;
  selected: string | null;
  logs: Record<string, LogEntry[]>;
  frame: Frame | null;
  config: string;
  lastAck: Ack | null;
}

const LOG_MAX = 400;

export function useHub() {
  const [state, setState] = useState<HubState>({ mode: "connecting", online: false, machines: {}, selected: null, logs: {}, frame: null, config: "", lastAck: null });
  const ws = useRef<WebSocket | null>(null);
  const demo = useRef<DemoBot | null>(null);
  const selectedRef = useRef<string | null>(null);

  const pushLog = useCallback((machine: string, entry: LogEntry) => {
    setState((s) => {
      const list = [...(s.logs[machine] || []), entry].slice(-LOG_MAX);
      return { ...s, logs: { ...s.logs, [machine]: list } };
    });
  }, []);

  const upsertMachine = useCallback((m: Machine) => {
    setState((s) => {
      const selected = s.selected ?? m.id;
      if (selectedRef.current === null) {
        selectedRef.current = selected;
        ws.current?.send(JSON.stringify({ type: "subscribe", machine: selected }));
      }
      return { ...s, machines: { ...s.machines, [m.id]: m }, selected };
    });
  }, []);

  const startDemo = useCallback(() => {
    if (demo.current) return;
    setState((s) => ({ ...s, mode: "demo", online: true }));
    demo.current = new DemoBot({
      machine: (m) => upsertMachine(m),
      log: (e) => pushLog("csb-01", e),
      frame: (f) => setState((s) => ({ ...s, frame: f })),
      ack: (a) => setState((s) => ({ ...s, lastAck: a })),
      config: (yaml) => setState((s) => ({ ...s, config: yaml })),
    });
    demo.current.start();
  }, [pushLog, upsertMachine]);

  useEffect(() => {
    let closed = false;
    let retry = 1000;
    let timer: number | undefined;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const sock = new WebSocket(`${proto}://${location.host}/ws/client`);
      ws.current = sock;
      sock.onopen = () => { retry = 1000; setState((s) => ({ ...s, mode: "live", online: true })); };
      sock.onclose = () => {
        setState((s) => ({ ...s, online: false }));
        if (!closed) timer = window.setTimeout(connect, (retry = Math.min(retry * 2, 30000)));
      };
      sock.onmessage = (ev) => {
        let msg: Record<string, any>;
        try { msg = JSON.parse(ev.data); } catch { return; }
        switch (msg.type) {
          case "snapshot":
            (msg.machines as Machine[]).forEach(upsertMachine);
            setState((s) => ({ ...s, logs: { ...s.logs, ...(msg.logs || {}) } }));
            break;
          case "machine": upsertMachine(msg.machine); break;
          case "log": pushLog(msg.machine, msg.entry); break;
          case "frame": setState((s) => ({ ...s, frame: { data: `data:${msg.mime};base64,${msg.data}`, mime: msg.mime, width: msg.width, height: msg.height, ts: msg.ts } })); break;
          case "config": setState((s) => ({ ...s, config: msg.yaml })); break;
          case "ack": setState((s) => ({ ...s, lastAck: { id: msg.id, ok: msg.ok, info: msg.info } })); break;
        }
      };
    };

    // Servi par le Worker ? /api/session répond 200 (session) ou 401 (→ /login). Sinon : aperçu → démo.
    fetch("/api/session", { credentials: "same-origin" })
      .then((r) => {
        if (r.status === 401) { location.href = "/login"; return; }
        const isJson = (r.headers.get("Content-Type") || "").includes("application/json");
        if (r.ok && isJson) connect();
        else startDemo();
      })
      .catch(() => startDemo());

    return () => {
      closed = true;
      window.clearTimeout(timer);
      ws.current?.close();
      demo.current?.stop();
    };
  }, [pushLog, startDemo, upsertMachine]);

  const select = useCallback((id: string) => {
    selectedRef.current = id;
    setState((s) => ({ ...s, selected: id, frame: null }));
    ws.current?.send(JSON.stringify({ type: "subscribe", machine: id }));
  }, []);

  const command = useCallback((action: Action, params: Record<string, unknown> = {}) => {
    const id = crypto.randomUUID();
    const machine = selectedRef.current;
    if (demo.current) demo.current.command(action, params, id);
    else if (ws.current?.readyState === WebSocket.OPEN && machine) ws.current.send(JSON.stringify({ type: "command", machine, id, action, params }));
    return id;
  }, []);

  const logout = useCallback(async () => {
    if (state.mode !== "live") return;
    await fetch("/api/logout", { method: "POST" });
    location.href = "/login";
  }, [state.mode]);

  return { state, select, command, logout };
}

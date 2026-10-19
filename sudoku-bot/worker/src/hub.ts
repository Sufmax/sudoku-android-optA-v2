/**
 * Durable Object « Hub » : état temps réel de toutes les machines, relais des commandes,
 * des journaux et du flux d'écran. Utilise l'API WebSocket Hibernation (coût nul au repos).
 */
import type { Env } from "./auth";

interface Machine {
  id: string;
  version: string;
  connected: boolean;
  lastSeen: number;
  connectedAt: number;
  status: Record<string, unknown> | null;
  stats: Record<string, unknown> | null;
  device: Record<string, unknown> | null;
  config: string | null;
}

type Attachment = { role: "bot"; machine: string } | { role: "client"; machine: string | null };

const LOG_KEEP = 300;
const LOGIN_WINDOW_MS = 15 * 60 * 1000;
const ACTIONS = new Set(["ready", "pause", "resume", "set_speed", "set_stream", "get_config", "set_config", "tap", "swipe", "key", "text", "snapshot", "stop"]);

export class Hub implements DurableObject {
  private machines = new Map<string, Machine>();
  private logs = new Map<string, unknown[]>();
  private frames = new Map<string, unknown>();
  private loaded = false;

  constructor(private state: DurableObjectState, private env: Env) {}

  private async load(): Promise<void> {
    if (this.loaded) return;
    const stored = await this.state.storage.list<Machine>({ prefix: "machine:" });
    for (const m of stored.values()) this.machines.set(m.id, { ...m, connected: false });
    for (const ws of this.state.getWebSockets()) {
      const att = ws.deserializeAttachment() as Attachment | null;
      if (att?.role === "bot" && this.machines.has(att.machine)) this.machines.get(att.machine)!.connected = true;
    }
    const logs = await this.state.storage.list<unknown[]>({ prefix: "logs:" });
    for (const [k, v] of logs) this.logs.set(k.slice(5), v);
    this.loaded = true;
  }

  private async save(m: Machine): Promise<void> {
    await this.state.storage.put(`machine:${m.id}`, m);
  }

  private clients(): WebSocket[] {
    return this.state.getWebSockets("client");
  }

  private botSocket(id: string): WebSocket | undefined {
    return this.state.getWebSockets(`bot:${id}`)[0];
  }

  private send(ws: WebSocket, msg: unknown): void {
    try {
      ws.send(JSON.stringify(msg));
    } catch {
      /* socket fermée entre-temps : ignorée */
    }
  }

  private broadcast(msg: unknown, machine?: string): void {
    const data = JSON.stringify(msg);
    for (const ws of this.clients()) {
      const att = ws.deserializeAttachment() as Attachment;
      if (machine && att.role === "client" && att.machine && att.machine !== machine) continue;
      try { ws.send(data); } catch { /* ignorée */ }
    }
  }

  private publicMachine(m: Machine) {
    const { config: _c, ...rest } = m;
    return rest;
  }

  private updateViewers(): void {
    const counts = new Map<string, number>();
    for (const ws of this.clients()) {
      const att = ws.deserializeAttachment() as Attachment;
      if (att.machine) counts.set(att.machine, (counts.get(att.machine) || 0) + 1);
    }
    for (const id of this.machines.keys()) {
      const bot = this.botSocket(id);
      if (bot) this.send(bot, { type: "viewers", count: counts.get(id) || 0 });
    }
  }

  async fetch(req: Request): Promise<Response> {
    await this.load();
    const url = new URL(req.url);

    if (url.pathname === "/internal/login-gate" || url.pathname === "/internal/login-ok") {
      const ip = url.searchParams.get("ip") || "unknown";
      const key = `login:${ip}`;
      const now = Date.now();
      const rec = (await this.state.storage.get<{ n: number; since: number }>(key)) || { n: 0, since: now };
      if (url.pathname === "/internal/login-ok") { await this.state.storage.delete(key); return new Response("ok"); }
      if (now - rec.since > LOGIN_WINDOW_MS) { rec.n = 0; rec.since = now; }
      rec.n += 1;
      await this.state.storage.put(key, rec);
      return new Response(null, { status: rec.n > Number(this.env.MAX_LOGIN_ATTEMPTS || 10) ? 429 : 204 });
    }

    if (url.pathname === "/api/machines") {
      return Response.json([...this.machines.values()].map((m) => this.publicMachine(m)));
    }

    if (url.pathname === "/ws/bot" || url.pathname === "/ws/client") {
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      if (url.pathname === "/ws/bot") {
        const id = (url.searchParams.get("machine") || "").replace(/[^a-zA-Z0-9_.-]/g, "").slice(0, 40);
        if (!id) return new Response("machine manquante", { status: 400 });
        for (const old of this.state.getWebSockets(`bot:${id}`)) old.close(4000, "remplacée par une nouvelle connexion");
        this.state.acceptWebSocket(server, ["bot", `bot:${id}`]);
        server.serializeAttachment({ role: "bot", machine: id } satisfies Attachment);
        const m: Machine = this.machines.get(id) || { id, version: "?", connected: true, lastSeen: Date.now(), connectedAt: Date.now(), status: null, stats: null, device: null, config: null };
        m.connected = true; m.connectedAt = Date.now(); m.lastSeen = Date.now();
        m.version = req.headers.get("X-Bot-Version") || m.version;
        this.machines.set(id, m);
        await this.save(m);
        this.broadcast({ type: "machine", machine: this.publicMachine(m) });
        queueMicrotask(() => this.updateViewers());
      } else {
        this.state.acceptWebSocket(server, ["client"]);
        server.serializeAttachment({ role: "client", machine: null } satisfies Attachment);
        this.send(server, {
          type: "snapshot",
          machines: [...this.machines.values()].map((m) => this.publicMachine(m)),
          logs: Object.fromEntries(this.logs),
        });
      }
      return new Response(null, { status: 101, webSocket: client });
    }
    return new Response("introuvable", { status: 404 });
  }

  async webSocketMessage(ws: WebSocket, raw: string | ArrayBuffer): Promise<void> {
    await this.load();
    const att = ws.deserializeAttachment() as Attachment;
    let msg: Record<string, any>;
    try {
      msg = JSON.parse(typeof raw === "string" ? raw : new TextDecoder().decode(raw));
    } catch {
      return;
    }
    if (att.role === "bot") return this.fromBot(att.machine, msg);
    return this.fromClient(ws, att, msg);
  }

  private async fromBot(id: string, msg: Record<string, any>): Promise<void> {
    const m = this.machines.get(id);
    if (!m) return;
    m.lastSeen = Date.now();
    switch (msg.type) {
      case "hello":
        m.version = String(msg.version || m.version);
        break;
      case "status":
        m.status = msg.status ?? null;
        break;
      case "metrics":
        m.stats = msg.stats ?? null;
        break;
      case "device":
        m.device = msg.device ?? null;
        break;
      case "config":
        m.config = String(msg.yaml ?? "");
        this.broadcast({ type: "config", machine: id, yaml: m.config }, id);
        await this.save(m);
        return;
      case "frame":
        this.frames.set(id, msg);
        this.broadcast({ ...msg, machine: id }, id);
        return;
      case "log": {
        const list = this.logs.get(id) || [];
        list.push(msg.entry);
        if (list.length > LOG_KEEP) list.splice(0, list.length - LOG_KEEP);
        this.logs.set(id, list);
        this.broadcast({ type: "log", machine: id, entry: msg.entry }, id);
        if (list.length % 25 === 0) await this.state.storage.put(`logs:${id}`, list);
        return;
      }
      case "ack":
        this.broadcast({ type: "ack", machine: id, id: msg.id, ok: msg.ok, info: msg.info }, id);
        return;
      default:
        return;
    }
    this.broadcast({ type: "machine", machine: this.publicMachine(m) });
    await this.save(m);
  }

  private async fromClient(ws: WebSocket, att: Attachment & { role: "client" }, msg: Record<string, any>): Promise<void> {
    if (msg.type === "ping") return this.send(ws, { type: "pong", ts: Date.now() });
    if (msg.type === "subscribe") {
      const id = typeof msg.machine === "string" && this.machines.has(msg.machine) ? msg.machine : null;
      ws.serializeAttachment({ role: "client", machine: id } satisfies Attachment);
      if (id) {
        const frame = this.frames.get(id);
        if (frame) this.send(ws, frame);
        const cfg = this.machines.get(id)!.config;
        if (cfg) this.send(ws, { type: "config", machine: id, yaml: cfg });
      }
      this.updateViewers();
      return;
    }
    if (msg.type === "command") {
      const id = String(msg.machine || "");
      const action = String(msg.action || "");
      const cid = String(msg.id || crypto.randomUUID());
      if (!ACTIONS.has(action)) return this.send(ws, { type: "ack", machine: id, id: cid, ok: false, info: "action inconnue" });
      const bot = this.botSocket(id);
      if (!bot) return this.send(ws, { type: "ack", machine: id, id: cid, ok: false, info: "machine hors ligne" });
      this.send(bot, { v: 1, type: "command", id: cid, action, params: msg.params || {} });
    }
  }

  async webSocketClose(ws: WebSocket): Promise<void> {
    await this.load();
    const att = ws.deserializeAttachment() as Attachment | null;
    if (att?.role === "bot") {
      const stillOpen = this.state.getWebSockets(`bot:${att.machine}`).some((s) => s !== ws);
      const m = this.machines.get(att.machine);
      if (m && !stillOpen) {
        m.connected = false;
        m.lastSeen = Date.now();
        await this.save(m);
        const list = this.logs.get(att.machine);
        if (list) await this.state.storage.put(`logs:${att.machine}`, list);
        this.broadcast({ type: "machine", machine: this.publicMachine(m) });
      }
    } else {
      this.updateViewers();
    }
  }

  async webSocketError(ws: WebSocket): Promise<void> {
    await this.webSocketClose(ws);
  }
}

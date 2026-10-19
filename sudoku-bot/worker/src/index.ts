/** Point d'entrée du Worker : HTTPS, authentification, routage vers le Durable Object et les assets. */
import { clearCookie, COOKIE, createSession, Env, readCookie, safeEqual, sessionCookie, verifySession } from "./auth";
import { loginPage } from "./login";
export { Hub } from "./hub";

const SECURITY_HEADERS: Record<string, string> = {
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Frame-Options": "DENY",
};

function withHeaders(res: Response, extra: Record<string, string> = {}): Response {
  const out = new Response(res.body, res);
  for (const [k, v] of Object.entries({ ...SECURITY_HEADERS, ...extra })) out.headers.set(k, v);
  return out;
}

function json(data: unknown, status = 200, extra: Record<string, string> = {}): Response {
  return withHeaders(new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } }), extra);
}

function hub(env: Env): DurableObjectStub {
  return env.HUB.get(env.HUB.idFromName("hub"));
}

async function handleLogin(req: Request, env: Env): Promise<Response> {
  if (!env.DASHBOARD_PASSWORD) return json({ error: "DASHBOARD_PASSWORD non configuré" }, 500);
  const ip = req.headers.get("CF-Connecting-IP") || "unknown";
  const gate = await hub(env).fetch(`https://hub/internal/login-gate?ip=${encodeURIComponent(ip)}`, { method: "POST" });
  const isForm = (req.headers.get("Content-Type") || "").includes("application/x-www-form-urlencoded");
  if (gate.status === 429) return isForm ? loginPage("Trop de tentatives. Réessaie dans 15 minutes.") : json({ error: "trop de tentatives" }, 429);
  let password = "";
  if (isForm) password = String((await req.formData()).get("password") || "");
  else password = String(((await req.json().catch(() => ({}))) as { password?: string }).password || "");
  if (!(await safeEqual(password, env.DASHBOARD_PASSWORD))) {
    await new Promise((r) => setTimeout(r, 700));
    return isForm ? loginPage("Mot de passe incorrect.") : json({ error: "mot de passe incorrect" }, 401);
  }
  await hub(env).fetch(`https://hub/internal/login-ok?ip=${encodeURIComponent(ip)}`, { method: "POST" });
  const { token, maxAge } = await createSession(env);
  const cookie = sessionCookie(token, maxAge);
  if (isForm) return withHeaders(new Response(null, { status: 303, headers: { Location: "/", "Set-Cookie": cookie } }));
  return json({ ok: true }, 200, { "Set-Cookie": cookie });
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    const local = url.hostname === "localhost" || url.hostname === "127.0.0.1";
    if (url.protocol === "http:" && !local) {
      url.protocol = "https:";
      return Response.redirect(url.toString(), 301);
    }

    // Canal du bot : authentifié par le mot de passe en en-tête (connexion sortante depuis le VPS)
    if (url.pathname === "/ws/bot") {
      const key = req.headers.get("X-Bot-Key") || "";
      if (!env.DASHBOARD_PASSWORD || !(await safeEqual(key, env.DASHBOARD_PASSWORD))) return new Response("unauthorized", { status: 401 });
      if (req.headers.get("Upgrade") !== "websocket") return new Response("websocket attendu", { status: 426 });
      return hub(env).fetch(req);
    }

    if (url.pathname === "/login" && req.method === "GET") return loginPage();
    if (url.pathname === "/api/login" && req.method === "POST") return handleLogin(req, env);
    if (url.pathname === "/api/logout" && req.method === "POST") return json({ ok: true }, 200, { "Set-Cookie": clearCookie() });

    const authed = await verifySession(env, readCookie(req, COOKIE));
    if (!authed) {
      if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")) return json({ error: "non authentifié" }, 401);
      return withHeaders(new Response(null, { status: 302, headers: { Location: "/login" } }));
    }

    if (url.pathname === "/api/session") return json({ ok: true });
    if (url.pathname === "/ws/client") {
      if (req.headers.get("Upgrade") !== "websocket") return new Response("websocket attendu", { status: 426 });
      const origin = req.headers.get("Origin");
      if (origin && new URL(origin).host !== url.host) return new Response("origine refusée", { status: 403 });
      return hub(env).fetch(req);
    }
    if (url.pathname.startsWith("/api/")) return hub(env).fetch(req);

    const asset = await env.ASSETS.fetch(req);
    return withHeaders(asset, { "Cache-Control": url.pathname.startsWith("/assets/") ? "public, max-age=31536000, immutable" : "no-store" });
  },
} satisfies ExportedHandler<Env>;

/** Authentification : mot de passe unique (secret) → jeton de session HMAC-SHA256 en cookie HttpOnly. */
export interface Env {
  HUB: DurableObjectNamespace;
  ASSETS: Fetcher;
  DASHBOARD_PASSWORD: string;
  SESSION_SECRET?: string;
  SESSION_TTL_S?: string;
  MAX_LOGIN_ATTEMPTS?: string;
}

const enc = new TextEncoder();
export const COOKIE = "sudoku_sid";

function b64url(buf: ArrayBuffer | Uint8Array): string {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromB64url(s: string): Uint8Array {
  const pad = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  const bin = atob(pad);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

async function hmacKey(env: Env): Promise<CryptoKey> {
  const material = env.SESSION_SECRET || `session:${env.DASHBOARD_PASSWORD}`;
  const raw = await crypto.subtle.digest("SHA-256", enc.encode(material));
  return crypto.subtle.importKey("raw", raw, { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

/** Comparaison à temps constant (via HMAC des deux valeurs). */
export async function safeEqual(a: string, b: string): Promise<boolean> {
  const key = await crypto.subtle.importKey("raw", crypto.getRandomValues(new Uint8Array(32)), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const [ha, hb] = await Promise.all([crypto.subtle.sign("HMAC", key, enc.encode(a)), crypto.subtle.sign("HMAC", key, enc.encode(b))]);
  const x = new Uint8Array(ha), y = new Uint8Array(hb);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0 && a.length === b.length;
}

export async function createSession(env: Env): Promise<{ token: string; maxAge: number }> {
  const maxAge = Number(env.SESSION_TTL_S || 604800);
  const payload = b64url(enc.encode(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + maxAge, n: b64url(crypto.getRandomValues(new Uint8Array(9))) })));
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(env), enc.encode(payload));
  return { token: `${payload}.${b64url(sig)}`, maxAge };
}

export async function verifySession(env: Env, token: string | null): Promise<boolean> {
  if (!token || !token.includes(".")) return false;
  const [payload, sig] = token.split(".", 2);
  try {
    const ok = await crypto.subtle.verify("HMAC", await hmacKey(env), fromB64url(sig), enc.encode(payload));
    if (!ok) return false;
    const data = JSON.parse(new TextDecoder().decode(fromB64url(payload))) as { exp: number };
    return typeof data.exp === "number" && data.exp > Date.now() / 1000;
  } catch {
    return false;
  }
}

export function readCookie(req: Request, name: string): string | null {
  const header = req.headers.get("Cookie") || "";
  for (const part of header.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return decodeURIComponent(v.join("="));
  }
  return null;
}

export function sessionCookie(token: string, maxAge: number): string {
  return `${COOKIE}=${encodeURIComponent(token)}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=${maxAge}`;
}

export function clearCookie(): string {
  return `${COOKIE}=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0`;
}

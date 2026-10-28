const HOP_BY_HOP = [
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];

const DROPPED_REQUEST_HEADERS = ["authorization", "cookie", "host", "content-length", ...HOP_BY_HOP];

const LOOPBACK_HOST = /^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/i;

function isUnsafeSegment(segment: string): boolean {
  return (
    segment === "" ||
    segment === "." ||
    segment === ".." ||
    segment.includes("/") ||
    segment.includes("\\")
  );
}

function safeDecode(segment: string): string | null {
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

/** Only `api/v1/...` may pass; the gateway and anything that could traverse out of it may not. */
export function isAllowedPath(segments: string[]): boolean {
  if (segments.length < 3 || segments[0] !== "api" || segments[1] !== "v1") return false;
  return segments.every((segment) => {
    const decoded = safeDecode(segment);
    return decoded !== null && !isUnsafeSegment(segment) && !isUnsafeSegment(decoded);
  });
}

export function buildForwardHeaders(incoming: Headers, token: string): Headers {
  const listed = (incoming.get("connection") ?? "")
    .split(",")
    .map((name) => name.trim().toLowerCase())
    .filter(Boolean);
  const dropped = new Set([...DROPPED_REQUEST_HEADERS, ...listed]);
  const out = new Headers();
  incoming.forEach((value, name) => {
    if (!dropped.has(name.toLowerCase())) out.set(name, value);
  });
  out.set("authorization", `Bearer ${token}`);
  return out;
}

/** The response leaves the proxy re-framed and already decoded by `fetch`. */
export function buildResponseHeaders(upstream: Headers): Headers {
  const dropped = new Set([...HOP_BY_HOP, "content-length", "content-encoding", "set-cookie"]);
  const out = new Headers();
  upstream.forEach((value, name) => {
    if (!dropped.has(name.toLowerCase())) out.set(name, value);
  });
  return out;
}

/**
 * The proxy attaches the local token, so it must only serve this app's own pages: a loopback
 * `Host` (blocks DNS rebinding) and no cross-site browser origin (blocks CSRF).
 */
export function isTrustedRequest(headers: Headers): boolean {
  const host = headers.get("host");
  if (host === null || !LOOPBACK_HOST.test(host)) return false;
  const site = headers.get("sec-fetch-site");
  if (site !== null && site !== "same-origin" && site !== "none") return false;
  const origin = headers.get("origin");
  if (origin === null) return true;
  try {
    return new URL(origin).host.toLowerCase() === host.toLowerCase();
  } catch {
    return false;
  }
}

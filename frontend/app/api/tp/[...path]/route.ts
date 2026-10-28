import { NextRequest, NextResponse } from "next/server";

import {
  buildForwardHeaders,
  buildResponseHeaders,
  isAllowedPath,
  isTrustedRequest,
} from "@/lib/proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const DEFAULT_API_URL = "http://127.0.0.1:8787";
const UPSTREAM_TIMEOUT_MS = 30_000;

type Context = { params: Promise<{ path: string[] }> };

function errorResponse(status: number, code: string, message: string): NextResponse {
  return NextResponse.json({ error: { code, message, details: null } }, { status });
}

async function forward(request: NextRequest, context: Context): Promise<Response> {
  if (!isTrustedRequest(request.headers)) {
    return errorResponse(403, "forbidden", "The API proxy only serves this app on a loopback host.");
  }
  const { path: segments } = await context.params;
  if (!isAllowedPath(segments)) {
    return errorResponse(404, "not_found", "Only /api/v1 paths are available through this proxy.");
  }
  const token = process.env.TOKENPILOT_LOCAL_TOKEN;
  if (!token) {
    return errorResponse(
      500,
      "proxy_not_configured",
      "TOKENPILOT_LOCAL_TOKEN is not set for the web server. Start it with `make dev-web`.",
    );
  }
  const base = (process.env.TOKENPILOT_API_URL || DEFAULT_API_URL).replace(/\/+$/, "");
  const target = `${base}/${segments.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers: buildForwardHeaders(request.headers, token),
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      return errorResponse(504, "upstream_timeout", "The TokenPilot API did not answer in time.");
    }
    return errorResponse(502, "upstream_unreachable", "The TokenPilot API is not reachable.");
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: buildResponseHeaders(upstream.headers),
  });
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const PUT = forward;

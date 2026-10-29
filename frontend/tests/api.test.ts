import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiDelete, apiGet, apiSend } from "@/lib/api";

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiGet", () => {
  it("calls the proxy with query params and returns the body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: 1 }, 200));
    vi.stubGlobal("fetch", fetchMock);

    const body = await apiGet<{ ok: number }>("api/v1/usage/summary", { bucket: "day" });

    expect(body).toEqual({ ok: 1 });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/tp/api/v1/usage/summary?bucket=day",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("throws ApiError from a structured error body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ error: { code: "validation_error", message: "bad from", details: [] } }, 422),
      ),
    );

    const err = await apiGet("api/v1/usage/summary").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ code: "validation_error", message: "bad from", status: 422 });
  });

  it("throws ApiError for an unstructured failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 502 })));

    const err = await apiGet("api/v1/projects").catch((e: unknown) => e);

    expect(err).toMatchObject({ code: "http_error", status: 502 });
  });
});

describe("apiSend", () => {
  it("sends a JSON body with the given method", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: "p1" }, 200));
    vi.stubGlobal("fetch", fetchMock);

    await apiSend("PATCH", "api/v1/projects/p1", { name: "x" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/tp/api/v1/projects/p1",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ name: "x" }) }),
    );
  });
});

describe("apiDelete", () => {
  it("sends DELETE with query params and returns the body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ deleted_events: 1 }, 200));
    vi.stubGlobal("fetch", fetchMock);

    const body = await apiDelete<{ deleted_events: number }>("api/v1/data", {
      before: "2026-06-01T00:00:00.000Z",
    });

    expect(body).toEqual({ deleted_events: 1 });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/tp/api/v1/data?before=2026-06-01T00%3A00%3A00.000Z",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});

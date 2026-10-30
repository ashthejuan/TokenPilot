import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { buildForwardHeaders, isAllowedPath, isTrustedRequest } from "@/lib/proxy";

describe("tp proxy route methods", () => {
  it("forwards DELETE as well as GET/POST/PATCH/PUT", () => {
    const source = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../app/api/tp/[...path]/route.ts"),
      "utf8",
    );
    for (const method of ["GET", "POST", "PATCH", "PUT", "DELETE"] as const) {
      expect(source).toMatch(new RegExp(`export const ${method}\\s*=\\s*forward`));
    }
  });
});

describe("toaster wiring", () => {
  it("mounts Sonner without next-themes and keeps a light token theme", () => {
    const root = join(dirname(fileURLToPath(import.meta.url)), "..");
    const sonner = readFileSync(join(root, "components/ui/sonner.tsx"), "utf8");
    const layout = readFileSync(join(root, "app/layout.tsx"), "utf8");
    expect(sonner).not.toMatch(/next-themes/);
    expect(sonner).toMatch(/theme="light"/);
    expect(layout).toMatch(/<Toaster\s*\/>/);
  });
});

describe("isAllowedPath", () => {
  it("allows the versioned REST API", () => {
    expect(isAllowedPath(["api", "v1", "usage", "summary"])).toBe(true);
    expect(isAllowedPath(["api", "v1", "projects"])).toBe(true);
  });

  it("rejects the gateway, other versions, and empty paths", () => {
    expect(isAllowedPath(["gateway", "v1", "chat", "completions"])).toBe(false);
    expect(isAllowedPath(["api", "v2", "x"])).toBe(false);
    expect(isAllowedPath(["api"])).toBe(false);
    expect(isAllowedPath([])).toBe(false);
    expect(isAllowedPath(["api", "v1", ""])).toBe(false);
  });

  it("rejects traversal, raw or encoded", () => {
    expect(isAllowedPath(["api", "v1", "..", "gateway"])).toBe(false);
    expect(isAllowedPath(["api", "v1", "%2e%2e", "x"])).toBe(false);
    expect(isAllowedPath(["api", "v1", ".", "x"])).toBe(false);
    expect(isAllowedPath(["api", "v1", "%2E", "x"])).toBe(false);
    expect(isAllowedPath(["api", "v1", "a/b"])).toBe(false);
    expect(isAllowedPath(["api", "v1", "a%2fb"])).toBe(false);
    expect(isAllowedPath(["api", "v1", "a\\b"])).toBe(false);
    expect(isAllowedPath(["api", "v1", "a%5Cb"])).toBe(false);
    expect(isAllowedPath(["api", "v1", "%E0%A4%A"])).toBe(false);
  });
});

describe("buildForwardHeaders", () => {
  it("replaces caller credentials with the local token", () => {
    const incoming = new Headers({
      authorization: "Bearer evil",
      cookie: "session=abc",
      host: "127.0.0.1:3000",
      connection: "keep-alive, x-drop-me",
      "x-drop-me": "1",
      "keep-alive": "timeout=5",
      "transfer-encoding": "chunked",
      "content-type": "application/json",
      accept: "application/json",
    });

    const out = buildForwardHeaders(incoming, "t");

    expect(out.get("authorization")).toBe("Bearer t");
    expect(out.get("cookie")).toBeNull();
    expect(out.get("host")).toBeNull();
    expect(out.get("connection")).toBeNull();
    expect(out.get("keep-alive")).toBeNull();
    expect(out.get("transfer-encoding")).toBeNull();
    expect(out.get("x-drop-me")).toBeNull();
    expect(out.get("content-type")).toBe("application/json");
    expect(out.get("accept")).toBe("application/json");
  });
});

describe("isTrustedRequest", () => {
  it("accepts same-origin loopback requests", () => {
    expect(isTrustedRequest(new Headers({ host: "127.0.0.1:3000" }))).toBe(true);
    expect(isTrustedRequest(new Headers({ host: "localhost:3000" }))).toBe(true);
    expect(
      isTrustedRequest(
        new Headers({
          host: "127.0.0.1:3000",
          origin: "http://127.0.0.1:3000",
          "sec-fetch-site": "same-origin",
        }),
      ),
    ).toBe(true);
  });

  it("rejects a non-loopback Host, as DNS rebinding would send", () => {
    expect(isTrustedRequest(new Headers({ host: "evil.example:3000" }))).toBe(false);
    expect(isTrustedRequest(new Headers())).toBe(false);
  });

  it("rejects cross-site browser requests", () => {
    expect(
      isTrustedRequest(
        new Headers({ host: "127.0.0.1:3000", origin: "https://evil.example" }),
      ),
    ).toBe(false);
    expect(
      isTrustedRequest(new Headers({ host: "127.0.0.1:3000", "sec-fetch-site": "cross-site" })),
    ).toBe(false);
    expect(
      isTrustedRequest(new Headers({ host: "127.0.0.1:3000", origin: "null" })),
    ).toBe(false);
  });
});

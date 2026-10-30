import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("layout tokens", () => {
  it("uses white canvas and black primary ink", () => {
    const css = readFileSync(join(root, "app/globals.css"), "utf8");
    expect(css).toMatch(/--background:\s*#ffffff/i);
    expect(css).toMatch(/--foreground:\s*#000000/i);
  });

  it("keeps pressable reduced-motion without transform", () => {
    const css = readFileSync(join(root, "app/globals.css"), "utf8");
    expect(css).toMatch(/prefers-reduced-motion:\s*reduce/);
    expect(css).toMatch(/\.pressable:active[\s\S]*transform:\s*none/);
  });
});

describe("layout class contracts", () => {
  it("exports page and chapter class constants", async () => {
    const layout = await import("@/lib/layout");
    expect(layout.PAGE_SHELL).toContain("max-w-6xl");
    expect(layout.CHAPTER).toContain("border-b");
    expect(layout.PAGE_TITLE).toContain("font-medium");
  });
});

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

  it("wires font-sans and font-heading to Geist sans, not a circular or serif stack", () => {
    const css = readFileSync(join(root, "app/globals.css"), "utf8");
    expect(css).toMatch(/--font-sans:\s*var\(--font-geist-sans\)/);
    expect(css).toMatch(/--font-heading:\s*var\(--font-geist-sans\)/);
    expect(css).not.toMatch(/--font-sans:\s*var\(--font-sans\)/);
    expect(css).not.toMatch(/font-serif|Times|Georgia|ui-serif/i);
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

describe("layout components", () => {
  it("ships PageHeader and Chapter components", () => {
    const header = readFileSync(join(root, "components/PageHeader.tsx"), "utf8");
    const chapter = readFileSync(join(root, "components/Chapter.tsx"), "utf8");
    expect(header).toMatch(/export function PageHeader/);
    expect(chapter).toMatch(/export function Chapter/);
  });
});

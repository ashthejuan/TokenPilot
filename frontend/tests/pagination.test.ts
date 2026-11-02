import { describe, expect, it } from "vitest";

import {
  LIST_PAGE_SIZE,
  advanceCursorStack,
  canGoNext,
  canGoPrev,
  pageCursor,
  resetCursorStack,
} from "@/lib/pagination";

describe("LIST_PAGE_SIZE", () => {
  it("requests ten rows per page", () => {
    expect(LIST_PAGE_SIZE).toBe(10);
  });
});

describe("cursor stack", () => {
  it("starts at the first page with a null cursor", () => {
    expect(resetCursorStack()).toEqual({ cursorStack: [null], pageIndex: 0 });
    expect(pageCursor([null], 0)).toBeNull();
  });

  it("advances by recording the next cursor for the following page", () => {
    const next = advanceCursorStack([null], 0, "cursor-a");
    expect(next).toEqual({ cursorStack: [null, "cursor-a"], pageIndex: 1 });
    expect(pageCursor(next!.cursorStack, next!.pageIndex)).toBe("cursor-a");
  });

  it("refuses to advance without a next cursor", () => {
    expect(advanceCursorStack([null], 0, null)).toBeNull();
  });

  it("reuses an already-visited next page without growing the stack", () => {
    const stack = [null, "cursor-a", "cursor-b"] as (string | null)[];
    expect(advanceCursorStack(stack, 0, "cursor-a")).toEqual({
      cursorStack: stack,
      pageIndex: 1,
    });
  });

  it("gates prev/next from page index and next_cursor", () => {
    expect(canGoPrev(0)).toBe(false);
    expect(canGoPrev(1)).toBe(true);
    expect(canGoNext(null)).toBe(false);
    expect(canGoNext("cursor-a")).toBe(true);
  });
});

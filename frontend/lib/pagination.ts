/** Shared list-page size for Sessions and Insights. */
export const LIST_PAGE_SIZE = 10;

export function resetCursorStack(): {
  cursorStack: (string | null)[];
  pageIndex: number;
} {
  return { cursorStack: [null], pageIndex: 0 };
}

/** Cursor to send for the page at `pageIndex` (`null` = first page). */
export function pageCursor(cursorStack: (string | null)[], pageIndex: number): string | null {
  return cursorStack[pageIndex] ?? null;
}

/**
 * Move forward one page. `nextCursor` from the current response becomes the
 * cursor for the next request. Reuses stack entries when revisiting.
 */
export function advanceCursorStack(
  cursorStack: (string | null)[],
  pageIndex: number,
  nextCursor: string | null,
): { cursorStack: (string | null)[]; pageIndex: number } | null {
  if (nextCursor == null) return null;
  const nextIndex = pageIndex + 1;
  if (cursorStack[nextIndex] !== undefined) {
    return { cursorStack, pageIndex: nextIndex };
  }
  return {
    cursorStack: [...cursorStack.slice(0, nextIndex), nextCursor],
    pageIndex: nextIndex,
  };
}

export function canGoPrev(pageIndex: number): boolean {
  return pageIndex > 0;
}

export function canGoNext(nextCursor: string | null): boolean {
  return nextCursor != null;
}

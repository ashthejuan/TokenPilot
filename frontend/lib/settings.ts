/**
 * Pure helpers for the Settings page. `datetime-local` values are read as
 * local wall-clock; the wire always carries UTC Z.
 */

export function retentionBeforeParam(localValue: string): string | null {
  if (!localValue) return null;
  const date = new Date(localValue);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function parseThresholdNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

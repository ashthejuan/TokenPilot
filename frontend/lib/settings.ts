/**
 * Pure helpers for the Settings page. `datetime-local` values carry no offset
 * and the retention contract is UTC, so naive values are read as UTC
 * wall-clock; the wire always carries UTC Z.
 */

export function retentionBeforeParam(localValue: string): string | null {
  if (!localValue) return null;
  // `datetime-local` carries no offset and the bound contract is UTC: read a
  // naive value as UTC wall-clock rather than the viewer's zone. A value that
  // already carries an offset keeps its instant, normalized to Z.
  if (/[zZ]|[+-]\d{2}:?\d{2}$/.test(localValue)) {
    const date = new Date(localValue);
    return Number.isNaN(date.getTime()) ? null : date.toISOString();
  }
  const utcValue = /^\d{4}-\d{2}-\d{2}$/.test(localValue)
    ? `${localValue}T00:00Z`
    : `${localValue}Z`;
  const date = new Date(utcValue);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function parseThresholdNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

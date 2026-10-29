const LOCALE = "en-US";

function numberOptions(value: number): Intl.NumberFormatOptions {
  const abs = Math.abs(value);
  if (abs > 0 && abs < 0.01) {
    return { minimumSignificantDigits: 2, maximumSignificantDigits: 4 };
  }
  return { minimumFractionDigits: 2, maximumFractionDigits: 2 };
}

export function formatMoney(value: number | null, currency: string | null): string {
  if (value === null) return "Unknown";
  const options = numberOptions(value);
  const plain = new Intl.NumberFormat(LOCALE, options).format(value);
  if (currency === null) return `${plain} (currency unknown)`;
  try {
    return new Intl.NumberFormat(LOCALE, { ...options, style: "currency", currency }).format(value);
  } catch {
    return `${plain} ${currency}`;
  }
}

const MONEY_SCALE = 1e10;

/** Sums the known parts; the result is unknown only when every part is unknown. */
export function addMoney(...parts: (number | null)[]): number | null {
  const known = parts.filter((part): part is number => part !== null);
  if (known.length === 0) return null;
  const scaled = known.reduce((sum, part) => sum + Math.round(part * MONEY_SCALE), 0);
  return scaled / MONEY_SCALE;
}

/**
 * Backend SQL SUM returns null both for an empty class and for a class whose
 * events are all unpriced. Show "$0.00" only when the summary currency is known
 * AND every event in the filter has a cost (`eventsWithUnknownCost === 0`);
 * otherwise keep "Unknown".
 */
export function moneyOrZero(
  value: number | null,
  currency: string | null,
  eventsWithUnknownCost: number = 0,
): number | null {
  if (value !== null) return value;
  if (currency === null || eventsWithUnknownCost > 0) return null;
  return 0;
}

export function formatCount(value: number | null): string {
  return value === null ? "Unknown" : new Intl.NumberFormat(LOCALE).format(value);
}

export function formatPct(value: number | null): string {
  return value === null ? "Unknown" : `${value.toFixed(1)}%`;
}

/**
 * Every timestamp in the app is UTC on the wire; render wall-clock UTC with an
 * explicit label so a viewer never mistakes it for their local time.
 */
export function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString(LOCALE, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

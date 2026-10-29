import { describe, expect, it } from "vitest";

import { addMoney, formatMoney, formatTimestamp, moneyOrZero } from "@/lib/format";

describe("formatMoney", () => {
  it("shows Unknown for a missing amount, never zero", () => {
    expect(formatMoney(null, "USD")).toBe("Unknown");
    expect(formatMoney(null, null)).toBe("Unknown");
  });

  it("formats whole and cent amounts with two decimals", () => {
    expect(formatMoney(0, "USD")).toBe("$0.00");
    expect(formatMoney(6, "USD")).toBe("$6.00");
    expect(formatMoney(0.01, "USD")).toBe("$0.01");
    expect(formatMoney(1234.5, "USD")).toBe("$1,234.50");
  });

  it("keeps significant digits below one cent", () => {
    expect(formatMoney(0.000123, "USD")).toBe("$0.000123");
    expect(formatMoney(0.0005, "USD")).toBe("$0.00050");
    expect(formatMoney(-0.000123, "USD")).toBe("-$0.000123");
  });

  it("labels an amount whose currency is unknown", () => {
    expect(formatMoney(6, null)).toBe("6.00 (currency unknown)");
    expect(formatMoney(0.000123, null)).toBe("0.000123 (currency unknown)");
  });

  it("falls back to the raw code for a currency Intl rejects", () => {
    expect(formatMoney(6, "not-a-code")).toBe("6.00 not-a-code");
  });
});

describe("addMoney", () => {
  it("is unknown only when every part is unknown", () => {
    expect(addMoney(null, null)).toBeNull();
    expect(addMoney(1.5, null)).toBe(1.5);
    expect(addMoney(null, 2)).toBe(2);
  });

  it("adds at the ledger's 1e-10 precision", () => {
    expect(addMoney(0.1, 0.2)).toBe(0.3);
  });
});

describe("moneyOrZero", () => {
  it("keeps a known amount", () => {
    expect(moneyOrZero(1.5, "USD", 0)).toBe(1.5);
  });

  it("treats an empty class as zero when every event is priced", () => {
    expect(moneyOrZero(null, "USD", 0)).toBe(0);
  });

  it("stays unknown when some events lack a cost", () => {
    expect(moneyOrZero(null, "USD", 3)).toBeNull();
  });

  it("stays unknown when currency is unknown", () => {
    expect(moneyOrZero(null, null, 0)).toBeNull();
  });
});

describe("formatTimestamp", () => {
  it("renders wall-clock UTC with an explicit UTC label", () => {
    expect(formatTimestamp("2026-10-27T00:30:00Z")).toBe("Oct 27, 12:30 AM UTC");
  });

  it("does not shift the instant into the viewer's zone", () => {
    expect(formatTimestamp("2026-06-01T23:45:00+02:00")).toBe("Jun 1, 09:45 PM UTC");
  });
});

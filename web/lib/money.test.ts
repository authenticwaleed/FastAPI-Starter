import { describe, expect, it } from "vitest";

import { formatMoney, money } from "@/lib/money";

/**
 * The criterion W6 is judged on: money renders from the string the API
 * sent, and a float never appears anywhere along the way.
 */

describe("formatMoney", () => {
  it("keeps every digit of a value a float would lose", () => {
    // 19.99 is not representable in binary floating point. Round-tripping
    // it through Number gives 19.989999999999998, and a total built from
    // three of those is wrong in a way nobody can find later.
    const shown = formatMoney("19.99", "USD");

    expect(shown).toContain("19.99");
    expect(shown).not.toContain("19.98");
  });

  it("does not lose precision on a value with more digits than a float holds", () => {
    // 21 significant digits: beyond what a double can represent at all.
    // Anything that parsed this would print a rounded number.
    expect(formatMoney("123456789012345678.90", null)).toBe(
      "123,456,789,012,345,678.90",
    );
  });

  it("groups thousands", () => {
    expect(formatMoney("1234567.50", null)).toBe("1,234,567.50");
  });

  it("keeps a negative sign", () => {
    expect(formatMoney("-40.00", null)).toBe("-40.00");
  });

  it("names the currency when there is one", () => {
    // The exact glyph and its placement are the locale's business; that
    // the amount and the currency both appear is not.
    const shown = formatMoney("49.00", "USD");

    expect(shown).toMatch(/49\.00/);
    expect(shown?.length).toBeGreaterThan("49.00".length);
  });

  it("falls back rather than throwing on a currency code it does not know", () => {
    const shown = formatMoney("10.00", "ZZZ");

    expect(shown).toContain("10.00");
    expect(shown).toContain("ZZZ");
  });

  it("treats a missing amount as missing, never as zero", () => {
    // A product with no price of its own takes its variant's. Printing
    // "0.00" there would quote a customer a free item.
    expect(formatMoney(null, "USD")).toBeNull();
    expect(formatMoney(undefined, "USD")).toBeNull();
    expect(formatMoney("", "USD")).toBeNull();
  });

  it("shows something unexpected as it arrived rather than mangling it", () => {
    expect(formatMoney("not-a-number", "USD")).toBe("not-a-number");
  });
});

describe("money", () => {
  it("gives a dash for a cell with no amount", () => {
    expect(money(null, "USD")).toBe("—");
  });

  it("is formatMoney otherwise", () => {
    expect(money("5.00", null)).toBe("5.00");
  });
});

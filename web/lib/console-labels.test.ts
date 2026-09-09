import { describe, expect, it } from "vitest";

import { timeLeft } from "@/lib/console-labels";

/**
 * The one piece of arithmetic W11 has, and the one worth pinning.
 *
 * The rule the phase is judged on is that a support window's remaining
 * time is always on screen and never silently wrong. The two ends of that
 * are where this can go astray: a window that has closed must not read as
 * a window with time in it, and a window with seconds in it must not round
 * up into a minute somebody then plans around.
 */

const NOW = Date.parse("2026-09-08T12:00:00Z");

function inSeconds(seconds: number): string {
  return new Date(NOW + seconds * 1000).toISOString();
}

describe("timeLeft", () => {
  it("is null once the window has closed", () => {
    expect(timeLeft(inSeconds(0), NOW)).toBeNull();
    expect(timeLeft(inSeconds(-1), NOW)).toBeNull();
    expect(timeLeft(inSeconds(-86_400), NOW)).toBeNull();
  });

  it("says less than a minute rather than rounding up to one", () => {
    // A screen reading "1m" with fifty-nine seconds left is a screen
    // somebody finishes a paragraph on.
    expect(timeLeft(inSeconds(59), NOW)).toBe("less than a minute");
    expect(timeLeft(inSeconds(1), NOW)).toBe("less than a minute");
  });

  it("counts down in minutes below the hour", () => {
    expect(timeLeft(inSeconds(60), NOW)).toBe("1m");
    expect(timeLeft(inSeconds(59 * 60 + 59), NOW)).toBe("59m");
  });

  it("counts down in hours and minutes above it", () => {
    expect(timeLeft(inSeconds(3600), NOW)).toBe("1h");
    expect(timeLeft(inSeconds(3600 + 60), NOW)).toBe("1h 1m");
    expect(timeLeft(inSeconds(4 * 3600 - 1), NOW)).toBe("3h 59m");
  });

  it("is null rather than NaN for a timestamp it cannot read", () => {
    expect(timeLeft("not a date", NOW)).toBeNull();
  });
});

import { describe, expect, it } from "vitest";
import { duration, humanize, ms, pct } from "./format";

describe("format", () => {
  it("formats percentages", () => {
    expect(pct(0.0523)).toBe("5.2%");
    expect(pct(null)).toBe("—");
  });
  it("formats durations", () => {
    expect(duration(42)).toBe("42s");
    expect(duration(125)).toBe("2m 5s");
    expect(duration(7300)).toBe("2h 2m");
  });
  it("formats latency", () => {
    expect(ms(1840)).toBe("1.84 s");
    expect(ms(120.4)).toBe("120 ms");
  });
  it("humanizes enum values", () => expect(humanize("ROOT_CAUSE_IDENTIFIED")).toBe("Root cause identified"));
});

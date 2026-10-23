import { describe, expect, it } from "vitest";

import { clock } from "./time";

describe("clock", () => {
  it("formats m:ss", () => {
    expect(clock(0)).toBe("0:00");
    expect(clock(65.9)).toBe("1:05");
    expect(clock(Number.NaN)).toBe("0:00");
  });
});

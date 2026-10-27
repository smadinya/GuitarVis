import { describe, expect, it } from "vitest";

import { MAX_POLL_MS, POLL_MS, backoff, stageText } from "./progress";

describe("stageText", () => {
  it("names a link job's download, which comes before the four stages", () => {
    expect(stageText("download")).toBe("Fetching the audio");
    expect(stageText("separation")).toBe("Isolating the guitar");
  });
});

describe("backoff", () => {
  it("doubles from the polling interval and stops at the cap", () => {
    const delays = [POLL_MS];
    for (let i = 0; i < 4; i++) delays.push(backoff(delays[i]));

    expect(delays).toEqual([1500, 3000, 6000, 10_000, 10_000]);
    expect(delays.at(-1)).toBe(MAX_POLL_MS);
  });
});

import { describe, expect, it } from "vitest";

import { routeOf, songPath } from "./routing";

describe("routeOf", () => {
  it("knows the two pages", () => {
    expect(routeOf("/")).toEqual({ page: "upload" });
    expect(routeOf("/songs/abc-123")).toEqual({ page: "song", jobId: "abc-123" });
    expect(routeOf("/songs/abc-123/")).toEqual({ page: "song", jobId: "abc-123" });
  });

  it("calls anything else missing", () => {
    expect(routeOf("/songs/")).toEqual({ page: "missing" });
    expect(routeOf("/songs/a/b")).toEqual({ page: "missing" });
    expect(routeOf("/jobs/abc")).toEqual({ page: "missing" });
    expect(routeOf("/songs/%E0")).toEqual({ page: "missing" });
  });

  it("round-trips a song path", () => {
    expect(routeOf(songPath("a b/c"))).toEqual({ page: "song", jobId: "a b/c" });
  });
});

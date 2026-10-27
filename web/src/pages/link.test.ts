import { describe, expect, it } from "vitest";

import { BLANK_HINT, NOT_A_LINK_HINT, linkHint } from "./link";

describe("linkHint", () => {
  it.each(["", "   ", "\t\n"])("asks for a link when the field is blank: %j", (raw) => {
    expect(linkHint(raw)).toBe(BLANK_HINT);
  });

  it.each([
    "never gonna give you up",
    "hello",
    "javascript:alert(1)",
    "ftp://example.com/song.mp3",
    "file:///etc/passwd",
    "https://",
    "https://exa mple.com/",
  ])("says %j does not look like a link", (raw) => {
    expect(linkHint(raw)).toBe(NOT_A_LINK_HINT);
  });

  it.each([
    "https://www.youtube.com/watch?v=kPdv44HtEoA",
    "  youtu.be/kPdv44HtEoA  ",
    "http://example.com/anything",
    "www.youtube.com/playlist?list=PL123",
  ])("lets %j through, for the api to judge", (raw) => {
    expect(linkHint(raw)).toBeNull();
  });
});

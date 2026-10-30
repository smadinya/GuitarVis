import { describe, expect, it } from "vitest";

import { BLANK_HINT, MAX_LINK_CHARS, NOT_A_LINK_HINT, linkHint } from "./link";

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

  // A link as long as `length`, which the api would otherwise turn away with
  // words meant for developers.
  const linkOf = (length: number) => {
    const start = "https://www.youtube.com/watch?v=kPdv44HtEoA&t=";
    return start + "1".repeat(length - start.length);
  };

  it("takes a link of 2,048 characters, the api's limit", () => {
    expect(MAX_LINK_CHARS).toBe(2048);
    expect(linkHint(linkOf(MAX_LINK_CHARS))).toBeNull();
    expect(linkHint(`  ${linkOf(MAX_LINK_CHARS)}\n`)).toBeNull(); // trimmed, as sent
  });

  it.each([MAX_LINK_CHARS + 1, 16 * 1024, 16 * 1024 + 1, 100_000])(
    "says a paste of %i characters does not look like a link",
    (length) => {
      expect(linkHint(linkOf(length))).toBe(NOT_A_LINK_HINT);
    },
  );
});

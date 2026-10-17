// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GUITAR_LOAD_FAILED } from "../labels";
import { buildSong } from "../song";
import { FakeMedia } from "../test/fakeMedia";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import { JOB_ID } from "../test/jobs";
import type { TabDocument } from "../types/tabDocument";
import { Player } from "./Player";

const chunkFailed = vi.hoisted(() => new Error("Failed to fetch dynamically imported module"));

// The guitar's chunk fails to load, as on a flaky network, or after a deploy
// replaced the file a tab's old entry bundle names. vitest wraps what the
// factory throws, and keeps it as the wrapper's `cause`.
vi.mock("../guitar/Guitar", () => {
  throw chunkFailed;
});

const FIRST_SONG: TabDocument = firstSongJson;

describe("Player when the guitar's code cannot load", () => {
  let uncaught: unknown[];
  // React raises a caught error as an error event first. Handling it keeps
  // React from logging the error, and jsdom from printing it as uncaught.
  const swallow = (event: ErrorEvent) => {
    uncaught.push(event.error);
    event.preventDefault();
  };

  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null);
    uncaught = [];
    window.addEventListener("error", swallow);
  });

  afterEach(() => {
    window.removeEventListener("error", swallow);
    vi.restoreAllMocks();
  });

  function mount() {
    const media = new FakeMedia();
    render(<Player song={buildSong(FIRST_SONG)} jobId={JOB_ID} createMedia={() => media} />);
    act(() => media.loadMetadata(13.871));
    return media;
  }

  it("says so in the guitar's panel, and leaves the rest of the player up", async () => {
    mount();

    const message = await screen.findByText(GUITAR_LOAD_FAILED);

    expect(message.closest(".guitar")).not.toBeNull(); // the panel keeps its size
    expect(screen.getByLabelText("Tab")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();

    // It was the chunk's failure that the boundary caught, and nothing else.
    expect(uncaught.length).toBeGreaterThan(0);
    for (const error of uncaught) expect((error as Error).cause).toBe(chunkFailed);
  });

  it("keeps playing from its controls", async () => {
    const media = mount();
    await screen.findByText(GUITAR_LOAD_FAILED);

    fireEvent.click(screen.getByRole("button", { name: "Play" }));

    expect(media.paused).toBe(false);
  });
});

// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildSong } from "../song";
import { FakeMedia } from "../test/fakeMedia";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import { JOB_ID } from "../test/jobs";
import type { TabDocument } from "../types/tabDocument";
import { clock } from "./Controls";
import { Player } from "./Player";

const FIRST_SONG: TabDocument = firstSongJson;

function mount(fields: Partial<TabDocument> = {}, media = new FakeMedia()) {
  const createMedia = () => media;
  render(<Player song={buildSong({ ...FIRST_SONG, ...fields })} jobId={JOB_ID} createMedia={createMedia} />);
  act(() => media.loadMetadata(13.871));
  return media;
}

function press(key: string, target: Element | Window = window) {
  act(() => {
    fireEvent.keyDown(target, { key });
  });
}

describe("Player", () => {
  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("plays and pauses from its button", () => {
    const media = mount();

    fireEvent.click(screen.getByRole("button", { name: "Play" }));

    expect(media.paused).toBe(false);
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
  });

  it("sets the speed, and shows which is on", () => {
    const media = mount();

    fireEvent.click(screen.getByRole("button", { name: "0.5×" }));

    expect(media.playbackRate).toBe(0.5);
    expect(screen.getByRole("button", { name: "0.5×" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("offers no speed control where pitch cannot be kept", () => {
    const media = new FakeMedia();
    Reflect.deleteProperty(media, "preservesPitch");
    Reflect.deleteProperty(media, "webkitPreservesPitch");

    mount({}, media);

    expect(screen.queryByRole("group", { name: "Speed" })).toBeNull();
  });

  it("switches to the guitar stem", () => {
    const media = mount();

    fireEvent.click(screen.getByRole("button", { name: "Guitar only" }));

    expect(media.src).toBe(`/jobs/${JOB_ID}/audio/guitar`);
  });

  it("plays and pauses on Space, and seeks on the arrows", () => {
    const media = mount();

    press(" ");
    expect(media.paused).toBe(false);
    press("ArrowRight");
    expect(media.currentTime).toBeCloseTo(5, 1); // plus the moment it has been playing
    press("ArrowLeft");
    expect(media.currentTime).toBeCloseTo(0, 1);
    press(" ");
    expect(media.paused).toBe(true);
  });

  it("leaves keys typed into a text field alone", () => {
    const media = mount();
    const field = document.createElement("input");
    document.body.append(field);

    press(" ", field);
    press("ArrowRight", field);

    expect(media.paused).toBe(true);
    expect(media.currentTime).toBe(0);
    field.remove();
  });

  it("leaves Space to a button that has keyboard focus", () => {
    const media = mount();

    press(" ", screen.getByRole("button", { name: "Guitar only" }));

    expect(media.paused).toBe(true);
  });

  it("keeps a mouse click from leaving focus on a control", () => {
    mount();

    const allowed = fireEvent.mouseDown(screen.getByRole("button", { name: "0.5×" }));

    expect(allowed).toBe(false); // default prevented: the button never takes focus
  });

  it("shows the document's warnings", () => {
    mount({ warnings: ["Chord detection failed, so this tab has no chords."] });
    expect(screen.getByRole("complementary", { name: "Warnings" }).textContent).toContain(
      "Chord detection failed",
    );
  });

  it("shows no warnings box for a clean document", () => {
    mount({ warnings: [] });

    expect(screen.queryByRole("complementary", { name: "Warnings" })).toBeNull();
  });

  it("says when the audio connection is lost", () => {
    const media = mount();

    act(() => {
      for (let i = 0; i < 3; i++) media.emit("error");
    });

    expect(screen.getByRole("alert").textContent).toContain("lost the connection");
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
  });
});

describe("clock", () => {
  it("formats m:ss", () => {
    expect(clock(0)).toBe("0:00");
    expect(clock(65.9)).toBe("1:05");
    expect(clock(Number.NaN)).toBe("0:00");
  });
});

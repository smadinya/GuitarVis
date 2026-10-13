// @vitest-environment jsdom
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PlaybackEngine } from "../playback/engine";
import { buildSong, type Song } from "../song";
import { FakeFrames, FakeMedia } from "../test/fakeMedia";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import { JOB_ID } from "../test/jobs";
import type { TabDocument } from "../types/tabDocument";
import { Fretboard } from "./Fretboard";
import { neckOf } from "./neck";

const FIRST_SONG: TabDocument = firstSongJson;

/** A confident G on the low E string's third fret, from 1 s to 2 s. */
const ONE_NOTE: TabDocument = {
  ...FIRST_SONG,
  notes: [{ id: "g", t: 1, dur: 1, midi: 43, string: 0, fret: 3, confidence: 0.95 }],
  chords: [],
};

/** Stands in for the browser's: jsdom has none. */
class FakeResizeObserver {
  static last: FakeResizeObserver | null = null;
  constructor(readonly callback: () => void) {
    FakeResizeObserver.last = this;
  }
  observe() {}
  disconnect() {}
}

/** An engine whose animation frames run only when flushed. */
function engineFor(song: Song) {
  const frames = new FakeFrames();
  const engine = new PlaybackEngine({
    media: new FakeMedia(),
    jobId: JOB_ID,
    duration: song.duration,
    requestFrame: frames.request,
    cancelFrame: frames.cancel,
  });
  return { engine, frames };
}

function mount(doc: TabDocument = FIRST_SONG) {
  const song: Song = buildSong(doc);
  const { engine, frames } = engineFor(song);
  render(<Fretboard song={song} engine={engine} />);
  const svg = screen.getByRole("img", { name: "Fretboard" });
  /** Move the song to `t` and run the frame that draws it. */
  const at = (t: number) => {
    engine.seek(t);
    frames.flush();
  };
  return { song, engine, svg, at };
}

describe("Fretboard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    FakeResizeObserver.last = null;
  });

  it("draws N + 1 wires and one string per tuning entry", () => {
    const { svg } = mount();

    // The first song reaches fret 8, so the neck shows twelve.
    expect(svg.querySelectorAll(".fret-nut, .fret-wire")).toHaveLength(13);
    expect(svg.querySelectorAll(".fret-string")).toHaveLength(6);
    expect([...svg.querySelectorAll(".fret-label")].map((label) => label.textContent)).toEqual([
      "E", "A", "D", "G", "B", "e",
    ]);
    expect(svg.querySelectorAll(".fret-number")).toHaveLength(12);
  });

  it("lights a note while it sounds, named by pitch", () => {
    const { svg, at } = mount(ONE_NOTE);

    at(1.5);
    expect(svg.querySelector(".fret-dot text")?.textContent).toBe("G");

    at(3);
    expect(svg.querySelector(".fret-dot")).toBeNull();
  });

  it("rings a note before it sounds", () => {
    const { svg, at } = mount(ONE_NOTE);

    at(0.25);

    expect(svg.querySelectorAll(".fret-ring")).toHaveLength(1);
    expect(svg.querySelector(".fret-dot")).toBeNull();
  });

  it("shows the message for a document with no notes", () => {
    const { svg, at } = mount({ ...FIRST_SONG, notes: [] });

    at(0);

    expect(svg.querySelector(".fret-message")?.textContent).toBe("No notes to show");
  });

  it("subscribes to the engine's frames, and unsubscribes on unmount", () => {
    const song = buildSong(FIRST_SONG);
    const { engine } = engineFor(song);
    const stopped = vi.fn();
    const onFrame = engine.onFrame.bind(engine);
    vi.spyOn(engine, "onFrame").mockImplementation((listener) => {
      const stop = onFrame(listener);
      return () => {
        stopped();
        stop();
      };
    });

    const view = render(<Fretboard song={song} engine={engine} />);
    expect(engine.onFrame).toHaveBeenCalledTimes(1);

    view.unmount();
    expect(stopped).toHaveBeenCalledTimes(1);
  });

  it("refits the neck on resize, and moves a sounding note's dot with it, without resubscribing", () => {
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    const { song, engine, svg, at } = mount(ONE_NOTE);
    const onFrame = vi.spyOn(engine, "onFrame");
    at(1.5);
    const dot = svg.querySelector(".fret-dot");

    const box = svg.parentElement as HTMLElement;
    Object.defineProperty(box, "clientWidth", { configurable: true, value: 900 });
    act(() => FakeResizeObserver.last?.callback());
    at(1.5);

    const neck = neckOf(song, 900);
    expect(svg.getAttribute("width")).toBe("900");
    expect(svg.querySelector(".fret-dot")).toBe(dot);
    expect(dot?.getAttribute("transform")).toBe(`translate(${neck.noteX[3]} ${neck.strings[0].y})`);
    expect(onFrame).not.toHaveBeenCalled();
  });
});

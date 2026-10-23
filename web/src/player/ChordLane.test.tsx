// @vitest-environment jsdom
import { act, render, screen, within } from "@testing-library/react";
import { Profiler } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CHORD_FULL, CHORD_HIDE, FADED } from "../confidence";
import { buildSong } from "../song";
import { fakeEngine } from "../test/engine";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { Chord, TabDocument } from "../types/tabDocument";
import { ChordLane } from "./ChordLane";

const FIRST_SONG: TabDocument = firstSongJson;

const chord = (t: number, symbol: string, confidence = 0.9, dur = 2) => ({ t, dur, symbol, confidence });
const FOUR = [chord(0, "Am"), chord(2, "C"), chord(4, "G"), chord(6, "D")];

function mount(chords: Chord[] = FOUR) {
  const song = buildSong({ ...FIRST_SONG, chords });
  const fake = fakeEngine(song);
  const onRender = vi.fn();
  render(
    <Profiler id="lane" onRender={onRender}>
      <ChordLane song={song} engine={fake.engine} />
    </Profiler>,
  );
  return { ...fake, onRender };
}
const cells = () => within(screen.getByRole("list", { name: "Chord lane" })).getAllByRole("listitem");
const states = () => cells().map((c) => c.dataset.state);

/** jsdom lays nothing out, so give the cells a 64px width at a 70px pitch in a
 * 40px lane: the centre of cell i is 70i + 32 and the lane's is 20, so the lane
 * scrolls to 70i + 12. */
function layOut() {
  vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockImplementation(function (this: HTMLElement) {
    return 70 * Array.from(this.parentElement?.children ?? []).indexOf(this);
  });
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(64);
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(40);
}
const scrollLeft = () => screen.getByRole("list", { name: "Chord lane" }).scrollLeft;

describe("ChordLane", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("draws one cell per chord, in order", () => {
    mount();
    expect(cells().map((c) => c.textContent)).toEqual(["Am", "C", "G", "D"]);
  });

  it("is not drawn for a song with no chords", () => {
    mount([]);
    expect(screen.queryByRole("list", { name: "Chord lane" })).toBeNull();
  });

  it("marks played, current and coming cells as the song plays", () => {
    const { at } = mount();
    at(3);
    expect(states()).toEqual(["played", "current", "coming", "coming"]);
    expect(cells()[1].getAttribute("aria-current")).toBe("true");
    at(0.5);
    expect(states()).toEqual(["current", "coming", "coming", "coming"]);
  });

  it("marks the cells as the playhead stands when it mounts, before the first frame arrives", () => {
    const song = buildSong({ ...FIRST_SONG, chords: FOUR });
    const fake = fakeEngine(song);
    fake.at(3);

    render(<ChordLane song={song} engine={fake.engine} />);

    expect(states()).toEqual(["played", "current", "coming", "coming"]);
  });

  it("has no current cell between chords", () => {
    const { at } = mount([chord(0, "Am", 0.9, 1), chord(2, "C", 0.9, 1)]);
    at(1.5);
    expect(states()).toEqual(["played", "coming"]);
  });

  it("fades a weak chord by the chord thresholds", () => {
    mount([chord(0, "Am", CHORD_HIDE), chord(2, "C", CHORD_FULL)]);
    expect(cells().map((c) => (c.firstElementChild as HTMLElement).style.opacity)).toEqual([String(FADED), "1"]);
  });

  it("renders again only when the current chord changes", () => {
    const { at, onRender } = mount();
    at(2.5);
    const renders = onRender.mock.calls.length;
    at(3);
    at(3.5);
    expect(onRender).toHaveBeenCalledTimes(renders);
    at(4.5);
    expect(onRender).toHaveBeenCalledTimes(renders + 1);
  });

  it("centres the current cell in the lane, and the next one between chords", () => {
    layOut();
    const { at } = mount([chord(0, "Am", 0.9, 1), chord(2, "C", 0.9, 1), chord(4, "G", 0.9, 1)]);
    at(2.5);
    expect(scrollLeft()).toBe(70 + 12);
    at(3.5); // between C and G: G is next
    expect(scrollLeft()).toBe(140 + 12);
    at(0.5);
    expect(scrollLeft()).toBe(12);
  });

  it("centres the current cell again when the lane's width changes, with no change of chord", () => {
    layOut();
    const observers: Array<{ callback: () => void; observed: Element[]; disconnected: boolean }> = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        private readonly seen = { callback: () => {}, observed: [] as Element[], disconnected: false };
        constructor(callback: () => void) {
          this.seen.callback = callback;
          observers.push(this.seen);
        }
        observe(target: Element) {
          this.seen.observed.push(target);
        }
        disconnect() {
          this.seen.disconnected = true;
        }
      },
    );
    const { at } = mount([chord(0, "Am", 0.9, 1), chord(2, "C", 0.9, 1), chord(4, "G", 0.9, 1)]);
    at(2.5);
    expect(scrollLeft()).toBe(70 + 12);

    // The window narrows across the 900 px breakpoint: the lane is 60 px wide.
    expect(observers).toHaveLength(1);
    expect(observers[0].observed).toEqual([screen.getByRole("list", { name: "Chord lane" })]);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(60);
    act(() => observers[0].callback());

    expect(scrollLeft()).toBe(70 + 32 - 30);
  });

  it("stops watching the lane's size when it goes", () => {
    const disconnect = vi.fn();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        disconnect = disconnect;
      },
    );
    const song = buildSong({ ...FIRST_SONG, chords: FOUR });
    const view = render(<ChordLane song={song} engine={fakeEngine(song).engine} />);

    view.unmount();

    expect(disconnect).toHaveBeenCalled();
  });

  it("stays on the last cell after the last chord", () => {
    layOut();
    const { at } = mount([chord(0, "Am", 0.9, 1), chord(2, "C", 0.9, 1)]);
    at(5);
    expect(scrollLeft()).toBe(70 + 12);
  });
});

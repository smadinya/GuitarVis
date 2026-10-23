// @vitest-environment jsdom
import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { Profiler } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { buildSong } from "../song";
import { fakeEngine } from "../test/engine";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { TabDocument } from "../types/tabDocument";
import { useTransportKeys } from "./keys";
import { Scrubber } from "./Scrubber";

const FIRST_SONG: TabDocument = firstSongJson;

const SECTIONS = [
  { t: 0, dur: 5, label: "Intro" },
  { t: 5, dur: 5, label: "Verse 1" },
  { t: 10, dur: 10, label: "Chorus" },
];
const RECT = { left: 100, width: 400, top: 0, right: 500, bottom: 24, height: 24, x: 100, y: 0, toJSON: () => ({}) } as DOMRect;

function mount(sections = SECTIONS) {
  const song = buildSong({ ...FIRST_SONG, sections });
  const fake = fakeEngine(song, { duration: 20 });
  const onRender = vi.fn();
  render(
    <Profiler id="scrubber" onRender={onRender}>
      <Scrubber engine={fake.engine} sections={song.sections} section="Verse 1" />
    </Profiler>,
  );
  const slider = screen.getByRole("slider", { name: "Position" });
  vi.spyOn(slider, "getBoundingClientRect").mockReturnValue(RECT);
  return { ...fake, slider, onRender };
}
const part = (slider: HTMLElement, name: string) => slider.querySelector(`.${name}`) as HTMLElement;

describe("Scrubber", () => {
  afterEach(() => vi.restoreAllMocks());

  it("is a slider over the song, speaking the time and the section", () => {
    const { slider, at } = mount();
    at(7);
    expect(["aria-valuemin", "aria-valuemax", "aria-valuenow", "aria-valuetext"].map((a) => slider.getAttribute(a))).toEqual(["0", "20", "7", "0:07, Verse 1"]);
  });

  it("moves the knob and the played part with each frame", () => {
    const { slider, at } = mount();
    at(5);
    expect(part(slider, "scrub-head").style.transform).toBe("translateX(25%)");
    expect(part(slider, "scrub-played").style.transform).toBe("scaleX(0.25)");
  });

  it("draws a tick at each section after the first, and the loop", () => {
    const { slider, engine, at } = mount();
    at(5);
    act(() => void engine.setLoopPoint("a"));
    at(15);
    act(() => void engine.setLoopPoint("b"));
    expect([...slider.querySelectorAll<HTMLElement>(".scrub-tick")].map((t) => t.style.left)).toEqual(["25%", "50%"]);
    const band = part(slider, "scrub-band");
    expect([band.style.left, band.style.width]).toEqual(["25%", "50%"]);
    expect(slider.querySelectorAll(".scrub-edge")).toHaveLength(2);
  });

  it("previews a drag without seeking, and seeks once on release, whatever the frames do meanwhile", () => {
    const { slider, engine, frames } = mount();
    const seek = vi.spyOn(engine, "seek");

    fireEvent.pointerDown(slider, { clientX: 200, pointerId: 1 });
    expect(screen.getByText("0:05")).toBeTruthy();
    act(() => {
      engine.redraw(); // a frame at t = 0, mid-drag
      frames.flush();
    });
    expect(part(slider, "scrub-head").style.transform).toBe("translateX(25%)");

    fireEvent.pointerMove(slider, { clientX: 300, pointerId: 1 });
    expect(part(slider, "scrub-head").style.transform).toBe("translateX(50%)");
    expect(seek).not.toHaveBeenCalled();

    fireEvent.pointerUp(slider, { clientX: 300, pointerId: 1 });
    expect(seek).toHaveBeenCalledTimes(1);
    expect(seek).toHaveBeenCalledWith(10);
    expect(screen.queryByText("0:10")).toBeNull();
  });

  it("renders again in a drag only when the second shown changes, while the knob and the seek stay exact", () => {
    const { slider, engine, onRender } = mount();
    const seek = vi.spyOn(engine, "seek");
    fireEvent.pointerDown(slider, { clientX: 200, pointerId: 1 }); // 5.00 s
    const renders = onRender.mock.calls.length;

    // 20 px a second: all of these are inside second 5.
    for (const clientX of [201, 203, 207, 210, 214, 218, 219]) {
      fireEvent.pointerMove(slider, { clientX, pointerId: 1 });
    }
    expect(onRender).toHaveBeenCalledTimes(renders);
    expect(part(slider, "scrub-head").style.transform).toBe("translateX(29.75%)"); // 5.95 s: not rounded to 5
    expect(screen.getByText("0:05")).toBeTruthy();

    fireEvent.pointerMove(slider, { clientX: 221, pointerId: 1 }); // 6.05 s
    expect(onRender).toHaveBeenCalledTimes(renders + 1);
    expect(screen.getByText("0:06")).toBeTruthy();

    fireEvent.pointerMove(slider, { clientX: 219, pointerId: 1 });
    fireEvent.pointerUp(slider, { clientX: 219, pointerId: 1 });
    expect(seek).toHaveBeenCalledTimes(1);
    expect(seek.mock.calls[0][0]).toBeCloseTo(5.95);
  });

  it("speaks the section under the pointer at its exact start, though the second shown has not changed", () => {
    const { slider } = mount([
      { t: 0, dur: 5.5, label: "A" },
      { t: 5.5, dur: 5, label: "B" },
    ]);
    fireEvent.pointerDown(slider, { clientX: 208, pointerId: 1 }); // 5.4 s
    expect(slider.getAttribute("aria-valuetext")).toBe("0:05, A");

    fireEvent.pointerMove(slider, { clientX: 212, pointerId: 1 }); // 5.6 s
    expect(slider.getAttribute("aria-valuetext")).toBe("0:05, B");
  });

  it("speaks the section under the pointer while dragging, and the playing one after", () => {
    const { slider } = mount();
    expect(slider.getAttribute("aria-valuetext")).toBe("0:00, Verse 1"); // the prop: the playhead's section

    fireEvent.pointerDown(slider, { clientX: 400, pointerId: 1 }); // 15 s, in the Chorus
    expect(slider.getAttribute("aria-valuenow")).toBe("15");
    expect(slider.getAttribute("aria-valuetext")).toBe("0:15, Chorus");

    fireEvent.pointerMove(slider, { clientX: 150, pointerId: 1 }); // 2.5 s, in the Intro
    expect(slider.getAttribute("aria-valuetext")).toBe("0:02, Intro");

    fireEvent.pointerCancel(slider, { pointerId: 1 });
    expect(slider.getAttribute("aria-valuetext")).toBe("0:00, Verse 1");
  });

  it("speaks only the time for a drag to a place outside every section", () => {
    const song = buildSong({ ...FIRST_SONG, sections: [{ t: 10, dur: 5, label: "Verse 1" }] });
    const fake = fakeEngine(song, { duration: 20 });
    render(<Scrubber engine={fake.engine} sections={song.sections} section="Verse 1" />);
    const slider = screen.getByRole("slider", { name: "Position" });
    vi.spyOn(slider, "getBoundingClientRect").mockReturnValue(RECT);
    fireEvent.pointerDown(slider, { clientX: 200, pointerId: 1 }); // 5 s, before the first section
    expect(slider.getAttribute("aria-valuetext")).toBe("0:05");
  });

  it("drops a cancelled drag without seeking", () => {
    const { slider, engine, frames } = mount();
    const seek = vi.spyOn(engine, "seek");
    fireEvent.pointerDown(slider, { clientX: 300, pointerId: 1 });
    fireEvent.pointerCancel(slider, { pointerId: 1 });
    act(() => frames.flush());
    expect(seek).not.toHaveBeenCalled();
    expect(part(slider, "scrub-head").style.transform).toBe("translateX(0%)");
  });

  it("seeks five seconds once per arrow key, though the page's keys listen too", () => {
    const { slider, engine } = mount();
    renderHook(() => useTransportKeys(engine));
    const key = (k: string) => act(() => void fireEvent.keyDown(slider, { key: k }));
    key("ArrowRight");
    expect(engine.getState().time).toBe(5);
    key("ArrowLeft");
    expect(engine.getState().time).toBe(0);
    key("End");
    expect(engine.getState().time).toBe(20);
    key("Home");
    expect(engine.getState().time).toBe(0);
  });
});

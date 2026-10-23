// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { Profiler } from "react";
import { describe, expect, it, vi } from "vitest";

import { buildSong } from "../song";
import { fakeEngine } from "../test/engine";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { TabDocument } from "../types/tabDocument";
import { Sections } from "./Sections";

const FIRST_SONG: TabDocument = firstSongJson;

const SECTIONS = [
  { t: 0, dur: 4, label: "Intro" },
  { t: 4, dur: 5, label: "Verse 1" },
  { t: 9, dur: 4.871, label: "Chorus" },
];

function mount(fields: Partial<TabDocument> = { sections: SECTIONS }) {
  const song = buildSong({ ...FIRST_SONG, ...fields });
  const fake = fakeEngine(song);
  const onRender = vi.fn();
  render(
    <Profiler id="sections" onRender={onRender}>
      <Sections song={song} engine={fake.engine} />
    </Profiler>,
  );
  return { ...fake, onRender };
}
const current = () =>
  screen
    .getAllByRole("button")
    .filter((b) => b.getAttribute("aria-current") === "true")
    .map((b) => b.textContent);

describe("Sections", () => {
  it("lists every section with its start", () => {
    mount();
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Intro 0:00", "Verse 1 0:04", "Chorus 0:09"]);
  });

  it("seeks to a section's start on a click, and leaves the loop alone", () => {
    const { engine, at } = mount();
    at(1);
    act(() => void engine.setLoopPoint("a"));
    at(3);
    act(() => void engine.setLoopPoint("b"));

    fireEvent.click(screen.getByRole("button", { name: /^Chorus/ }));

    expect(engine.getState().time).toBe(9);
    expect(engine.getState().loop).toEqual({ a: 1, b: 3 });
  });

  it("highlights the current section as the song plays, and the earlier one after a seek back", () => {
    const { at } = mount();
    at(5);
    expect(current()).toEqual(["Verse 1 0:04"]);
    at(10);
    expect(current()).toEqual(["Chorus 0:09"]);
    at(2);
    expect(current()).toEqual(["Intro 0:00"]);
  });

  it("renders again only when the section changes", () => {
    const { at, onRender } = mount();
    at(5);
    const renders = onRender.mock.calls.length;
    at(5.5);
    at(6);
    at(8.9);
    expect(onRender).toHaveBeenCalledTimes(renders);
    at(9.5);
    expect(onRender).toHaveBeenCalledTimes(renders + 1);
  });

  it("marks the section the playhead is in as it mounts, before the first frame arrives", () => {
    const song = buildSong({ ...FIRST_SONG, sections: SECTIONS });
    const fake = fakeEngine(song);
    fake.at(10);

    render(<Sections song={song} engine={fake.engine} />);

    expect(current()).toEqual(["Chorus 0:09"]);
  });

  it("says when there are no sections", () => {
    mount({ sections: [] });
    expect(screen.getByRole("heading", { name: "Sections" })).toBeTruthy();
    expect(screen.getByText("No sections found")).toBeTruthy();
  });

  it("lists the song's chords once each, first heard first", () => {
    const chord = (t: number, symbol: string) => ({ t, dur: 1, symbol, confidence: 0.9 });
    mount({ sections: SECTIONS, chords: [chord(0, "Am"), chord(1, "C"), chord(2, "Am"), chord(3, "G")] });
    expect(screen.getByRole("heading", { name: "Chords" })).toBeTruthy();
    const list = screen.getByRole("heading", { name: "Chords" }).nextElementSibling;
    expect([...(list?.children ?? [])].map((item) => item.textContent)).toEqual(["Am", "C", "G"]);
  });

  it("keeps a mouse click on a section from taking focus", () => {
    mount();
    expect(fireEvent.mouseDown(screen.getByRole("button", { name: /^Intro/ }))).toBe(false);
  });
});

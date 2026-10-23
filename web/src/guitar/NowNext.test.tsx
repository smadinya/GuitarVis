// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { Profiler } from "react";
import { describe, expect, it, vi } from "vitest";

import { CHORD_HIDE, FADED } from "../confidence";
import { buildSong } from "../song";
import { fakeEngine } from "../test/engine";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { TabDocument } from "../types/tabDocument";
import { NowNext } from "./NowNext";

const FIRST_SONG: TabDocument = firstSongJson;

const chord = (t: number, symbol: string, confidence = 0.9) => ({ t, dur: 1, symbol, confidence });

function mount(doc: TabDocument) {
  const song = buildSong(doc);
  const fake = fakeEngine(song);
  const onRender = vi.fn();
  const view = render(
    <Profiler id="now-next" onRender={onRender}>
      <NowNext song={song} engine={fake.engine} />
    </Profiler>,
  );
  return { ...fake, onRender, box: () => view.container.querySelector(".guitar-chords") as HTMLElement | null };
}

describe("NowNext", () => {
  const AM_C = { ...FIRST_SONG, notes: [], chords: [chord(1, "Am"), chord(2, "C")] };

  it("shows the chord sounding now and the one after it", () => {
    const { at, box } = mount(AM_C);
    at(1.5);
    expect(box()?.querySelector(".now")?.textContent).toBe("Am");
    expect(box()?.querySelector(".next")?.textContent).toBe("next C");
    at(2.5);
    expect(box()?.querySelector(".now")?.textContent).toBe("C");
    expect(box()?.querySelector(".next")).toBeNull();
  });

  it("before the first chord, shows only what is next", () => {
    const { at, box } = mount(AM_C);
    at(0.5);
    expect(box()?.querySelector(".now")).toBeNull();
    expect(box()?.querySelector(".next")?.textContent).toBe("next Am");
  });

  it("fades a weak chord as the lane does", () => {
    const { at, box } = mount({ ...FIRST_SONG, notes: [], chords: [chord(1, "Am", CHORD_HIDE)] });
    at(1.5);
    expect((box()?.querySelector(".now") as HTMLElement).style.opacity).toBe(String(FADED));
  });

  it("fades a weak next chord as the lane does", () => {
    const { at, box } = mount({ ...FIRST_SONG, notes: [], chords: [chord(1, "Am"), chord(2, "C", CHORD_HIDE)] });
    at(1.5);
    expect((box()?.querySelector(".next") as HTMLElement).style.opacity).toBe(String(FADED));
  });

  it("hides inside a hidden passage, where the guitar shows the chord itself", () => {
    const hiddenAm = {
      ...FIRST_SONG,
      notes: [1, 1.3, 1.6].map((t, i) => ({ id: `w${i}`, t, dur: 0.25, midi: 57, string: 2, fret: 7, confidence: 0.05 })),
      chords: [{ t: 1, dur: 2, symbol: "Am", confidence: 0.9 }],
    };
    const { at, box } = mount(hiddenAm);
    at(1.3);
    expect(box()?.hidden).toBe(true);
    at(2.5);
    expect(box()?.hidden).toBe(false);
  });

  it("draws nothing for a song with no chords", () => {
    const { box } = mount({ ...FIRST_SONG, chords: [] });
    expect(box()).toBeNull();
  });

  it("renders only when the chord, the next one or the hidden state changes, not on every frame", () => {
    const { at, box, onRender } = mount(AM_C);
    at(1.1);
    expect(box()?.querySelector(".now")?.textContent).toBe("Am");
    const renders = onRender.mock.calls.length;

    at(1.2);
    at(1.4);
    at(1.9);

    expect(onRender).toHaveBeenCalledTimes(renders);
  });

  it("reads where the playhead stands when it mounts, as no frame comes while paused", () => {
    const song = buildSong(AM_C);
    const fake = fakeEngine(song);
    fake.at(1.5);

    const view = render(<NowNext song={song} engine={fake.engine} />);

    expect(view.container.querySelector(".now")?.textContent).toBe("Am");
    expect(view.container.querySelector(".next")?.textContent).toBe("next C");
  });

  it("shows the new song's chords after a change of song, whatever the old one's state was", () => {
    const song = buildSong(AM_C);
    const fake = fakeEngine(song);
    const view = render(<NowNext song={song} engine={fake.engine} />);
    fake.at(2.5);
    expect(view.container.querySelector(".now")?.textContent).toBe("C");

    const other = buildSong({ ...FIRST_SONG, notes: [], chords: [chord(1, "Em"), chord(2, "G")] });
    view.rerender(<NowNext song={other} engine={fake.engine} />);
    fake.at(1.5);

    expect(view.container.querySelector(".now")?.textContent).toBe("Em");
    expect(view.container.querySelector(".next")?.textContent).toBe("next G");
  });
});

import { describe, expect, it } from "vitest";

import { FADED } from "../confidence";
import { buildSong } from "../song";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { Chord, Note, TabDocument } from "../types/tabDocument";
import {
  EMPTY_MESSAGE,
  PLAYHEAD_AT,
  PX_PER_SEC,
  UNCLEAR_LABEL,
  layout,
  rowsOf,
  stringLabels,
  type DrawOp,
} from "./layout";

const FIRST_SONG: TabDocument = firstSongJson;
const VIEW = { width: 800, height: 200 };
const NO_LOOP = { a: null, b: null };
const PLAYHEAD_X = VIEW.width * PLAYHEAD_AT;

type Text = Extract<DrawOp, { kind: "text" }>;
type Line = Extract<DrawOp, { kind: "line" }>;

function texts(ops: DrawOp[]): Text[] {
  return ops.filter((op): op is Text => op.kind === "text");
}

function lines(ops: DrawOp[], paint: string): Line[] {
  return ops.filter((op): op is Line => op.kind === "line" && op.paint === paint);
}

function frets(ops: DrawOp[]): Text[] {
  return texts(ops).filter((op) => op.font === "fret" || op.font === "fretBold");
}

let ids = 0;
function note(t: number, fields: Partial<Note> = {}): Note {
  ids += 1;
  return { id: `n${ids}`, t, dur: 0.5, midi: 45, string: 1, fret: 0, confidence: 0.95, ...fields };
}

function doc(fields: Partial<TabDocument> = {}): TabDocument {
  return {
    source: { title: "t", duration_sec: 60, audio_url: "/jobs/x/audio/mix" },
    instrument: {},
    timing: {},
    ...fields,
  };
}

describe("geometry", () => {
  it("puts a note at playheadX + (t - now) * pxPerSec", () => {
    const song = buildSong(doc({ notes: [note(11, { fret: 7 })] }));

    const [seven] = frets(layout(song, 10, VIEW, NO_LOOP));

    expect(seven.text).toBe("7");
    expect(seven.x).toBe(PLAYHEAD_X + PX_PER_SEC);
  });

  it("draws the playhead at a fifth of the width", () => {
    const song = buildSong(doc());

    const [playhead] = lines(layout(song, 0, VIEW, NO_LOOP), "playhead");

    expect(playhead.x1).toBe(PLAYHEAD_X);
  });

  it("leaves out notes outside the visible window", () => {
    const song = buildSong(doc({ notes: [note(0), note(100)] }));

    expect(frets(layout(song, 50, VIEW, NO_LOOP))).toEqual([]);
  });
});

describe("strings", () => {
  it("labels standard tuning e B G D A E, highest on top", () => {
    const song = buildSong(doc());
    const rows = rowsOf(song);

    expect(stringLabels(song.tuning)).toEqual(["E", "A", "D", "G", "B", "e"]);
    expect(rows.stringY[5]).toBeLessThan(rows.stringY[0]);
    const labels = texts(layout(song, 0, VIEW, NO_LOOP))
      .filter((op) => op.font === "label" && op.align === "center")
      .sort((a, b) => a.y - b.y)
      .map((op) => op.text);
    expect(labels).toEqual(["e", "B", "G", "D", "A", "E"]);
  });

  it("keeps drop D's top E in capitals", () => {
    expect(stringLabels(["D2", "A2", "D3", "G3", "B3", "E4"])).toEqual([
      "D", "A", "D", "G", "B", "E",
    ]);
  });

  it("names sharps and flats", () => {
    expect(stringLabels(["C#2", "Bb2"])).toEqual(["C#", "Bb"]);
  });

  it("places each note on its own string", () => {
    const song = buildSong(doc({ notes: [note(1, { string: 0 }), note(1, { string: 5, fret: 3 })] }));
    const rows = rowsOf(song);

    const ops = frets(layout(song, 1, VIEW, NO_LOOP));

    expect(ops.map((op) => op.y).sort()).toEqual([rows.stringY[5], rows.stringY[0]].sort());
  });
});

describe("note states", () => {
  const song = buildSong(doc({ notes: [note(1), note(2), note(3)] }));

  it("dims the past, accents what sounds, and leaves the rest plain", () => {
    const [past, sounding, upcoming] = frets(layout(song, 2.2, VIEW, NO_LOOP));

    expect(past.alpha).toBeLessThan(1);
    expect(past.paint).toBe("text");
    expect(sounding).toMatchObject({ paint: "accent", font: "fretBold", alpha: 1 });
    expect(upcoming).toMatchObject({ paint: "text", font: "fret", alpha: 1 });
  });

  it("fades a weak note by its confidence", () => {
    const weak = buildSong(doc({ notes: [note(2, { confidence: 0 })] }));

    const [faded] = frets(layout(weak, 0, VIEW, NO_LOOP));

    expect(faded.alpha).toBe(FADED);
  });
});

describe("the degradation ladder", () => {
  it("draws bar lines only at the first beat of a bar", () => {
    const beats = [1, 2, 3, 4, 1].map((beat, i) => ({ t: i * 0.5, bar: beat === 1 && i > 0 ? 2 : 1, beat }));
    const song = buildSong(doc({ timing: { beats } }));

    expect(lines(layout(song, 0, VIEW, NO_LOOP), "bar").map((op) => op.x1)).toEqual([
      PLAYHEAD_X,
      PLAYHEAD_X + 2 * PX_PER_SEC,
    ]);
  });

  it("with no beats, draws no bar lines and still places the notes", () => {
    const song = buildSong(doc({ notes: [note(1)] }));

    const ops = layout(song, 0, VIEW, NO_LOOP);

    expect(lines(ops, "bar")).toEqual([]);
    expect(frets(ops)).toHaveLength(1);
  });

  it("collapses the chord and section rows when their tracks are empty", () => {
    const bare = buildSong(doc());
    const full = buildSong(
      doc({
        chords: [{ t: 0, dur: 2, symbol: "Em", confidence: 0.9 }],
        sections: [{ t: 0, dur: 10, label: "intro" }],
      }),
    );

    expect(rowsOf(bare)).toMatchObject({ chordY: null, sectionY: null });
    expect(rowsOf(full).height).toBeGreaterThan(rowsOf(bare).height);
    const words = texts(layout(full, 0, VIEW, NO_LOOP)).map((op) => op.text);
    expect(words).toContain("Em");
    expect(words).toContain("intro");
  });

  it("with no notes, draws the bare strings and a message", () => {
    const song = buildSong(doc());

    const ops = layout(song, 0, VIEW, NO_LOOP);

    expect(lines(ops, "string")).toHaveLength(6);
    expect(texts(ops).map((op) => op.text)).toContain(EMPTY_MESSAGE);
  });

  it("draws the real first song, which has no sections", () => {
    const song = buildSong(FIRST_SONG);

    const ops = layout(song, 3, VIEW, NO_LOOP);

    expect(rowsOf(song).sectionY).toBeNull();
    expect(frets(ops).length).toBeGreaterThan(0);
    expect(lines(ops, "bar").length).toBeGreaterThan(0);
  });
});

describe("hidden passages", () => {
  const weak = (t: number) => note(t, { confidence: 0.05, fret: 9 });
  const chord: Chord = { t: 1, dur: 1, symbol: "Am", confidence: 0.9 };

  it("draws no fret numbers inside a hidden band", () => {
    const song = buildSong(doc({ notes: [weak(1), weak(1.3), weak(1.6), note(3, { fret: 5 })] }));

    const ops = layout(song, 0, VIEW, NO_LOOP);

    expect(song.hidden).toHaveLength(1);
    expect(frets(ops).map((op) => op.text)).toEqual(["5"]);
    expect(ops.some((op) => op.kind === "rect" && op.paint === "hidden")).toBe(true);
  });

  it("labels a band with no chord over it", () => {
    const song = buildSong(doc({ notes: [weak(1), weak(1.3), weak(1.6)] }));

    expect(texts(layout(song, 0, VIEW, NO_LOOP)).map((op) => op.text)).toContain(UNCLEAR_LABEL);
  });

  it("draws the chord over a band larger, at its own confidence, and no label", () => {
    const song = buildSong(
      doc({ notes: [weak(1), weak(1.3), weak(1.6)], chords: [{ ...chord, confidence: 0 }] }),
    );

    const ops = texts(layout(song, 0, VIEW, NO_LOOP));

    expect(ops.find((op) => op.text === "Am")).toMatchObject({ font: "chordLarge", alpha: FADED });
    expect(ops.map((op) => op.text)).not.toContain(UNCLEAR_LABEL);
  });
});

describe("the loop", () => {
  it("shades between A and B and marks both", () => {
    const song = buildSong(doc());

    const ops = layout(song, 0, VIEW, { a: 1, b: 2 });

    const band = ops.find((op) => op.kind === "rect" && op.paint === "loop");
    expect(band).toMatchObject({ x: PLAYHEAD_X + PX_PER_SEC, w: PX_PER_SEC });
    expect(lines(ops, "loop")).toHaveLength(2);
  });

  it("marks A alone before B is set", () => {
    const ops = layout(buildSong(doc()), 0, VIEW, { a: 1, b: null });

    expect(ops.some((op) => op.kind === "rect" && op.paint === "loop")).toBe(false);
    expect(lines(ops, "loop")).toHaveLength(1);
  });
});

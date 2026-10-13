import { describe, expect, it } from "vitest";

import minimalJson from "../../../packages/core/tests/fixtures/minimal.tabdoc.json";
import { CHORD_FULL, FADED, emphasis, isHidden } from "../confidence";
import { EMPTY_MESSAGE, UNCLEAR_LABEL } from "../labels";
import { buildSong, type Song } from "../song";
import firstSongJson from "../test/fixtures/first-song.tabdoc.json";
import type { Chord, Note, TabDocument } from "../types/tabDocument";
import { LOOKAHEAD, MIN_LIT, cursorsOf, layout, type Mark } from "./layout";
import { DOT_R, neckOf } from "./neck";

const FIRST_SONG: TabDocument = firstSongJson;
const MINIMAL: TabDocument = minimalJson;
const WIDTH = 1000;

type Dot = Extract<Mark, { kind: "dot" }>;
type Ring = Extract<Mark, { kind: "ring" }>;
type Message = Extract<Mark, { kind: "message" }>;

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

/** The fretboard for one song, laid out at any time with one set of cursors,
 * as the component does. */
function board(song: Song) {
  const neck = neckOf(song, WIDTH);
  const cursors = cursorsOf(song);
  const at = (now: number) => layout(song, cursors, now, neck);
  return {
    neck,
    at,
    dots: (now: number) => at(now).filter((m): m is Dot => m.kind === "dot"),
    rings: (now: number) => at(now).filter((m): m is Ring => m.kind === "ring"),
    message: (now: number) => at(now).find((m): m is Message => m.kind === "message"),
  };
}

function boardOf(notes: Note[], fields: Partial<TabDocument> = {}) {
  return board(buildSong(doc({ notes, ...fields })));
}

describe("dots", () => {
  it("lights a note across [t, t + dur], at its string and fret, named by pitch", () => {
    const fretboard = boardOf([note(1, { dur: 0.5, string: 2, fret: 2, midi: 52 })]);
    const { neck } = fretboard;

    expect(fretboard.dots(0.99)).toEqual([]);
    expect(fretboard.dots(1)).toHaveLength(1);
    expect(fretboard.dots(1.5)).toHaveLength(1);
    expect(fretboard.dots(1.51)).toEqual([]);
    expect(fretboard.dots(1.2)[0]).toMatchObject({
      x: neck.noteX[2],
      y: neck.strings[2].y,
      r: DOT_R,
      name: "E",
    });
  });

  it("holds a short note for MIN_LIT", () => {
    const fretboard = boardOf([note(1, { dur: 0.04 })]);

    expect(fretboard.dots(1 + MIN_LIT - 0.01)).toHaveLength(1);
    expect(fretboard.dots(1 + MIN_LIT + 0.01)).toEqual([]);
  });

  it("draws an open string in the column left of the nut", () => {
    const fretboard = boardOf([note(1, { fret: 0 })]);

    expect(fretboard.dots(1)[0].x).toBe(fretboard.neck.noteX[0]);
    expect(fretboard.dots(1)[0].x).toBeLessThan(fretboard.neck.wireX[0]);
  });

  it("keys a dot by its note, so it is one node for its whole life", () => {
    const sounding = note(1, { dur: 1 });
    const fretboard = boardOf([sounding]);

    expect(fretboard.dots(1.1)[0].key).toBe(`dot:${sounding.id}`);
    expect(fretboard.dots(1.9)[0].key).toBe(`dot:${sounding.id}`);
  });

  it("draws one dot per string: the latest onset wins", () => {
    const early = note(1, { dur: 2, fret: 2 });
    const late = note(1.5, { dur: 2, fret: 4 });
    const fretboard = boardOf([early, late]);

    expect(fretboard.dots(1.2).map((d) => d.key)).toEqual([`dot:${early.id}`]);
    expect(fretboard.dots(1.6).map((d) => d.key)).toEqual([`dot:${late.id}`]);
  });

  it("does not light a long note again after a shorter one on its string has ended it", () => {
    const long = note(0, { dur: 4, fret: 2 });
    const short = note(1, { dur: 0.05, fret: 4 });
    const fretboard = boardOf([long, short]);

    expect(fretboard.dots(0.5).map((d) => d.key)).toEqual([`dot:${long.id}`]);
    expect(fretboard.dots(1.05).map((d) => d.key)).toEqual([`dot:${short.id}`]);
    expect(fretboard.dots(2)).toEqual([]);
  });

  it("draws notes on different strings together", () => {
    const chord = [0, 1, 2].map((string) => note(1, { string, fret: 2 }));

    expect(boardOf(chord).dots(1.1)).toHaveLength(3);
  });

  it("skips a note on a string or fret the neck does not have", () => {
    // A document with no tuning gets six strings; its notes might not fit.
    const fretboard = boardOf([note(1, { string: 6, fret: 3 }), note(1, { string: 0, fret: -1 })]);

    expect(fretboard.at(1)).toEqual([]);
  });
});

describe("rings", () => {
  const coming = note(2, { string: 3, fret: 5, midi: 60 });
  const fretboard = boardOf([coming]);

  it("appears LOOKAHEAD before the onset at twice the dot's radius", () => {
    expect(fretboard.rings(2 - LOOKAHEAD - 0.01)).toEqual([]);
    expect(fretboard.rings(2 - LOOKAHEAD)[0]).toMatchObject({
      x: fretboard.neck.noteX[5],
      y: fretboard.neck.strings[3].y,
      r: 2 * DOT_R,
    });
  });

  it("closes linearly to the dot's radius at the onset, where the dot fills it", () => {
    expect(fretboard.rings(2 - LOOKAHEAD / 2)[0].r).toBeCloseTo(1.5 * DOT_R);
    expect(fretboard.rings(2)[0].r).toBe(DOT_R);
    expect(fretboard.dots(2)).toHaveLength(1);
    expect(fretboard.rings(2.01)).toEqual([]);
  });

  it("is unlabelled: the name appears when the note sounds", () => {
    expect(fretboard.rings(1.5)[0]).not.toHaveProperty("name");
  });

  it("draws one ring per position, for the nearest onset", () => {
    const strums = [1, 1.3, 1.6, 1.9].map((t) => note(t, { string: 0, fret: 3 }));
    const strummed = boardOf(strums);

    const rings = strummed.rings(0.8);

    expect(rings).toHaveLength(1);
    expect(rings[0].key).toBe("ring:0:3");
    expect(rings[0].r).toBeCloseTo(DOT_R * (1 + 0.2 / LOOKAHEAD));
  });

  it("can share a position with a dot: the cue for a repeated note", () => {
    const repeated = boardOf([note(1, { fret: 3 }), note(1.4, { fret: 3 })]);

    const marks = repeated.at(1.1);

    expect(marks.map((m) => m.kind).sort()).toEqual(["dot", "ring"]);
    const [dot, ring] = [marks.find((m) => m.kind === "dot"), marks.find((m) => m.kind === "ring")];
    expect([dot?.x, dot?.y]).toEqual([ring?.x, ring?.y]);
  });
});

describe("confidence", () => {
  it("sets the opacity of dots and rings by emphasis(confidence)", () => {
    const fretboard = boardOf([
      note(1, { string: 0, confidence: 0.55 }),
      note(1.5, { string: 1, confidence: 0.2 }),
    ]);

    const marks = fretboard.at(1);

    expect(marks.find((m) => m.kind === "dot")?.opacity).toBe(emphasis(0.55));
    expect(marks.find((m) => m.key === "ring:1:0")?.opacity).toBe(FADED);
  });

  const weak = (t: number) => note(t, { confidence: 0.05, string: 2, fret: 7 });

  it("gives a note in a hidden passage neither a dot nor a ring, even before the passage", () => {
    const fretboard = boardOf([weak(1), weak(1.3), weak(1.6), note(3, { fret: 5 })]);

    expect(fretboard.at(0.5)).toEqual([]); // all three hidden notes are within LOOKAHEAD
    expect(fretboard.dots(1.35)).toEqual([]);
    expect(fretboard.rings(1.9).map((r) => r.key)).toEqual(["ring:1:5"]);
  });

  it("keeps a hidden note dark after its passage ends, however long it sounds", () => {
    const fretboard = boardOf([
      weak(1),
      weak(1.3),
      note(1.6, { confidence: 0.05, string: 3, dur: 3 }),
      note(2, { fret: 5 }),
    ]);

    expect(fretboard.dots(3)).toEqual([]);
  });

  it("lights every note the tab strip shows, and no other, across the real first song", () => {
    const song = buildSong(FIRST_SONG);
    const fretboard = board(song);
    const lit = new Set<string>();

    for (let now = 0; now <= song.duration; now += 1 / 120) {
      for (const dot of fretboard.dots(now)) lit.add(dot.key);
    }

    const shown = song.notes.filter((n) => !isHidden(song.hidden, n.t)).map((n) => `dot:${n.id}`);
    expect(song.hidden.length).toBeGreaterThan(0);
    expect([...lit].sort()).toEqual(shown.sort());
  });
});

describe("hidden passages", () => {
  const weak = (t: number) => note(t, { confidence: 0.05 });
  const am: Chord = { t: 1, dur: 1, symbol: "Am", confidence: 0.9 };

  it("shows the sounding chord's symbol, at the chord's own confidence", () => {
    const fretboard = boardOf([weak(1), weak(1.3), weak(1.6)], { chords: [{ ...am, confidence: 0 }] });

    expect(fretboard.message(1.2)).toMatchObject({ text: "Am", chord: true, opacity: FADED });
  });

  it("shows a confident chord at full strength", () => {
    const fretboard = boardOf([weak(1), weak(1.3), weak(1.6)], { chords: [{ ...am, confidence: CHORD_FULL }] });

    expect(fretboard.message(1.2)?.opacity).toBe(1);
  });

  it("says the passage is unclear when no chord sounds", () => {
    const fretboard = boardOf([weak(1), weak(1.3), weak(1.6)], { chords: [{ ...am, t: 5 }] });

    expect(fretboard.message(1.2)).toMatchObject({ text: UNCLEAR_LABEL, chord: false });
  });

  it("shows no message outside a passage", () => {
    const fretboard = boardOf([weak(1), weak(1.3), weak(1.6)], { chords: [am] });

    expect(fretboard.message(0.5)).toBeUndefined();
    expect(fretboard.message(2.5)).toBeUndefined();
  });

  it("centres the message on the fingerboard", () => {
    const fretboard = boardOf([weak(1), weak(1.3), weak(1.6)]);
    const { neck } = fretboard;

    expect(fretboard.message(1.2)).toMatchObject({
      x: (neck.wireX[0] + neck.wireX[neck.frets]) / 2,
      y: (neck.top + neck.bottom) / 2,
    });
  });
});

describe("the other cases", () => {
  it("draws the minimal fixture: the open low E, and a ring closing on the D string's second fret", () => {
    const fretboard = board(buildSong(MINIMAL));

    expect(fretboard.at(0.1)).toEqual([
      expect.objectContaining({ kind: "ring", key: "ring:2:2" }),
      expect.objectContaining({ kind: "dot", key: "dot:n_0000", name: "E", x: fretboard.neck.noteX[0] }),
    ]);
  });

  it("shows the message, and nothing else, for a document with no notes", () => {
    const fretboard = boardOf([]);

    expect(fretboard.at(0)).toEqual([expect.objectContaining({ kind: "message", text: EMPTY_MESSAGE })]);
  });

  it("is right straight after a jump back, as when an A/B loop restarts", () => {
    const notes = Array.from({ length: 40 }, (_, i) => note(i * 0.25, { string: i % 6, fret: i % 9 }));
    const song = buildSong(doc({ notes }));
    const playing = board(song);

    for (let now = 0; now <= 8; now += 1 / 60) playing.at(now);

    expect(playing.at(2)).toEqual(board(song).at(2));
  });
});

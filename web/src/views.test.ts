/**
 * The tab strip and the fretboard each read the hidden passages for their own
 * window, by the same rule written twice. This runs both over one song built
 * so that a read narrowed to the window misses passages a note is still
 * sounding from, and pins each view to isHidden. The two copies cannot drift
 * apart without failing here.
 */
import { describe, expect, it } from "vitest";

import { isHidden } from "./confidence";
import { cursorsOf, layout as fretboardLayout } from "./fretboard/layout";
import { neckOf } from "./fretboard/neck";
import { cursorsOf as soundingCursors, sounding } from "./guitar/sounding";
import { buildSong, type Song } from "./song";
import { PLAYHEAD_AT, PX_PER_SEC, layout as tabLayout, rowsOf } from "./tab/layout";
import type { Note } from "./types/tabDocument";

const WIDTH = 800;
const NO_LOOP = { a: null, b: null };
const OPEN = [40, 45, 50, 55, 59, 64]; // standard tuning, lowest string first

/** Six blocks, 8 s apart. Each opens with a weak run on one string, a hidden
 * passage whose last note sounds on for seconds after the passage ends, then
 * confident notes on the other strings. */
function separatingSong(): Song {
  const notes: Note[] = [];
  const add = (t: number, string: number, fret: number, fields: Partial<Note> = {}) =>
    notes.push({ id: `n${notes.length}`, t, dur: 0.3, midi: OPEN[string] + fret, string, fret, confidence: 0.95, ...fields });
  for (let block = 0; block < 6; block++) {
    const start = block * 8;
    add(start, block, 2, { confidence: 0.05 });
    add(start + 0.3, block, 4, { confidence: 0.05 });
    add(start + 0.6, block, 5, { confidence: 0.05, dur: 4 + block * 0.5 });
    for (let i = 0; i < 8; i++) {
      add(start + 1 + i * 0.6, (block + 1 + (i % 5)) % 6, (i * 3) % 10, { dur: 0.2 + (i % 3) * 0.4 });
    }
  }
  return buildSong({
    source: { title: "t", duration_sec: 50, audio_url: "/jobs/x/audio/mix" },
    instrument: {},
    timing: {},
    notes,
  });
}

const song = separatingSong();
const shown = (note: Note) => !isHidden(song.hidden, note.t);
const grid = Array.from({ length: 50 * 30 }, (_, i) => i / 30);

describe("both views hide the same notes", () => {
  it("is given a song that tells a narrow read of the passages from a wide one", () => {
    const past = (WIDTH * PLAYHEAD_AT) / PX_PER_SEC; // the strip's seconds left of the playhead

    expect(song.hidden).toHaveLength(6);
    for (const passage of song.hidden) {
      const outlasting = song.notes.filter(
        (n) => n.t >= passage.from && n.t < passage.to && n.t + n.dur > passage.to + past,
      );
      expect(outlasting, `passage at ${passage.from}`).toHaveLength(1);
    }
  });

  it("the tab strip draws every note in its window that isHidden leaves shown, and no other", () => {
    const rows = rowsOf(song);
    const playheadX = WIDTH * PLAYHEAD_AT;

    for (const now of grid) {
      const from = now - playheadX / PX_PER_SEC;
      const to = now + (WIDTH - playheadX) / PX_PER_SEC;
      const expected = song.notes
        .filter((n) => n.t <= to && n.t + n.dur >= from && shown(n))
        .map((n) => `${playheadX + (n.t - now) * PX_PER_SEC}|${rows.stringY[n.string]}|${n.fret}`);
      const drawn = tabLayout(song, now, { width: WIDTH, height: rows.height }, NO_LOOP).flatMap((op) =>
        op.kind === "text" && (op.font === "fret" || op.font === "fretBold") ? [`${op.x}|${op.y}|${op.text}`] : [],
      );

      expect(drawn.sort(), `at ${now}`).toEqual(expected.sort());
    }
  });

  it("the fretboard lights every note that isHidden leaves shown, and no other", () => {
    const neck = neckOf(song, WIDTH);
    const cursors = cursorsOf(song);
    const lit = new Set<string>();

    // Each onset, where its note is sure to be lit if shown, and a steady sweep.
    for (const now of [...song.notes.map((n) => n.t), ...grid]) {
      for (const mark of fretboardLayout(song, cursors, now, neck)) {
        if (mark.kind === "dot") lit.add(mark.key);
      }
    }

    const expected = song.notes.filter(shown).map((n) => `dot:${n.id}`);
    expect([...lit].sort()).toEqual(expected.sort());
  });

  it("sounding() lights every note that isHidden leaves shown, and no other", () => {
    const cursors = soundingCursors(song);
    const lit = new Set<string>();

    for (const now of [...song.notes.map((n) => n.t), ...grid]) {
      for (const note of sounding(song, cursors, now).notes) lit.add(note.key);
    }

    expect([...lit].sort()).toEqual(song.notes.filter(shown).map((n) => `dot:${n.id}`).sort());
  });
});

/** Anything with an onset and a duration, in seconds. */
export interface Span {
  t: number;
  dur: number;
}

/**
 * The notes sounding at any moment of a time window, answered from notes
 * sorted once by onset.
 *
 * During normal playback the window moves forward a little each frame, and
 * two pointers follow it. A backward jump, a forward jump past the last
 * window, or a window that shrinks re-seats them by binary search. Per-call
 * work is proportional to the notes in the window, not the song's length.
 *
 * Stateful, so each view keeps its own: `new NoteCursor(song.notes)`.
 */
export class NoteCursor<T extends Span> {
  private readonly notes: readonly T[];
  private readonly longest: number;
  private lo = 0; // the first note that could still sound at `from`
  private hi = 0; // the first note with t > to
  private from = Number.POSITIVE_INFINITY;
  private to = Number.NEGATIVE_INFINITY;

  /** `notes` must be sorted by onset. */
  constructor(notes: readonly T[]) {
    this.notes = notes;
    this.longest = notes.reduce((longest, note) => Math.max(longest, note.dur), 0);
  }

  /** The notes whose [t, t + dur] overlaps [from, to], in onset order. */
  window(from: number, to: number): T[] {
    // A note is out of reach once t + longest < from. That is the filter's own
    // sum, `t + dur >= from`, with dur at its largest, so the bound can never
    // drop a note the filter would keep. (`t < from - longest` rounds
    // differently and can.)
    const following = from >= this.from && from <= this.to && to >= this.to;
    if (following) {
      while (this.lo < this.notes.length && this.notes[this.lo].t + this.longest < from) this.lo++;
      while (this.hi < this.notes.length && this.notes[this.hi].t <= to) this.hi++;
    } else {
      this.lo = firstIndex(this.notes, (note) => note.t + this.longest >= from);
      this.hi = firstIndex(this.notes, (note) => note.t > to);
    }
    this.from = from;
    this.to = to;

    const found: T[] = [];
    for (let i = this.lo; i < this.hi; i++) {
      const note = this.notes[i];
      if (note.t + note.dur >= from) found.push(note);
    }
    return found;
  }
}

/**
 * The items whose [start, end] overlaps [from, to], for items sorted so that
 * both their starts and their ends rise: beats, whose start is their end, or
 * spans that never overlap. Stateless, so any view may share the list: a
 * binary search, then only the items returned.
 */
export function inWindow<T>(
  items: readonly T[],
  from: number,
  to: number,
  start: (item: T) => number,
  end: (item: T) => number = start,
): T[] {
  const found: T[] = [];
  for (let i = firstIndex(items, (item) => end(item) >= from); i < items.length; i++) {
    if (start(items[i]) > to) break;
    found.push(items[i]);
  }
  return found;
}

/** The first index whose note passes `test`, which must be monotonic. */
function firstIndex<T>(items: readonly T[], test: (item: T) => boolean): number {
  let lo = 0;
  let hi = items.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (test(items[mid])) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}

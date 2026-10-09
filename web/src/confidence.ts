/**
 * The confidence rule, shared by every view so that it cannot drift between
 * them. Phase 5's fretboards import this module unchanged.
 *
 * HIDE and FULL are measured, not chosen by eye. Where they came from, and
 * what they do to real songs, is recorded in
 * docs/specs/006-tab-view-sync/calibration.md.
 */
import type { Note } from "./types/tabDocument";

/** Below HIDE, a note is more often wrong than right (calibration.md). */
export const HIDE = 0.5;
/** At or above FULL, a note is right at least 80% of the time (calibration.md). */
export const FULL = 0.6;
/** The opacity of anything at or below HIDE. */
export const FADED = 0.35;
/** A passage is hidden when at least this many weak notes run together... */
export const MIN_RUN = 3;
/** ...with no gap between neighbouring onsets longer than this. */
export const MAX_GAP_SEC = 1;

export interface Thresholds {
  hide: number;
  full: number;
}

export const THRESHOLDS: Thresholds = { hide: HIDE, full: FULL };

/** A time span of the song, in seconds. */
export interface Passage {
  from: number;
  to: number;
}

/**
 * The opacity to draw a note or chord at: FADED at or below `hide`, 1 at or
 * above `full`, linear in between. Equal thresholds make it a step.
 */
export function emphasis(
  confidence: number,
  { hide, full }: Thresholds = THRESHOLDS,
): number {
  if (confidence >= full) return 1;
  if (confidence <= hide) return FADED;
  return FADED + ((1 - FADED) * (confidence - hide)) / (full - hide);
}

/**
 * The spans to hide: runs of at least MIN_RUN consecutive notes, in onset
 * order across all strings, all below `hide`, with no gap between
 * neighbouring onsets over MAX_GAP_SEC. A run hides from its first onset to
 * its latest end. A lone weak note fades but leaves no hole. Spans that
 * overlap are merged. Run once per document.
 */
export function hiddenPassages(
  notes: readonly Note[],
  hide: number = HIDE,
): Passage[] {
  const passages: Passage[] = [];
  let run: Note[] = [];

  const close = () => {
    if (run.length >= MIN_RUN) {
      const from = run[0].t;
      const to = Math.max(...run.map((note) => note.t + note.dur));
      const last = passages.at(-1);
      if (last !== undefined && from <= last.to) last.to = Math.max(last.to, to);
      else passages.push({ from, to });
    }
    run = [];
  };

  for (const note of [...notes].sort((a, b) => a.t - b.t)) {
    if (note.confidence >= hide) {
      close();
      continue;
    }
    const previous = run.at(-1);
    if (previous !== undefined && note.t - previous.t > MAX_GAP_SEC) close();
    run.push(note);
  }
  close();
  return passages;
}

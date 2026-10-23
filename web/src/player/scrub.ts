/**
 * Where things sit on the scrubber, decided apart from the drawing: section
 * ticks, the loop's band and edges, and the time under a pointer. Every
 * position is a fraction of the track's width, so the scrubber paints them as
 * percentages and never needs to know the duration itself.
 */
import type { LoopPoints } from "../playback/engine";
import type { Section } from "../types/tabDocument";

/** Whether a duration can be divided by: a positive, finite number of seconds. */
function usable(duration: number): boolean {
  return Number.isFinite(duration) && duration > 0;
}

/**
 * t as a fraction of the track, clamped to [0, 1]. A duration that is not a
 * positive finite number gives 0, so a media element that has not reported its
 * length yet draws everything at the start instead of at NaN.
 */
export function fraction(t: number, duration: number): number {
  if (!usable(duration) || Number.isNaN(t)) return 0;
  return Math.min(1, Math.max(0, t / duration));
}

/**
 * The time under a pointer at clientX, for a track at `left` that is `width`
 * wide. Clamped to [0, duration], so a drag that leaves the track still lands
 * on its ends; a track with no width (not laid out yet) gives 0.
 */
export function timeAt(clientX: number, left: number, width: number, duration: number): number {
  if (!usable(duration) || !(width > 0)) return 0;
  return fraction((clientX - left) / width, 1) * duration;
}

/** What the scrubber draws over its track. */
export interface ScrubMarks {
  /** A tick at each section start, strictly inside (0, 1): a start at 0 is
   * the track's own start, and one at or past the end is off the track. */
  ticks: number[];
  /** Both points set: min to max, as the engine and the tab strip read them. */
  band: { from: number; to: number } | null;
  /** Each set point. */
  edges: Array<{ point: "a" | "b"; at: number }>;
}

/**
 * The ticks, band and edges for a track `duration` seconds long. The band runs
 * from the earlier point to the later one whichever was set first, because the
 * engine loops min to max and the scrubber must show what will play. A point
 * past the media's reported duration is clamped to the end, not dropped: the
 * loop is still set. Without a usable duration nothing can be placed, so
 * nothing is drawn.
 */
export function scrubMarks(duration: number, sections: readonly Section[], loop: LoopPoints): ScrubMarks {
  if (!usable(duration)) return { ticks: [], band: null, edges: [] };
  // Strictly inside the track drops a start at 0 and a start at or past the
  // end. The first section is no exception: it may begin after 0, and that
  // boundary is as real as any other.
  const ticks = sections
    .map((s) => fraction(s.t, duration))
    .filter((at) => at > 0 && at < 1);
  const edges: ScrubMarks["edges"] = [];
  if (loop.a !== null) edges.push({ point: "a", at: fraction(loop.a, duration) });
  if (loop.b !== null) edges.push({ point: "b", at: fraction(loop.b, duration) });
  const band =
    loop.a !== null && loop.b !== null
      ? {
          from: fraction(Math.min(loop.a, loop.b), duration),
          to: fraction(Math.max(loop.a, loop.b), duration),
        }
      : null;
  return { ticks, band, edges };
}

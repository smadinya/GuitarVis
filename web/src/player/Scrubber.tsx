import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { KeyboardEvent, PointerEvent } from "react";

import { TrackCursor } from "../playback/cursor";
import { SEEK_STEP_SEC, type PlaybackEngine } from "../playback/engine";
import type { Section } from "../types/tabDocument";
import { fraction, scrubMarks, timeAt } from "./scrub";
import { clock } from "./time";

export interface ScrubberProps {
  engine: PlaybackEngine;
  sections: readonly Section[];
  /** The playhead's section label, spoken with the time; null when none is
   * current. During a drag the slider speaks the section under the pointer
   * instead, which it finds in `sections`. */
  section: string | null;
}

const percent = (f: number) => `${f * 100}%`;

/** What a drag shows of the time under the pointer: the whole second the
 * readout says, and the section it is in. Nothing else of the drag is
 * drawn, so the scrubber renders when one of these two changes and not on
 * every pointer move. */
interface Preview {
  second: number;
  section: number;
}

/** A drag in progress: the exact time under the pointer, which the seek and
 * the knob use, and the preview last drawn from it. */
interface Drag {
  t: number;
  preview: Preview;
}

/**
 * The song's position as a slider: the playhead, a tick at each section, and
 * the A–B loop. A drag previews the time under the pointer and seeks once, on
 * release, so a drag never makes the audio stutter through every position it
 * passes. The arrow keys seek by `SEEK_STEP_SEC`, Home and End go to the ends.
 *
 * The slider speaks a time and its section. That is the playhead's, until a
 * drag begins; then both follow the pointer, so what is spoken is what a
 * release would seek to. A drag keeps its exact time apart from what it
 * shows, so the scrubber renders when the second or the section under the
 * pointer changes, not on every move.
 *
 * The knob and the played part follow playback without React: `place` writes
 * their transforms, from `onFrame` and from a drag, and nothing in the JSX
 * styles them, so the readout's 4 Hz re-render never fights the frames. While
 * a drag is held the frames leave the knob to the pointer.
 */
export function Scrubber({ engine, sections, section }: ScrubberProps) {
  const { duration, time, loop } = useSyncExternalStore(engine.subscribe, engine.getState);
  // What the pointer is over while dragging; null otherwise. It is state for
  // the preview's text, and `drag` is the exact time for the handlers, which
  // must see it before React has re-rendered.
  const [preview, setPreview] = useState<Preview | null>(null);
  const drag = useRef<Drag | null>(null);
  // The section under the pointer, for the slider's spoken value in a drag.
  const cursor = useMemo(() => new TrackCursor(sections), [sections]);
  const headRef = useRef<HTMLDivElement>(null);
  const playedRef = useRef<HTMLDivElement>(null);

  const place = useCallback((f: number) => {
    if (headRef.current !== null) headRef.current.style.transform = `translateX(${f * 100}%)`;
    if (playedRef.current !== null) playedRef.current.style.transform = `scaleX(${f})`;
  }, []);

  useEffect(
    () =>
      engine.onFrame((t) => {
        if (drag.current === null) place(fraction(t, engine.getState().duration));
      }),
    [engine, place],
  );

  /** Move the knob and the preview to the pointer. */
  const follow = (event: PointerEvent<HTMLDivElement>) => {
    const { duration: length } = engine.getState();
    const rect = event.currentTarget.getBoundingClientRect();
    const t = timeAt(event.clientX, rect.left, rect.width, length);
    const next = { second: Math.floor(t), section: cursor.at(t).current };
    const before = drag.current?.preview;
    drag.current = { t, preview: next };
    place(fraction(t, length));
    if (before?.second !== next.second || before.section !== next.section) setPreview(next);
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    // So the drag goes on over the rest of the page, and past the track's
    // ends. jsdom has no pointer capture, hence the optional call.
    event.currentTarget.setPointerCapture?.(event.pointerId);
    follow(event);
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (drag.current !== null) follow(event);
  };

  const onPointerUp = () => {
    const held = drag.current;
    if (held === null) return;
    drag.current = null;
    setPreview(null);
    engine.seek(held.t);
  };

  /** A drag that ends without a release: the knob goes back to the playhead.
   * After a release there is no drag left, so this does nothing. */
  const onPointerCancel = () => {
    if (drag.current === null) return;
    drag.current = null;
    setPreview(null);
    engine.redraw();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // The browser's own shortcuts (Alt+← is back) are not ours, as in the
    // page's key handler.
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "ArrowRight" || event.key === "ArrowUp") engine.seekBy(SEEK_STEP_SEC);
    else if (event.key === "ArrowLeft" || event.key === "ArrowDown") engine.seekBy(-SEEK_STEP_SEC);
    else if (event.key === "Home") engine.seek(0);
    else if (event.key === "End") engine.seek(duration);
    else return;
    // The window's handler seeks on the arrows too, and skips a key that is
    // already handled: without this one press would seek twice.
    event.preventDefault();
  };

  const shown = preview?.second ?? time;
  const spoken = preview === null ? section : (sections[preview.section]?.label ?? null);
  const marks = scrubMarks(duration, sections, loop);
  return (
    <div
      className="scrubber"
      role="slider"
      tabIndex={0}
      aria-label="Position"
      aria-valuemin={0}
      aria-valuemax={Math.round(duration)}
      aria-valuenow={Math.round(shown)}
      aria-valuetext={spoken === null ? clock(shown) : `${clock(shown)}, ${spoken}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onLostPointerCapture={onPointerCancel}
      onKeyDown={onKeyDown}
    >
      <div className="scrub-track">
        <div className="scrub-played" ref={playedRef} />
      </div>
      {marks.band !== null && (
        <div
          className="scrub-band"
          style={{ left: percent(marks.band.from), width: percent(marks.band.to - marks.band.from) }}
        />
      )}
      {marks.edges.map((edge) => (
        <div key={edge.point} className="scrub-edge" data-point={edge.point} style={{ left: percent(edge.at) }} />
      ))}
      {marks.ticks.map((at, index) => (
        <div key={index} className="scrub-tick" style={{ left: percent(at) }} />
      ))}
      <div className="scrub-head" ref={headRef}>
        <div className="scrub-knob" />
        {preview !== null && <span className="scrub-preview">{clock(preview.second)}</span>}
      </div>
    </div>
  );
}

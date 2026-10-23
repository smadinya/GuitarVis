import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { KeyboardEvent, PointerEvent } from "react";

import { SEEK_STEP_SEC, type PlaybackEngine } from "../playback/engine";
import type { Section } from "../types/tabDocument";
import { fraction, scrubMarks, timeAt } from "./scrub";
import { clock } from "./time";

export interface ScrubberProps {
  engine: PlaybackEngine;
  sections: readonly Section[];
  /** The current section's label, spoken with the time; null when none is current. */
  section: string | null;
}

const percent = (f: number) => `${f * 100}%`;

/**
 * The song's position as a slider: the playhead, a tick at each section, and
 * the A–B loop. A drag previews the time under the pointer and seeks once, on
 * release, so a drag never makes the audio stutter through every position it
 * passes. The arrow keys seek by `SEEK_STEP_SEC`, Home and End go to the ends.
 *
 * The knob and the played part follow playback without React: `place` writes
 * their transforms, from `onFrame` and from a drag, and nothing in the JSX
 * styles them, so the readout's 4 Hz re-render never fights the frames. While
 * a drag is held the frames leave the knob to the pointer.
 */
export function Scrubber({ engine, sections, section }: ScrubberProps) {
  const { duration, time, loop } = useSyncExternalStore(engine.subscribe, engine.getState);
  // What the pointer is over while dragging; null otherwise. It is state for
  // the preview's text, and `drag` is the same time for the handlers, which
  // must see it before React has re-rendered.
  const [preview, setPreview] = useState<number | null>(null);
  const drag = useRef<number | null>(null);
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
    drag.current = t;
    place(fraction(t, length));
    setPreview(t);
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
    const t = drag.current;
    if (t === null) return;
    drag.current = null;
    setPreview(null);
    engine.seek(t);
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

  const shown = preview ?? time;
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
      aria-valuetext={section === null ? clock(shown) : `${clock(shown)}, ${section}`}
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
        {preview !== null && <span className="scrub-preview">{clock(preview)}</span>}
      </div>
    </div>
  );
}
